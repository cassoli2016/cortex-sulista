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



E nao trata o passivo historico como fila de trabalho: CT-e NAO se emite

retroativo (a SEFAZ recusa data de emissao fora da janela). O acumulado sai

num bloco separado, rotulado como numero para decisao juridica.

"""

from __future__ import annotations



import logging

from datetime import date, datetime, timedelta



from api import db

from api.contrapartida import cadastro
from api.contrapartida.sql import (FROTA_AGR_SQL, PASSIVO_SQL,

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

def _ie_utilizavel(ie: str | None) -> bool:
    """IE que serve para emitir tem DIGITO. "ISENTO", "-" ou vazio, nao.

    Nao afirmamos que quem esta como ISENTO fica de fora - pode ser cadastro
    velho no ERP. Mas nao da para tratar como PRONTO quem talvez nem possa
    emitir: o erro apareceria na transmissao, documento a documento.
    """
    return bool("".join(c for c in (ie or "") if c.isdigit()))


NOTA_TAC = ("Transportador Autônomo de Cargas não emite CT-e — a documentação "

            "dele é CIOT (Lei 11.442) e RPA. Estes CT-e não entram na fila de "
            "contrapartida por natureza do documento, não por falta de "
            "certificado.")





def _janela(de: str | None, ate: str | None) -> tuple[str, str]:
    """Sem filtro, a tela abre no DIA DE HOJE.

    A fila de contrapartida e trabalho DIARIO: o CT-e sai hoje e o documento do
    agregado tem de sair junto. Abrir em seis meses fazia a tela responder
    "quanto acumulou" quando a pergunta do dia e "o que preciso emitir agora" -
    e o acumulado continua a um clique, alem de estar sempre no bloco de
    passivo, que ignora este filtro.
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
    passivo = db.query(PASSIVO_SQL, {"de": "2022-01-01", "ate": d_ate})



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
    # KPIs do recorte - o passivo acumulado continua do periodo inteiro.
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
            "emitidas_recusadas": _tx["recusadas"],
        },
        "emissoes": _tx["ultimas"],
        "por_mes": _serial(mes),
        "por_agregado": _serial(agreg),
        "frota": _serial(frota),
        "passivo": _serial(passivo),
        "pendencia_cadastral": faltando,
        "classes": CLASSES,
        "avisos": _avisos(pj, tac, indef, faltando, passivo),
        "fonte": {
            "tabela": "conhecimento × veiculo (utilizacaoveiculo='AGR') × cadastro",
            "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    }





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
                "recusadas": 0, "ultimas": []}
    prod = [x for x in linhas if str(x.get("ambiente")) == "1"]
    homo = [x for x in linhas if str(x.get("ambiente")) == "2"]
    ok = [x for x in linhas if str(x.get("cstat")) == "100"]
    return {
        "producao": len(prod),
        "homologacao": len(homo),
        "autorizadas": len(ok),
        "recusadas": len(linhas) - len(ok),
        "ultimas": [{
            "quando": x.get("quando"), "quem": x.get("quem"),
            "ambiente": "homologação" if str(x.get("ambiente")) == "2"
                        else "produção",
            "serie": x.get("serie"), "numero": x.get("numero"),
            "chave": x.get("chave"), "cstat": x.get("cstat"),
            "xmotivo": x.get("xmotivo"), "protocolo": x.get("protocolo"),
            "autorizado": str(x.get("cstat")) == "100",
            "chave_origem": x.get("chave_origem"),
        } for x in linhas],
    }


def _br(v: float, casas: int = 2) -> str:
    """Numero em pt-BR. Existe para NAO precisar mexer na string ja montada:
    aplicar replace na frase inteira comeu as virgulas do texto do aviso."""
    inteiro, _, dec = f"{v:,.{casas}f}".partition(".")
    inteiro = inteiro.replace(",", ".")
    return f"{inteiro},{dec}" if dec else inteiro


def _avisos(pj, tac, indef, faltando, passivo) -> list[str]:

    av: list[str] = []
    av.append(

        "Nenhuma contrapartida emitida até hoje: esta tela dimensiona a fila, "
        "não mede cobertura. O número de emitidas é zero por confirmação da "
        "própria operação, não por falta de dado.")
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
    velho = [x for x in passivo if x["classe"] == "pj"

             and x["ano"] < str(date.today().year)]
    if velho:

        n = sum(x["ctes"] for x in velho)
        v = sum(x["valor"] for x in velho)
        # formata SO o numero. Aplicar replace(",", ".") na frase inteira
        # comeu as virgulas do texto - a mesma armadilha da substituicao em
        # massa que o CLAUDE.md descreve, em miniatura.
        av.append(
            f"Passivo de anos anteriores: {_br(n, 0)} CT-e de agregado PJ, "
            f"R$ {_br(v, 0)} de prestação. CT-e NÃO se emite retroativo (a "
            "SEFAZ recusa data de emissão fora da janela), então isto não é "
            "fila de trabalho — é número para a decisão da contabilidade e do "
            "jurídico.")
    return av

