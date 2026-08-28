# api/contrapartida/servico.py

"""Conciliacao do CT-e de contrapartida do agregado.



Hoje NENHUMA contrapartida e emitida (confirmado pelo usuario em 26/08/2026).

Entao esta tela nao mede cobertura - ela dimensiona a fila, separa quem PODE

emitir de quem NAO PODE, e prepara o cadastro que a emissao vai exigir.



O QUE ELA NAO FAZ, E POR QUE

---------------------------

Nao emite nada. Emissao de CT-e em nome de terceiro exige procuracao vigente,

certificado A1 e enquadramento fiscal definido - e nenhuma dessas tres coisas e

decisao de software. A tela existe para essas decisoes serem tomadas com o

numero na mao.



E nao mostra passivo historico. CT-e NAO se emite retroativo (a SEFAZ recusa
data de emissao fora da janela), entao o acumulado de anos anteriores nao e
trabalho desta tela - a pergunta aqui e "o que preciso emitir agora". O numero
fica registrado em docs/contrapartida-perguntas-contabilidade.md, que e onde
ele serve: decisao de contabilidade e juridico.

"""

from __future__ import annotations



import logging

from datetime import date, datetime, timedelta



from api import db

from api.contrapartida import cadastro
from api.contrapartida.sql import (FROTA_AGR_SQL, NOMES_SQL,
                                   POR_AGREGADO_SQL, POR_MES_SQL)



log = logging.getLogger("cortex.contrapartida")



# Rotulos das duas populacoes. Escritos aqui e nao no front porque a diferenca

# e FISCAL, nao de apresentacao: somar as duas produz um passivo falso.

CLASSES = {

    "pj": "PJ — emite CT-e",
    "tac": "TAC (CPF) — não emite CT-e",

    "indefinido": "documento do proprietário indefinido",

}



# O TAC nao e sujeito passivo do CT-e (Lei 11.442): a documentacao dele e

# CIOT + RPA. Isto nao e limitacao da rotina - e do documento.

# A regra mora em `cadastro` porque o LOTE tambem precisa dela: enquanto ela
# so existia aqui, a tela marcava o agregado sem IE como pendente e o lote
# emitia para ele assim mesmo. O apelido continua para quem ja chamava por
# este nome.
_ie_utilizavel = cadastro.ie_utilizavel


NOTA_TAC = ("Transportador Autônomo de Cargas não emite CT-e — a documentação "

            "dele é CIOT (Lei 11.442) e RPA. Estes CT-e não entram na fila de "
            "contrapartida por natureza do documento, não por falta de "
            "certificado.")





def _janela(de: str | None, ate: str | None) -> tuple[str, str]:
    """Sem filtro, a tela abre no DIA DE HOJE.

    A fila de contrapartida e trabalho DIARIO: o CT-e sai hoje e o documento do
    agregado tem de sair junto. Abrir em seis meses fazia a tela responder
    "quanto acumulou" quando a pergunta do dia e "o que preciso emitir agora" -
    e o acumulado continua a um clique no filtro.
    """
    hoje = date.today()
    d_ate = date.fromisoformat(ate) if ate else hoje
    d_de = date.fromisoformat(de) if de else d_ate
    if d_de > d_ate:
        d_de, d_ate = d_ate, d_de
    return d_de.isoformat(), (d_ate + timedelta(days=1)).isoformat()


def _serial(linhas) -> list[dict]:
    """date -> 'AAAA-MM-DD'. O JSONResponse nao serializa datetime.date e
    devolve 500 - e o teste que so olhava os KPIs nunca chegava na
    serializacao, entao o defeito so apareceu na tela."""
    saida = []
    for r in linhas:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = v.isoformat()[:10] if isinstance(v, date) else v.isoformat()
        saida.append(d)
    return saida


def get_contrapartida(de: str | None = None, ate: str | None = None,
                      busca: str | None = None) -> dict:

    d_de, d_ate = _janela(de, ate)
    par = {"de": d_de, "ate": d_ate}

    mes = db.query(POR_MES_SQL, par)
    agreg = db.query(POR_AGREGADO_SQL, par)

    frota = db.query(FROTA_AGR_SQL, {})



    def _soma(linhas, classe, campo):
        return sum(x[campo] for x in linhas if x["classe"] == classe)



    # PRONTIDAO: procuracao vigente + certificado A1 valido + senha no cofre.
    # Sem isto a fila diz "14 mil CT-e a emitir" sem dizer que a emissao ainda
    # nao esta autorizada para ninguem - numero grande sem o que o desarma.
    try:
        pront = cadastro.mapa()
    except Exception as exc:  # noqa: BLE001
        log.warning("cadastro de procuracao/certificado indisponivel: %s", exc)
        pront = {}
    for x in agreg:
        p = pront.get(x["documento"]) or {}
        x["prontidao"] = p.get("prontidao") or {
            "pronto": False, "faltas": ["sem procuração cadastrada",
                                        "sem certificado cadastrado"],
            "alertas": []}
    # BUSCA por nome ou CNPJ, em memoria. A consulta ja traz os ~85 agregados;
    # refazer o SQL por um filtro de texto multiplicaria a chave de cache sem
    # ganho (mesmo padrao do Painel de Custos). Vale para a TABELA e para os
    # KPIs do recorte.
    if (busca or "").strip():
        alvo = " ".join((busca or "").lower().split())
        so_dig = "".join(c for c in alvo if c.isdigit())
        agreg = [x for x in agreg
                 if alvo in (x.get("nome") or "").lower()
                 or (so_dig and so_dig in (x.get("documento") or ""))]

    pj = [x for x in agreg if x["classe"] == "pj"]

    tac = [x for x in agreg if x["classe"] == "tac"]
    indef = [x for x in agreg if x["classe"] == "indefinido"]



    # PENDENCIA CADASTRAL: o que a emissao exige e o cadastro pode nao ter.
    # Descobrir isso na transmissao custa uma rejeicao POR DOCUMENTO - com

    # 3 mil CT-e/mes, e o tipo de erro que para a operacao.
    faltando = [{"documento": x["documento"], "nome": x["nome"],

                 "falta": [c for c, ok in (
                     ("razão social", bool(x["nome"])),
                     # "ISENTO" nao e inscricao — e o motivo vai no rotulo,
                     # senao a pendencia parece campo em branco
                     (f"inscrição estadual ({x['ie']})" if x["ie"]
                      else "inscrição estadual",
                      _ie_utilizavel(x["ie"])),
                     ("RNTRC", bool(x["rntrc"])),
                     ("município/UF", bool(x["cidade"])))
                     if not ok]}
                for x in pj]

    faltando = [x for x in faltando if x["falta"]]

    # a TABELA recebe a lista pronta: recalcular no front duplicava a regra e
    # ela divergiu no mesmo dia em que "ISENTO" passou a contar como pendencia
    _por_doc = {x["documento"]: x["falta"] for x in faltando}
    for x in agreg:
        x["falta"] = (_por_doc.get(x["documento"], [])
                      if x["classe"] == "pj" else [])



    _tx = _transmissoes()
    return {
        "periodo": {"de": d_de, "ate": d_ate, "busca": busca or ""},
        "kpis": {
            "ctes_pj": _soma(mes, "pj", "ctes"),
            "valor_pj": round(_soma(mes, "pj", "valor"), 2),
            "agregados_pj": len(pj),
            "ctes_tac": _soma(mes, "tac", "ctes"),
            "valor_tac": round(_soma(mes, "tac", "valor"), 2),
            "agregados_tac": len(tac),
            "ctes_indefinido": _soma(mes, "indefinido", "ctes"),
            "agregados_indefinido": len(indef),
            "pendencia_cadastral": len(faltando),
            "sem_ie": sum(1 for x in pj if not _ie_utilizavel(x["ie"])),
            "prontos_para_emitir": sum(1 for x in pj
                                       if (x.get("prontidao") or {}).get("pronto")),
            # Deixa de ser zero declarado: agora ha transmissoes de verdade,
            # ainda que so em homologacao. Producao e contada a parte porque
            # homologacao NAO tem valor fiscal - somar as duas num numero so
            # faria a tela anunciar uma fila resolvida que nao foi.
            "emitidas": _tx["producao"],
            "emitidas_homologacao": _tx["homologacao"],
            "emitidas_autorizadas": _tx["autorizadas"],
            "emitidas_avaliadas": _tx.get("avaliadas", 0),
            "emitidas_esperadas": _tx.get("esperadas_homologacao", 0),
            "emitidas_producao_autorizadas": _tx.get("producao_autorizadas", 0),
            "emitidas_recusadas": _tx["recusadas"],
            "taxa_retorno_ok": _tx["taxa_ok"],
        },
        "emissoes": _tx["ultimas"],
        "emissoes_por_dia": _tx["por_dia"],
        "por_mes": _serial(mes),
        "por_agregado": _serial(agreg),
        "frota": _serial(frota),
        "pendencia_cadastral": faltando,
        "prontidao_fila": _prontidao_fila(pj),
        "validacao": _validacao(pj),
        "certificados": _certificados(pj, pront),
        "classes": CLASSES,
        "avisos": _avisos(pj, tac, indef, faltando, _tx),
        "fonte": {
            "tabela": "conhecimento × veiculo (utilizacaoveiculo='AGR') × cadastro",
            "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    }





def _por_cstat(limite: int = 8) -> list[dict]:
    """Retornos da SEFAZ agrupados, do mais frequente para o menos.

    É o que responde "quais erros aconteceram" sem precisar ler linha a linha
    — a pergunta do acompanhamento diário, e a que a lista das últimas trinta
    transmissões não responde.
    """
    from api.contrapartida import emissao
    try:
        with emissao._conn() as c:
            linhas = [dict(r) for r in c.execute(
                "SELECT cstat, max(xmotivo) AS xmotivo, count(*) AS n,"
                "       max(quando) AS ultima"
                "  FROM emissao"
                " WHERE cstat IS NOT NULL AND cstat NOT LIKE 'CANC:%'"
                " GROUP BY cstat ORDER BY count(*) DESC")]
    except Exception as exc:  # noqa: BLE001
        log.warning("agrupamento por cStat indisponivel: %s", exc)
        return []
    return [{"cstat": str(r["cstat"]), "n": int(r["n"] or 0),
             "xmotivo": (r["xmotivo"] or "")[:120], "ultima": r["ultima"],
             "autorizado": str(r["cstat"]) == "100"}
            for r in linhas[:limite]]


def _transmissoes(limite: int = 30) -> dict:
    """As transmissoes ja feitas, para a tela mostrar o que saiu.

    So LEITURA do registro local - esta funcao nao emite nada. Homologacao e
    producao ficam separadas de proposito: documento de homologacao nao tem
    valor fiscal e nao pode entrar na mesma contagem do que valeu.
    """
    from api.contrapartida import emissao
    try:
        linhas = emissao.historico(limite)
    except Exception as exc:  # noqa: BLE001
        # Registro indisponivel nao pode derrubar a tela inteira: o resto da
        # conciliacao nao depende dele.
        log.warning("historico de transmissoes indisponivel: %s", exc)
        return {"producao": 0, "homologacao": 0, "autorizadas": 0,
                "recusadas": 0, "com_xml": 0, "autorizadas_sem_xml": 0,
                "por_dia": [], "taxa_ok": None, "ultimas": []}
    try:
        serie_dia = emissao.por_dia(30)
    except Exception as exc:  # noqa: BLE001
        log.warning("serie diaria de transmissoes indisponivel: %s", exc)
        serie_dia = []
    # Chaves com cancelamento REGISTRADO. O cancelamento entra como linha
    # propria, com cStat "CANC:<codigo>": 135 e registrado e 631 e duplicidade
    # de evento, que tambem significa que o evento existe.
    canceladas = {x.get("chave") for x in linhas
                  if str(x.get("cstat") or "").startswith("CANC:")
                  and str(x.get("cstat"))[5:] in ("135", "631")}
    # NOME DO EMITENTE. A numeracao do CT-e e POR EMITENTE, e cada agregado e
    # um emitente: o primeiro documento de cada um e "900/1", entao a serie e o
    # numero repetidos na lista sao o comportamento CERTO. Sem esta coluna a
    # tela mostrava tres linhas "900/1" seguidas e nao havia como distinguir
    # isso de uma duplicidade - que e o defeito mais caro deste modulo.
    #
    # Do cadastro LOCAL (titular do certificado), nao do AVA: e uma leitura que
    # ja esta em memoria, e a lista de transmissoes nao pode passar a depender
    # do ERP para desenhar.
    try:
        titulares = {c: (v.get("certificado") or {}).get("titular")
                     for c, v in cadastro.mapa().items()}
    except Exception as exc:  # noqa: BLE001
        log.warning("titulares dos certificados indisponiveis: %s", exc)
        titulares = {}
    com_xml = [x for x in linhas if x.get("tem_xml")]
    # Evento (cancelamento) nao e transmissao de documento: contar junto
    # inflaria a fila e estragaria a taxa de retorno.
    linhas = [x for x in linhas
              if not str(x.get("cstat") or "").startswith("CANC:")] + [
        x for x in linhas if str(x.get("cstat") or "").startswith("CANC:")]
    # AS CONTAGENS VEM DO REGISTRO INTEIRO, nao das `limite` ultimas linhas.
    # A tela contava em cima da propria pagina e mostrava o LIMITE como
    # universo: "5 de 30 autorizadas · 0 em producao", quando eram 30
    # autorizadas em 99 documentos e 2 delas em producao - que sumiam por
    # serem mais antigas que as trinta ultimas. `linhas` continua servindo
    # para a LISTA; para contar, nunca.
    try:
        tot = emissao.totais()
    except Exception as exc:  # noqa: BLE001
        log.warning("totais de transmissao indisponiveis: %s", exc)
        tot = {}
    docs = int(tot.get("documentos") or 0)
    ok_n = int(tot.get("autorizados") or 0)
    # A taxa mede o que o DOCUMENTO acertou. A recusa que so existe em
    # homologacao - o CT-e de origem que a base de teste nao conhece - nao
    # diz nada sobre o documento e sai do denominador, contada a parte. Deixa-
    # la dentro faria o periodo de teste medir o ambiente em vez do trabalho.
    esperadas = int(tot.get("esperadas_homologacao") or 0)
    base = max(docs - esperadas, 0)
    return {
        "producao": int(tot.get("producao") or 0),
        "producao_autorizadas": int(tot.get("producao_ok") or 0),
        "homologacao": int(tot.get("homologacao") or 0),
        "autorizadas": ok_n,
        "recusadas": docs - ok_n,
        "documentos": docs,
        "por_dia": serie_dia,
        # Taxa de retorno OK. `None` e nao 0 quando nao houve transmissao:
        # "0% de acerto" sem nenhuma tentativa e um numero que acusa alguem.
        "esperadas_homologacao": esperadas,
        "por_cstat": _por_cstat(),
        "avaliadas": base,
        "taxa_ok": (round(100.0 * ok_n / base, 1) if base else None),
        # Documento autorizado sem XML guardado nao se importa no ERP nem se
        # arquiva: a chave prova que existe, o arquivo e que serve.
        # Tambem sobre o registro inteiro: contados na pagina, os dois
        # numeros diziam quanto falta arquivar das ULTIMAS trinta linhas, que
        # nao e pergunta que alguem faca.
        "com_xml": int(tot.get("com_xml") or 0),
        "autorizadas_sem_xml": int(tot.get("autorizados_sem_xml") or 0),
        "ultimas": [{
            "quando": x.get("quando"), "quem": x.get("quem"),
            "tem_xml": bool(x.get("tem_xml")),
            "ambiente": "homologação" if str(x.get("ambiente")) == "2"
                        else "produção",
            "serie": x.get("serie"), "numero": x.get("numero"),
            "cnpj_emitente": x.get("cnpj_emitente"),
            "emitente": titulares.get(x.get("cnpj_emitente")),
            "chave": x.get("chave"), "cstat": x.get("cstat"),
            "xmotivo": x.get("xmotivo"), "protocolo": x.get("protocolo"),
            "autorizado": str(x.get("cstat")) == "100",
            "cancelado": x.get("chave") in canceladas,
            "evento": str(x.get("cstat") or "").startswith("CANC:"),
            "chave_origem": x.get("chave_origem"),
        } for x in linhas],
    }


def _br(v: float, casas: int = 2) -> str:
    """Numero em pt-BR. Existe para NAO precisar mexer na string ja montada:
    aplicar replace na frase inteira comeu as virgulas do texto do aviso."""
    inteiro, _, dec = f"{v:,.{casas}f}".partition(".")
    inteiro = inteiro.replace(",", ".")
    return f"{inteiro},{dec}" if dec else inteiro


# Faixas do semaforo do certificado, em dias ate vencer. Graduado e nao
# binario porque "vence em 2 dias" e "vence em 29" pedem acoes diferentes, e
# um chip igual para os dois nao prioriza nada (mesma licao da Manutencao
# Preventiva). Certificado A1 vale UM ANO: 60 dias e o momento de comprar.
CERT_CRITICO_DIAS = 15
CERT_ALERTA_DIAS = 30
CERT_ATENCAO_DIAS = 60


def _situacao_cert(dias: int | None, tipo: str | None) -> tuple[str, str]:
    """(situacao, texto) do certificado. Sem data nao e 'ok' — e desconhecido.

    Tratar validade ausente como boa notícia e o erro que faz a emissao parar
    em silencio: o certificado vence, ninguem e avisado, e a empresa descobre
    pelo agregado.
    """
    if tipo == "A3":
        return "impedido", "A3 (token físico) — não automatiza"
    if dias is None:
        return "desconhecido", "validade não informada"
    if dias < 0:
        return "vencido", f"vencido há {abs(dias)} dias"
    if dias <= CERT_CRITICO_DIAS:
        return "critico", f"vence em {dias} {'dia' if dias == 1 else 'dias'}"
    if dias <= CERT_ALERTA_DIAS:
        return "alerta", f"vence em {dias} dias"
    if dias <= CERT_ATENCAO_DIAS:
        return "atencao", f"vence em {dias} dias"
    return "ok", f"vence em {dias} dias"


def _certificados(pj: list[dict], pront: dict) -> dict:
    """Controle de vencimento, com o VOLUME que cada certificado sustenta.

    **NÃO segue o filtro de período**, e isso é deliberado: certificado vence
    no calendário, não na janela que a tela está mostrando. Antes a lista saía
    dos agregados COM CT-e no período e, como a tela abre no dia de hoje, um
    agregado que simplesmente não rodou hoje sumia do controle — inclusive o
    que vencia primeiro. O card leva badge dizendo isso.

    O volume, esse sim, é do período: é o que responde "quanto para se este
    certificado vencer". Zero ali significa "não rodou no recorte", não
    "não importa".
    """
    hoje = date.today()
    volume = {x["documento"]: x for x in pj}
    try:
        from api.contrapartida import emissao
        desligados = emissao.envios_desligados()
    except Exception as exc:  # noqa: BLE001
        log.warning("estado do envio por agregado indisponivel: %s", exc)
        desligados = {}

    # nome de quem tem certificado mas não apareceu no período
    faltam = [d for d, reg in pront.items()
              if (reg or {}).get("certificado") and d not in volume]
    nomes: dict[str, str] = {}
    if faltam:
        try:
            nomes = {r["documento"]: r["nome"]
                     for r in db.query(NOMES_SQL, {"docs": faltam})}
        except Exception as exc:  # noqa: BLE001
            # sem o nome ainda dá para agir pelo titular do certificado
            log.warning("nomes dos agregados com certificado: %s", exc)

    itens: list[dict] = []
    for documento, reg in (pront or {}).items():
        reg = reg or {}
        cert = reg.get("certificado") or {}
        if not cert:
            continue                      # sem certificado é pendência de outro card
        x = volume.get(documento) or {}
        dias = None
        if cert.get("valida_ate"):
            try:
                dias = (date.fromisoformat(cert["valida_ate"]) - hoje).days
            except ValueError:
                dias = None
        situacao, texto = _situacao_cert(dias, cert.get("tipo"))
        itens.append({
            "documento": documento,
            "nome": x.get("nome") or nomes.get(documento) or cert.get("titular"),
            "no_periodo": documento in volume,
            "titular": cert.get("titular"), "tipo": cert.get("tipo"),
            "valida_ate": cert.get("valida_ate"), "dias": dias,
            "situacao": situacao, "texto": texto,
            "tem_senha": bool(reg.get("tem_senha")),
            "envio": documento not in desligados,
            "envio_quem": (desligados.get(documento) or {}).get("quem"),
            "ctes": x.get("ctes") or 0,
            "valor": round(x.get("valor") or 0.0, 2),
        })
    # Ordem: o que precisa de acao primeiro. Dentro da mesma situacao, o de
    # maior volume - e o que para mais trabalho se vencer.
    ordem = {"vencido": 0, "critico": 1, "alerta": 2, "impedido": 3,
             "desconhecido": 4, "atencao": 5, "ok": 6}
    itens.sort(key=lambda i: (ordem.get(i["situacao"], 9), -i["ctes"]))

    def _conta(*situacoes):
        alvo = [i for i in itens if i["situacao"] in situacoes]
        return {"certificados": len(alvo),
                "ctes": sum(i["ctes"] for i in alvo)}

    faixas_contagem = [
        {"rotulo": "vencido", "chave": "vencido",
         "n": sum(1 for i in itens if i["situacao"] == "vencido")},
        {"rotulo": f"até {CERT_CRITICO_DIAS} dias", "chave": "critico",
         "n": sum(1 for i in itens if i["situacao"] == "critico")},
        {"rotulo": f"{CERT_CRITICO_DIAS + 1} a {CERT_ALERTA_DIAS} dias",
         "chave": "alerta",
         "n": sum(1 for i in itens if i["situacao"] == "alerta")},
        {"rotulo": f"{CERT_ALERTA_DIAS + 1} a {CERT_ATENCAO_DIAS} dias",
         "chave": "atencao",
         "n": sum(1 for i in itens if i["situacao"] == "atencao")},
        {"rotulo": f"mais de {CERT_ATENCAO_DIAS} dias", "chave": "ok",
         "n": sum(1 for i in itens if i["situacao"] == "ok")},
        # Estes dois NAO sao faixa de prazo, e por isso vao no fim e
        # separados: um nao tem data e o outro nao se resolve esperando.
        {"rotulo": "sem validade informada", "chave": "desconhecido",
         "n": sum(1 for i in itens if i["situacao"] == "desconhecido")},
        {"rotulo": "A3 — não automatiza", "chave": "impedido",
         "n": sum(1 for i in itens if i["situacao"] == "impedido")},
    ]
    return {
        "itens": itens,
        "total": len(itens),
        "faixas_contagem": faixas_contagem,
        "vencidos": _conta("vencido"),
        "criticos": _conta("critico"),
        "ate_30": _conta("vencido", "critico", "alerta"),
        "ate_60": _conta("vencido", "critico", "alerta", "atencao"),
        "sem_validade": _conta("desconhecido"),
        "faixas": {"critico": CERT_CRITICO_DIAS, "alerta": CERT_ALERTA_DIAS,
                   "atencao": CERT_ATENCAO_DIAS},
        # a tela avisa: este card ignora o filtro de período de propósito
        "ignora_periodo": True,
    }


def _prontidao_fila(pj: list[dict]) -> dict:
    """Quem da fila PODE emitir hoje, e o que trava quem nao pode.

    Substituiu o bloco de passivo acumulado. O passivo olhava para tras e nao
    virava trabalho - CT-e nao se emite retroativo. Este olha para a frente e
    responde a pergunta da tela: de tudo que entrou, quanto da para emitir
    agora, e o que falta no resto.

    A separacao dos travados por INDICADOR DE INSCRICAO ESTADUAL importa
    porque os dois grupos tem encaminhamentos diferentes:

      - marcado como CONTRIBUINTE e com inscricao "ISENTO" e CONTRADICAO de
        cadastro: se e contribuinte, tem inscricao. Da para corrigir.
      - marcado como NAO CONTRIBUINTE e coerente: provavelmente nao emite
        CT-e mesmo, e sai da fila em vez de virar pendencia eterna.
    """
    def _bloco(itens):
        return {"agregados": len(itens),
                "ctes": sum(x.get("ctes") or 0 for x in itens),
                "valor": round(sum(x.get("valor") or 0.0 for x in itens), 2)}

    # DOIS PORTOES DIFERENTES, e confundi-los faz a tela mentir:
    #   cadastro  = tem os campos que o documento exige (IE, RNTRC, municipio)
    #   autorizado = TEM CERTIFICADO e autorizacao vigente para assinar
    # Um agregado pode estar com o cadastro impecavel e nao emitir nada por
    # falta de certificado - foi o caso de 28 dos 30 no primeiro levantamento.
    autorizados = [x for x in pj if (x.get("prontidao") or {}).get("pronto")]
    cadastro_ok = [x for x in pj
                   if _ie_utilizavel(x.get("ie")) and not x.get("falta")]
    sem_certificado = [x for x in cadastro_ok if x not in autorizados]
    sem_ie = [x for x in pj if not _ie_utilizavel(x.get("ie"))]
    # 1 = contribuinte de ICMS; 9 = nao contribuinte (dominio do ERP)
    contradicao = [x for x in sem_ie if str(x.get("ind_ie") or "") != "9"]
    nao_contrib = [x for x in sem_ie if str(x.get("ind_ie") or "") == "9"]
    return {
        "autorizados": _bloco(autorizados),
        "cadastro_ok_sem_certificado": _bloco(sem_certificado),
        "sem_ie_contribuinte": _bloco(contradicao),
        "sem_ie_nao_contribuinte": _bloco(nao_contrib),
        "total": _bloco(pj),
    }


def _validacao(pj: list[dict]) -> dict:
    """Confere, agregado a agregado, o que a emissão vai exigir — ANTES dela.

    A tela já dizia QUANTOS estavam travados; o que faltava era o item a item
    com o encaminhamento de cada um. Sem isso, o defeito só aparece na
    transmissão, um documento por vez: a rejeição 229 ("IE do emitente não
    informada") foi descoberta assim, com o disjuntor derrubando o lote.

    Cada achado carrega a AÇÃO, não só o rótulo, porque os motivos pedem
    coisas diferentes de pessoas diferentes: cadastro se corrige no ERP,
    certificado se pede ao agregado, e "não contribuinte" não se corrige —
    sai da fila por natureza do documento.

    O código da SEFAZ só aparece onde foi MEDIDO (229). Inventar número de
    rejeição para os outros campos daria autoridade a um palpite.
    """
    achados: list[dict] = []

    def _add(x, categoria, defeito, acao, rejeicao=None, grave=True):
        # CATEGORIA e o que torna a lista utilizavel. Sem ela, 39 dos 46
        # agregados aparecem por "sem certificado" - que e verdade, e afoga os
        # defeitos de CADASTRO, que sao os que se resolvem digitando no ERP.
        # Sao filas de pessoas diferentes: cadastro e trabalho interno,
        # certificado depende do agregado entregar o arquivo.
        achados.append({
            "documento": x.get("documento"), "nome": x.get("nome"),
            "uf": x.get("uf"), "ctes": x.get("ctes") or 0,
            "valor": round(x.get("valor") or 0.0, 2),
            "categoria": categoria,
            "defeito": defeito, "acao": acao, "rejeicao": rejeicao,
            "grave": grave,
        })

    for x in pj:
        ind = str(x.get("ind_ie") or "")
        ie = (x.get("ie") or "").strip()
        pront = x.get("prontidao") or {}

        if not _ie_utilizavel(ie):
            if ind == "9":
                # Coerente: nao contribuinte de ICMS nao emite CT-e. Nao e
                # pendencia a resolver - e um agregado que sai da fila.
                _add(x, "natureza", "não contribuinte de ICMS" + (f" (IE “{ie}”)" if ie else ""),
                     "Confirmar com a contabilidade que ele não emite CT-e e "
                     "tirar da fila — não há o que corrigir no cadastro.",
                     grave=False)
            else:
                _add(x, "cadastro", f"marcado contribuinte, inscrição “{ie or 'em branco'}”",
                     "Consultar no SINTEGRA. Tendo inscrição, corrigir no ERP; "
                     "sendo isento mesmo, mudar o indicador para não "
                     "contribuinte — hoje o cadastro se contradiz.",
                     rejeicao="229 · IE do emitente não informada")
        elif ind == "9":
            # A contradicao no sentido inverso, que passava despercebida: tem
            # inscricao valida e esta marcado como nao contribuinte. Nao trava
            # a emissao, mas um dos dois campos esta errado.
            _add(x, "cadastro", f"inscrição {ie} preenchida, mas marcado não contribuinte",
                 "Um dos dois campos está errado. Não impede a emissão hoje, "
                 "mas decide se ele entra ou não na fila.", grave=False)

        # UMA LINHA POR AGREGADO E POR AÇÃO, nunca por campo. Cada falta virava
        # uma linha própria e o mesmo agregado aparecia duas e três vezes:
        # "sem procuração" e "sem certificado" são o mesmo item de trabalho —
        # 34 dos 38 agregados apareciam repetidos, e a lista deixava de ser
        # lista de trabalho para virar lista de campos.
        faltam = [r for r, ok in (("razão social", bool(x.get("nome"))),
                                  ("RNTRC", bool(x.get("rntrc"))),
                                  ("município/UF", bool(x.get("cidade"))))
                  if not ok]
        if faltam:
            _add(x, "cadastro", "sem " + ", ".join(faltam),
                 f"Preencher no cadastro do ERP: {', '.join(faltam)}. São "
                 "campos obrigatórios no CT-e — cada um vira rejeição "
                 "documento a documento.")

        fal = list(pront.get("faltas") or []) if not pront.get("pronto") else []
        if fal:
            # A ação sai da NATUREZA da falta, não de um texto único: vencido
            # se renova, ausente se coleta, senha se cadastra. Um texto só
            # para os três mandaria pedir ao agregado o que já está com a
            # gente.
            junto = " · ".join(fal)
            if any("vencid" in f.lower() for f in fal):
                acao = ("Renovar o certificado A1 com o agregado. Vencido, a "
                        "emissão dele para sozinha e sem aviso.")
            elif any("senha" in f.lower() for f in fal):
                acao = ("Cadastrar a senha do certificado no cofre — o arquivo "
                        "já está aqui, falta a senha para conseguir assinar.")
            else:
                acao = ("Certificado A1 e procuração são do agregado: sem eles "
                        "a Sulista não pode assinar em nome dele.")
            _add(x, "certificado", junto, acao)

        alertas = list(pront.get("alertas") or [])
        if alertas:
            _add(x, "certificado", " · ".join(alertas),
                 "Renovar antes do vencimento: vencido, a emissão desse "
                 "agregado para sem aviso nenhum.", grave=False)

    com_defeito = {a["documento"] for a in achados if a["grave"]}
    por_cat: dict[str, int] = {}
    for a in achados:
        por_cat[a["categoria"]] = por_cat.get(a["categoria"], 0) + 1
    return {
        "achados": sorted(achados,
                          key=lambda a: (not a["grave"], -(a["ctes"] or 0))),
        "por_categoria": por_cat,
        "agregados": len(pj),
        "aprovados": len([x for x in pj
                          if x.get("documento") not in com_defeito]),
        "com_impedimento": len(com_defeito),
        # Quantos agregados PASSARIAM se so o certificado faltasse - e a
        # medida do trabalho interno, separada do que depende de terceiro.
        "cadastro_ok": len([x for x in pj if x.get("documento") not in {
            a["documento"] for a in achados
            if a["grave"] and a["categoria"] == "cadastro"}]),
    }


def _avisos(pj, tac, indef, faltando, tx=None) -> list[str]:

    av: list[str] = []
    # ESTE AVISO ERA UM TEXTO FIXO dizendo "nenhuma contrapartida emitida ate
    # hoje". Era verdade quando foi escrito e continuou na tela depois das
    # primeiras emissoes, inclusive a de PRODUCAO - o cartao "Ler com atencao"
    # ficou afirmando o contrario do que os cartoes ao lado mostravam. Aviso e
    # leitura do dado, nao anotacao: se ele nao sai de uma contagem, envelhece
    # calado e no dia em que erra ninguem desconfia dos outros numeros.
    tx = tx or {}
    prod = int(tx.get("producao") or 0)
    homo = int(tx.get("homologacao") or 0)
    if not (prod or homo):
        av.append(
            "Nenhuma contrapartida emitida até hoje: esta tela dimensiona a "
            "fila, não mede cobertura. O número de emitidas é zero por "
            "confirmação da própria operação, não por falta de dado.")
    elif not prod:
        av.append(
            f"{homo} documento(s) transmitido(s), todos em HOMOLOGAÇÃO — que "
            "não tem valor fiscal e não substitui a obrigação do agregado. "
            "Para a contabilidade a fila continua inteira: o que foi emitido "
            "até agora é teste do caminho, não contrapartida.")
    else:
        # AUTORIZADO x TRANSMITIDO. Este aviso dizia "N autorizados em
        # PRODUCAO" usando o total de TENTATIVAS: com 4 transmissoes e 2
        # autorizacoes, ele afirmava 4 enquanto o cartao logo acima dizia
        # "producao 2 de 4". Dois numeros diferentes para a mesma coisa na
        # mesma tela, e o texto era o errado.
        pok = int((tx or {}).get("producao_autorizadas") or 0)
        av.append(
            f"{pok} documento(s) AUTORIZADO(S) em produção, de {prod} "
            f"transmitido(s); e {homo} transmissões em homologação. Só os "
            "autorizados em produção existem para o fisco — os de homologação "
            "estão na tela para conferir o caminho e não entram em conta "
            "fiscal nenhuma.")

    # QUARENTENA: documento que a SEFAZ ja recusou tantas vezes que a rotina
    # parou de reapresentar. Sair da fila em SILENCIO seria pior que o
    # looping que ela resolve - o CT-e de origem continua sem contrapartida e
    # ninguem ficaria sabendo.
    try:
        from api.contrapartida import lote as _lote
        presos = _lote._quarentena(_lote.emissao.ambiente_ativo())
    except Exception as exc:  # noqa: BLE001
        log.warning("quarentena indisponivel: %s", exc)
        presos = {}
    if presos:
        # Cortar em N caracteres partia a palavra ao meio ("...inexistente na
        # bas"), que faz o aviso parecer truncado por defeito. Corta na
        # PONTUACAO e, nao havendo, no ultimo espaco.
        def _curto(t, n=90):
            t = " ".join((t or "").split())
            if len(t) <= n:
                return t
            corte = t[:n]
            for sep in (". ", " ["):
                if sep in corte:
                    return corte[:corte.rindex(sep)].rstrip(" .")
            return corte[:corte.rfind(" ")].rstrip(" ,.") + "…"

        motivos = sorted({f"{v.get('cstat')} · {_curto(v.get('xmotivo'))}"
                          for v in presos.values()})
        av.append(
            f"{len(presos)} CT-e sairam da fila por recusa repetida da SEFAZ "
            f"(a partir de {_lote.MAX_TENTATIVAS_MESMA_RECUSA} tentativas com "
            f"o mesmo retorno). Rejeicao nao muda sozinha: insistir gastava "
            f"uma rodada inteira e o disjuntor derrubava o lote antes de "
            f"chegar em quem estava certo. Motivos: " + " | ".join(motivos))

    if tac:

        av.append(f"{len(tac)} dos {len(pj) + len(tac) + len(indef)} agregados "
                  f"do período são pessoa física. " + NOTA_TAC)

    if indef:
        av.append(
            f"{len(indef)} agregados com documento de proprietário fora do "
            "padrão de CNPJ ou CPF: não dá para dizer se emitem CT-e. "
            "Conferir o cadastro do veículo antes de incluí-los em qualquer fila.")
    sem_ie = [x for x in pj if not _ie_utilizavel(x["ie"])]
    if sem_ie:
        av.append(
            f"{len(sem_ie)} de {len(pj)} agregados PJ estão sem inscrição "
            "estadual utilizável no cadastro — a maioria com o texto "
            "“ISENTO”. CT-e é documento de ICMS: transportadora emitente "
            "precisa ser inscrita. Ou o cadastro do ERP está desatualizado, ou "
            "esses agregados não emitem CT-e — e nesse caso a fila real é de "
            f"{len(pj) - len(sem_ie)} agregados, não {len(pj)}. Confira alguns "
            "no SINTEGRA antes de tratar como pendência de sistema.")

    if faltando:

        quais = ", ".join(f"{x['nome'] or x['documento']} ({', '.join(x['falta'])})"
                          for x in faltando[:4])
        av.append(
            f"{len(faltando)} agregados PJ com cadastro incompleto para emitir: "
            f"{quais}{'...' if len(faltando) > 4 else ''}. Campo faltando vira "
            "rejeição documento a documento na transmissão.")

    # CT-e de centavos quase certamente e documento de AJUSTE (anulacao,
    # complementar), nao prestacao. Se for, nao deveria puxar contrapartida -
    # mas isso e definicao fiscal, nao suposicao minha: a tela conta e
    # pergunta, em vez de filtrar por conta propria e esconder o caso.
    centavos = [x for x in pj if (x.get("valor") or 0) < 1.0]
    if centavos:
        av.append(
            f"{len(centavos)} agregado(s) PJ com CT-e somando menos de R$ 1,00 no "
            "período (há caso de 4 CT-e totalizando R$ 0,04). Documento de "
            "valor simbólico costuma ser anulação ou complementar, não "
            "prestação — se for, não deveria entrar na fila de contrapartida. "
            "Confirmar com a contabilidade antes de emitir para eles.")
    naopronto = [x for x in pj if not (x.get("prontidao") or {}).get("pronto")]
    if naopronto:
        av.append(
            f"{len(naopronto)} dos {len(pj)} agregados PJ ainda não estão "
            "autorizados a emitir: falta procuração vigente, certificado A1 "
            "válido ou a senha dele no cofre. Enquanto isso, a fila é "
            "diagnóstico — nenhum documento pode ser emitido.")
    return av



DIAS_VARREDURA_PADRAO = 90


def validacao_completa(dias: int = DIAS_VARREDURA_PADRAO) -> dict:
    """Valida o cadastro de TODOS os agregados, ignorando o filtro da tela.

    A tela abre no dia de hoje, e o validador dentro dela obedecia esse
    recorte: quem não rodou hoje não era validado. Só que defeito de cadastro
    não pertence a uma janela de datas — é a mesma lição do cartão de
    vencimento de certificado, que ignora o período de propósito. Com o filtro
    do dia via-se 18 agregados; a varredura completa encontra 46, e as duas
    contradições mais caras (188 e 190 CT-e) estavam fora do recorte.

    A janela de 90 dias não é filtro de validação: é a definição de "agregado
    ATIVO". Validar quem não roda há um ano encheria a lista de trabalho que
    ninguém vai fazer.
    """
    try:
        d = max(1, min(int(dias), 730))
    except (TypeError, ValueError):
        d = DIAS_VARREDURA_PADRAO
    hoje = date.today()
    par = {"de": (hoje - timedelta(days=d)).isoformat(),
           "ate": (hoje + timedelta(days=1)).isoformat()}
    agreg = db.query(POR_AGREGADO_SQL, par)
    try:
        pront = cadastro.mapa()
    except Exception as exc:  # noqa: BLE001
        log.warning("cadastro de procuracao/certificado indisponivel: %s", exc)
        pront = {}
    for x in agreg:
        p = pront.get(x["documento"]) or {}
        x["prontidao"] = p.get("prontidao") or {
            "pronto": False, "faltas": ["sem procuração cadastrada",
                                        "sem certificado cadastrado"],
            "alertas": []}
    pj = [x for x in agreg if x["classe"] == "pj"]
    out = _validacao(pj)
    out["janela_dias"] = d
    out["escopo"] = (f"todos os agregados PJ com CT-e nos últimos {d} dias — "
                     "não segue o filtro de período da tela")
    out["gerado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return out
