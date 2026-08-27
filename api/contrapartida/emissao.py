# api/contrapartida/emissao.py
"""Assinatura e transmissão do CT-e de contrapartida. **Só homologação.**

POR QUE ISTO NÃO MORA EM `documento.py`
=======================================
Montar o XML e assinar como terceiro são atos de natureza diferente. O
primeiro é reversível e não vale nada; o segundo é a empresa praticando um ato
em nome de outra pessoa jurídica. `documento.py` tem guarda de árvore sintática
que o proíbe de alcançar certificado, assinatura ou transmissão — e essa guarda
só continua significando alguma coisa se este módulo for separado.

OS DOIS AMBIENTES, E POR QUE UM TEM TRANCA
------------------------------------------
**Homologação** é o ambiente de teste da SEFAZ: o documento autorizado lá não
tem valor fiscal, não é escriturado e não gera obrigação. É o padrão de tudo
neste módulo.

**Produção** emite documento de verdade, em nome de outra pessoa jurídica. Um
CT-e autorizado com enquadramento errado **não se apaga**: cancela-se, dentro
de prazo, com justificativa, e repercute na escrituração dos dois lados. Por
isso produção não é só um parâmetro diferente — exige uma LIBERAÇÃO explícita,
que nasce desligada, pede uma frase de confirmação e fica registrada com autor
e data.

A frase existe porque `--producao` numa linha de comando é fácil demais de
digitar por engano, e o engano aqui custa cancelamento e retificação.

AS TRÊS GUARDAS ANTES DE ASSINAR
--------------------------------
Nenhuma é decorativa — cada uma corresponde a uma falha que já aconteceu ou
que só apareceria documento a documento na transmissão:

  1. **prontidão** (`cadastro.prontidao`): autorização vigente, certificado A1
     válido, arquivo presente e senha no cofre. Assinar por quem não autorizou
     é o único erro deste módulo que não tem conserto técnico.
  2. **titularidade**: o CNPJ do emitente do XML tem de ser o dono do
     certificado. Certificado trocado assina o documento errado e isso não
     aparece em conferência nenhuma depois.
  3. **numeração**: número repetido é rejeição 539 (duplicidade). O próximo
     número sai do registro local, não de um contador na cabeça de quem chama.

TUDO QUE SAI DAQUI FICA REGISTRADO
----------------------------------
Cada transmissão grava linha em `emissao` (chave, número, retorno da SEFAZ) e
na `auditoria` do módulo. Assinar em nome de terceiro tem de ser respondível
meses depois, inclusive contra o próprio CÓRTEX.
"""
from __future__ import annotations

import logging
import pathlib
from datetime import date, datetime

from api.contrapartida import cadastro, documento, sefaz
from api.contrapartida.cadastro import DIR_CERT, ler_senha, mapa

log = logging.getLogger("cortex.contrapartida.emissao")

HOMOLOGACAO = sefaz.HOMOLOGACAO
PRODUCAO = "1"
AMBIENTES = {HOMOLOGACAO: "homologação", PRODUCAO: "produção"}

# Quem quiser ligar produção digita isto. Não é senha — é atrito deliberado,
# para que ninguém libere emissão fiscal por autocompletar de terminal.
CONFIRMACAO_PRODUCAO = "EMITIR EM PRODUCAO"

# SÉRIE 900, exclusiva destes documentos (aprovada pela área em 26/08/2026,
# em caráter provisório para homologação).
#
# Por que uma série alta e reservada, e não a 1: se o agregado já emite CT-e
# por conta própria — pelo contador dele, por outro sistema —, estará numa
# série baixa. Número repetido dentro da mesma série é rejeitado pela SEFAZ,
# documento a documento, no meio de um lote de milhares; e não há como
# levantar, agregado a agregado, o que cada um já gastou. A série reservada
# afasta a colisão sem depender desse levantamento.
#
# De quebra torna a origem auditável: pela série se sabe, sem consultar
# ninguém, que o documento saiu pela Sulista em nome do agregado.
SERIE_PADRAO = 900

# Quem aparece na trilha quando a emissao NAO parte de uma pessoa logada -
# rotina agendada, script de operacao. Identidade do sistema, e-mail que
# ninguem le: a trilha tem de dizer "foi o CORTEX", nao o e-mail pessoal de
# quem por acaso rodou o comando naquele dia.
#
# Emissao disparada pela TELA continua exigindo o usuario logado: `transmitir`
# nao tem valor padrao para `quem`, de proposito.
IDENTIDADE_SISTEMA = "noreply@sulista.com.br"

_DDL_EMISSAO = """
CREATE TABLE IF NOT EXISTS emissao (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  quando        TEXT NOT NULL,
  quem          TEXT NOT NULL,
  ambiente      TEXT NOT NULL,
  cnpj_emitente TEXT NOT NULL,
  serie         INTEGER NOT NULL,
  numero        INTEGER NOT NULL,
  chave         TEXT,
  chave_origem  TEXT NOT NULL,
  cstat         TEXT,
  xmotivo       TEXT,
  protocolo     TEXT
);
"""

# O XML ASSINADO fica guardado. Sem ele, um documento autorizado nao se
# reconstroi: a chave e o protocolo provam que existe, mas quem precisa
# IMPORTAR o documento (o ERP, a contabilidade, uma fiscalizacao) precisa do
# arquivo. Coluna acrescentada depois, entao entra por migracao.
_MIGRACOES = ("ALTER TABLE emissao ADD COLUMN xml TEXT",
              "ALTER TABLE emissao ADD COLUMN xml_prot TEXT")

# Chaves de configuração do módulo (liberação de produção, automação do lote).
# Mesma tabela para os dois: são interruptores da mesma natureza — ligam algo
# que emite documento sem alguém confirmando na hora.
_DDL_CONFIG = """
CREATE TABLE IF NOT EXISTS lote_config (
  chave      TEXT PRIMARY KEY,
  valor      TEXT NOT NULL,
  quem       TEXT NOT NULL,
  quando     TEXT NOT NULL
);
"""

CHAVE_PRODUCAO = "producao_liberada"
CHAVE_AMBIENTE = "ambiente_ativo"

# Interruptor POR AGREGADO. Chave = "envio:<cnpj>".
#
# Ausencia de registro significa HABILITADO, ao contrario dos outros
# interruptores deste modulo. A razao e que aqui o padrao seguro e o
# comportamento de HOJE: quem tem certificado e autorizacao ja entrava na
# fila. Um padrao desligado esvaziaria a fila em silencio - e uma fila vazia
# parece trabalho concluido.
PREFIXO_ENVIO = "envio:"


def _conn():
    c = cadastro._conn()          # mesmo banco, mesma disciplina (WAL, curta)
    c.executescript(_DDL_EMISSAO)
    for ddl in _MIGRACOES:
        try:
            c.execute(ddl)
        except Exception:      # noqa: BLE001 - coluna ja existe
            pass
    return c


def _conn_config():
    c = _conn()
    c.executescript(_DDL_CONFIG)
    return c


def config_lida(chave: str) -> dict | None:
    with _conn_config() as c:
        r = c.execute("SELECT valor, quem, quando FROM lote_config WHERE chave=?",
                      (chave,)).fetchone()
    return dict(r) if r else None


def config_grava(chave: str, ativa: bool, quem: str, acao: str) -> dict:
    if not quem:
        raise ValueError("Informe quem está mudando esta configuração.")
    agora = datetime.now().isoformat(timespec="seconds")
    with _conn_config() as c:
        c.execute(
            "INSERT INTO lote_config(chave, valor, quem, quando)"
            " VALUES(?,?,?,?) ON CONFLICT(chave) DO UPDATE SET"
            " valor=excluded.valor, quem=excluded.quem, quando=excluded.quando",
            (chave, "1" if ativa else "0", quem, agora))
        cadastro._audita(c, quem, acao, "-", "ligada" if ativa else "desligada")
    log.warning("%s %s por %s", acao, "LIGADA" if ativa else "desligada", quem)
    return {"ativa": ativa, "quem": quem, "quando": agora}


def ambiente_ativo() -> str:
    """Ambiente que a operação está usando. PADRÃO: homologação.

    Ausência de registro é HOMOLOGAÇÃO — nunca produção. Banco novo, backup
    restaurado ou configuração corrompida caem no ambiente que não emite
    documento de verdade.
    """
    r = config_lida(CHAVE_AMBIENTE)
    return PRODUCAO if (r and r["valor"] == PRODUCAO) else HOMOLOGACAO


def estado_ambiente() -> dict:
    """O ambiente e quem o colocou assim — para a tela mostrar responsável."""
    r = config_lida(CHAVE_AMBIENTE) or {}
    amb = ambiente_ativo()
    return {"ambiente": amb, "nome": AMBIENTES[amb],
            "producao": amb == PRODUCAO,
            "quem": r.get("quem"), "quando": r.get("quando"),
            "confirmacao_exigida": CONFIRMACAO_PRODUCAO}


def definir_ambiente(ambiente: str, quem: str, confirmacao: str = "") -> dict:
    """Troca o ambiente da operação.

    Ir para PRODUÇÃO exige a frase; VOLTAR para homologação não exige nada —
    voltar é sempre seguro, e não pode depender de lembrar de uma frase no
    meio de um problema.
    """
    if ambiente not in AMBIENTES:
        raise ValueError(f"Ambiente {ambiente!r} não existe.")
    if ambiente == PRODUCAO and confirmacao.strip().upper() != CONFIRMACAO_PRODUCAO:
        raise PermissionError(
            f"Para emitir em PRODUÇÃO, confirme com a frase "
            f"'{CONFIRMACAO_PRODUCAO}'. Em produção o documento é real e "
            f"emitido em nome de outra empresa: se sair errado, não se apaga "
            f"— cancela-se, dentro de prazo, com justificativa, e repercute na "
            f"escrituração dos dois lados.")
    if not quem:
        raise ValueError("Informe quem está mudando o ambiente.")
    agora = datetime.now().isoformat(timespec="seconds")
    with _conn_config() as c:
        c.execute(
            "INSERT INTO lote_config(chave, valor, quem, quando)"
            " VALUES(?,?,?,?) ON CONFLICT(chave) DO UPDATE SET"
            " valor=excluded.valor, quem=excluded.quem, quando=excluded.quando",
            (CHAVE_AMBIENTE, ambiente, quem, agora))
        cadastro._audita(c, quem, "ambiente_emissao", "-", AMBIENTES[ambiente])
    log.warning("ambiente de emissao -> %s por %s", AMBIENTES[ambiente], quem)
    return estado_ambiente()


def producao_liberada() -> bool:
    """Produção está destravada? É o mesmo que o ambiente ativo ser produção.

    Mantido como nome próprio porque é assim que a guarda pergunta, e porque
    deixa explícito no ponto de uso que a resposta padrão é NÃO.
    """
    return ambiente_ativo() == PRODUCAO


def liberar_producao(ativa: bool, quem: str, confirmacao: str = "") -> dict:
    """Atalho antigo, mantido para os scripts: liga/desliga produção."""
    r = definir_ambiente(PRODUCAO if ativa else HOMOLOGACAO, quem, confirmacao)
    return {"ativa": r["producao"], "quem": r["quem"], "quando": r["quando"]}


def envio_habilitado(cnpj: str) -> bool:
    """Este agregado entra na fila de emissão? Sem registro, SIM."""
    r = config_lida(f"{PREFIXO_ENVIO}{cnpj}")
    return not r or r["valor"] != "0"


def definir_envio(cnpj: str, ativo: bool, quem: str) -> dict:
    """Liga ou desliga a emissão para UM agregado. Entra na auditoria.

    Serve para testar com um de cada vez e para tirar da fila quem está
    rejeitando sempre — sem mexer no certificado nem na autorização, que são
    registros de outra natureza e não deveriam ser apagados por conveniência
    operacional.
    """
    if not cnpj:
        raise ValueError("Informe o agregado.")
    r = config_grava(f"{PREFIXO_ENVIO}{cnpj}", ativo, quem, "envio_agregado")
    return {"cnpj": cnpj, "habilitado": ativo,
            "quem": r["quem"], "quando": r["quando"]}


def envios_desligados() -> dict[str, dict]:
    """{cnpj: {quem, quando}} dos que estão fora da fila por decisão."""
    with _conn_config() as c:
        linhas = [dict(r) for r in c.execute(
            "SELECT chave, valor, quem, quando FROM lote_config"
            " WHERE chave LIKE ? AND valor='0'", (f"{PREFIXO_ENVIO}%",))]
    return {r["chave"][len(PREFIXO_ENVIO):]: {"quem": r["quem"],
                                              "quando": r["quando"]}
            for r in linhas}


def proximo_numero(cnpj: str, serie: int, ambiente: str) -> int:
    """Próximo número da série, por emitente e por AMBIENTE.

    Homologação e produção têm numerações independentes; misturar as duas faria
    o primeiro CT-e de produção nascer com o número gasto num teste.
    """
    with _conn() as c:
        r = c.execute(
            "SELECT max(numero) AS n FROM emissao WHERE cnpj_emitente=?"
            " AND serie=? AND ambiente=?", (cnpj, serie, ambiente)).fetchone()
    return int((r["n"] or 0)) + 1


def _guardas(cnpj: str, d: dict, ambiente: str) -> None:
    if ambiente not in AMBIENTES:
        raise ValueError(
            f"Ambiente {ambiente!r} não existe. Use "
            f"'{HOMOLOGACAO}' (homologação) ou '{PRODUCAO}' (produção).")
    if ambiente == PRODUCAO and not producao_liberada():
        raise PermissionError(
            "A emissão em PRODUÇÃO está travada. Ela nasce assim e não "
            "destrava sozinha: alguém precisa liberar, com confirmação, e "
            "essa liberação fica registrada com autor e data. Homologação "
            "continua disponível para testar o documento inteiro.")

    reg = cadastro.mapa().get(cnpj) or {}
    pront = reg.get("prontidao") or {}
    if not pront.get("pronto"):
        faltas = "; ".join(pront.get("faltas") or ["agregado não cadastrado"])
        raise PermissionError(f"{cnpj} não está pronto para emitir: {faltas}")

    if d["emit_cnpj"] != cnpj:
        raise ValueError(
            f"O XML tem emitente {d['emit_cnpj']} e o certificado é de {cnpj}. "
            f"Certificado trocado assina o documento errado.")

    venc = (reg.get("certificado") or {}).get("valida_ate")
    if venc and date.fromisoformat(venc) < date.today():
        raise PermissionError(f"Certificado de {cnpj} venceu em {venc}.")


def _registra(quem: str, ambiente: str, cnpj: str, serie: int, numero: int,
              chave: str, chave_origem: str, resp: dict,
              xml: str | None = None, xml_prot: str | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente, serie,"
            " numero, chave, chave_origem, cstat, xmotivo, protocolo, xml,"
            " xml_prot) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), quem, ambiente,
             cnpj, serie, numero, chave, chave_origem, str(resp.get("cStat")),
             resp.get("xMotivo"), resp.get("protocolo"), xml, xml_prot))
        cadastro._audita(c, quem, "transmissao", cnpj,
                         f"amb {ambiente} · {serie}/{numero} · "
                         f"cStat {resp.get('cStat')}")


def _autorizado_para(chave_origem: str, ambiente: str) -> dict | None:
    """O CT-e de origem já tem contrapartida autorizada neste ambiente?"""
    with _conn() as c:
        r = c.execute(
            "SELECT serie, numero, protocolo, chave FROM emissao"
            " WHERE chave_origem=? AND ambiente=? AND cstat='100'"
            " ORDER BY id DESC LIMIT 1", (chave_origem, ambiente)).fetchone()
    return dict(r) if r else None


def transmitir(chave_origem: str, enq: documento.Enquadramento, *, quem: str,
               serie: int = SERIE_PADRAO, numero: int | None = None,
               ambiente: str = HOMOLOGACAO, repetir: bool = False) -> dict:
    """Monta, assina e transmite. Devolve o retorno da SEFAZ, sempre gravado.

    `quem` é obrigatório e não tem valor padrão: uma trilha de auditoria que
    aceita anônimo não é trilha. Já houve `?` gravado neste módulo, e meses
    depois — que é quando ela é consultada — não servia para nada.
    """
    from erpbrasil.assinatura.certificado import Certificado
    from erpbrasil.transmissao import TransmissaoSOAP

    if not quem:
        raise ValueError("Informe quem está transmitindo (trilha de auditoria).")

    cte_mod = sefaz.compatibilizar()
    d = documento.dados(chave_origem)
    cnpj = d["emit_cnpj"]
    _guardas(cnpj, d, ambiente)

    # IDEMPOTENCIA AQUI, e nao so no lote. Esta guarda existia apenas no
    # caminho em lote, e o caminho de UM documento passava por fora: foi assim
    # que a mesma prestacao ganhou DOIS CT-e autorizados em producao, com dois
    # protocolos. Documento fiscal duplicado nao se apaga - cancela-se, dentro
    # de prazo, com justificativa. A guarda mora no lugar por onde TODO envio
    # passa.
    ja = _autorizado_para(d["chave_original"], ambiente)
    if ja and not repetir:
        raise PermissionError(
            f"Já existe CT-e AUTORIZADO em {AMBIENTES[ambiente]} para o CT-e "
            f"{d['chave_original']}: série {ja['serie']}/{ja['numero']}, "
            f"protocolo {ja['protocolo']}. Emitir de novo criaria uma segunda "
            f"prestação para o mesmo serviço. Se for mesmo o caso, chame com "
            f"repetir=True — e saiba que o primeiro continua valendo até ser "
            f"cancelado.")

    if numero is None:
        numero = proximo_numero(cnpj, serie, ambiente)

    edoc = documento.montar(d, enq, numero=numero, serie=serie,
                            ambiente=ambiente)
    chave = (edoc.infCte.Id or "")[3:]

    senha = cadastro.ler_senha(cnpj)
    arq = cadastro.DIR_CERT / (
        (cadastro.mapa()[cnpj].get("certificado") or {}).get("arquivo") or "")
    if not (senha and arq.exists()):
        raise FileNotFoundError(f"Certificado ou senha ausentes para {cnpj}.")

    uf = d["emit_uf"]
    if uf not in cte_mod.SIGLA_ESTADO:
        raise ValueError(f"UF desconhecida: {uf}")

    log.info("transmitindo CT-e %s/%s de %s para a SEFAZ %s (amb %s)",
             serie, numero, cnpj, uf, ambiente)
    doc_sefaz = cte_mod.CTe(TransmissaoSOAP(Certificado(str(arq), senha)),
                            cte_mod.SIGLA_ESTADO[uf], ambiente=ambiente)

    # QR CODE (cStat 850 sem ele). Não é decoração do DACTE: é campo do
    # documento e entra ANTES da assinatura, senão o hash não fecha. Fica aqui
    # e não em `documento.py` porque a URL depende do endereço da SEFAZ da UF —
    # informação de transmissão, não de montagem.
    edoc.infCTeSupl = documento._tipo(type(edoc), "infCTeSupl")(
        qrCodCTe=doc_sefaz.monta_qrcode(chave))
    # `envia_documento` assina a raiz, comprime e posta no recebimento
    # SÍNCRONO: a resposta da autorização volta nesta mesma chamada.
    # Assina ANTES para guardar o arquivo. A transmissao assina a copia dela;
    # o conteudo e a chave sao os mesmos, e o que fica arquivado e um CT-e
    # assinado de verdade - nao o rascunho sem assinatura.
    try:
        xml_assinado = doc_sefaz.assina_raiz(edoc, edoc.infCte.Id)
    except Exception as exc:  # noqa: BLE001
        log.warning("nao foi possivel guardar o XML assinado: %s", exc)
        xml_assinado = None

    retorno = doc_sefaz.envia_documento(edoc)
    resp = _resposta(retorno)
    xml_prot = _xml_do_protocolo(retorno)
    resp.update({"chave": chave, "serie": serie, "numero": numero,
                 "ambiente": ambiente, "cnpj_emitente": cnpj,
                 "chave_origem": d["chave_original"]})
    _registra(quem, ambiente, cnpj, serie, numero, chave,
              d["chave_original"], resp, xml_assinado, xml_prot)
    return resp


# Justificativa de cancelamento tem minimo legal de 15 caracteres. O limite
# nao e capricho do sistema: e o que a SEFAZ valida, e uma justificativa de
# tres palavras nao explica nada a quem ler o evento daqui a um ano.
JUSTIFICATIVA_MINIMA = 15


def cancelar(chave: str, justificativa: str, *, quem: str,
             ambiente: str | None = None) -> dict:
    """Cancela um CT-e JA AUTORIZADO. Ato fiscal, com prazo e justificativa.

    NAO exige a liberacao de producao. Liberar existe para impedir que se
    EMITA sem querer; exigi-la para CANCELAR seria pedir para destravar a
    emissao a fim de corrigir uma emissao — o contrario do que se quer numa
    hora dessas. Desfazer tem de ser sempre mais facil que fazer.

    O ambiente sai do REGISTRO do documento, não de quem chama: cancelar em
    homologacao um documento de producao nao faz nada e daria a impressao de
    ter resolvido.
    """
    from erpbrasil.assinatura.certificado import Certificado
    from erpbrasil.transmissao import TransmissaoSOAP

    if not quem:
        raise ValueError("Informe quem está cancelando.")
    justificativa = " ".join((justificativa or "").split())
    if len(justificativa) < JUSTIFICATIVA_MINIMA:
        raise ValueError(
            f"A justificativa precisa de ao menos {JUSTIFICATIVA_MINIMA} "
            f"caracteres — é o que a SEFAZ exige, e é o que alguém vai ler "
            f"daqui a um ano para entender por que o documento caiu.")

    limpa = "".join(c for c in (chave or "") if c.isdigit())
    with _conn() as c:
        r = c.execute(
            "SELECT * FROM emissao WHERE chave=? AND cstat='100'"
            " ORDER BY id DESC LIMIT 1", (limpa,)).fetchone()
    if not r:
        raise ValueError(
            f"Não há documento AUTORIZADO com a chave {limpa} no registro. "
            f"Só se cancela o que foi autorizado — recusado não existe para "
            f"a SEFAZ.")
    reg = dict(r)
    amb = ambiente or str(reg["ambiente"])
    cnpj = reg["cnpj_emitente"]

    cte_mod = sefaz.compatibilizar()
    senha = ler_senha(cnpj)
    arq = DIR_CERT / ((mapa().get(cnpj, {}).get("certificado") or {}).get(
        "arquivo") or "")
    if not (senha and arq.exists()):
        raise FileNotFoundError(f"Certificado ou senha ausentes para {cnpj}.")
    uf = limpa[:2]
    sigla = next((k for k, v in cte_mod.SIGLA_ESTADO.items()
                  if str(v) == uf), None)
    if not sigla:
        raise ValueError(f"UF {uf} da chave não reconhecida.")

    doc = cte_mod.CTe(TransmissaoSOAP(Certificado(str(arq), senha)),
                      cte_mod.SIGLA_ESTADO[sigla], ambiente=amb)
    evento = doc.cancela_documento(limpa, reg["protocolo"], justificativa)
    retorno = doc.enviar_lote_evento([evento])
    resp = _resposta_evento(retorno)

    with _conn() as c:
        c.execute(
            "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente, serie,"
            " numero, chave, chave_origem, cstat, xmotivo, protocolo)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), quem, amb, cnpj,
             reg["serie"], reg["numero"], limpa, reg["chave_origem"],
             f"CANC:{resp.get('cStat')}", resp.get("xMotivo"),
             resp.get("protocolo")))
        cadastro._audita(c, quem, "cancelamento", cnpj,
                         f"{limpa} · {resp.get('cStat')} · {justificativa}")
    resp.update({"chave": limpa, "justificativa": justificativa,
                 "ambiente": amb})
    return resp


def _resposta_evento(retorno) -> dict:
    """Retorno do evento. 135 e 'registrado', que e o que vale."""
    def v(obj, campo):
        x = getattr(obj, campo, None)
        return getattr(x, "value", x)

    # `RetEventoCte` traz `infEvento` DIRETO - nao ha nivel `retEvento` como
    # no retorno da autorizacao. Procurando o nivel errado, cStat vinha vazio
    # e o cancelamento parecia ter falhado em silencio, sem dizer por que.
    inf = getattr(retorno, "infEvento", None)
    if isinstance(inf, list):
        inf = inf[0] if inf else None
    fonte = inf if inf is not None else retorno
    cstat = str(v(fonte, "cStat") or "")
    return {"cStat": cstat, "xMotivo": str(v(fonte, "xMotivo") or ""),
            "protocolo": str(v(fonte, "nProt") or "") or None,
            # 135 = evento registrado; 136 = registrado fora de prazo (vale,
            # mas nao cancela); qualquer outro nao registrou.
            "cancelado": cstat == "135"}


def _xml_do_protocolo(retorno) -> str | None:
    """O protocolo de autorização, em XML.

    Guardar só o NÚMERO do protocolo não basta: o que o ERP importa, o que se
    arquiva e o que se apresenta numa fiscalização é o `cteProc` — o documento
    assinado MAIS este bloco. Sem ele, a autorização existe e não se prova.
    """
    # Preferencia ABSOLUTA pelo XML que a SEFAZ mandou (guardado na leitura
    # da resposta): e o que se arquiva e o que o ERP importa. A reserializacao
    # abaixo e so um ultimo recurso, e sai com o nome da classe no lugar do
    # nome do elemento - serve para nao perder o dado, nao para importar.
    bruto = getattr(retorno, "_xml_protocolo", None)
    if bruto:
        return bruto
    prot = getattr(retorno, "protCTe", None) or getattr(retorno, "protCte", None)
    if prot is None:
        return None
    try:
        from xsdata.formats.dataclass.serializers import XmlSerializer
        from xsdata.formats.dataclass.serializers.config import SerializerConfig
        cfg = SerializerConfig(xml_declaration=False)
        return XmlSerializer(config=cfg).render(
            prot, ns_map={None: "http://www.portalfiscal.inf.br/cte"})
    except Exception as exc:  # noqa: BLE001
        # não derruba a transmissão: o documento foi autorizado de qualquer
        # jeito, e o protocolo em número continua registrado.
        log.warning("nao foi possivel guardar o XML do protocolo: %s", exc)
        return None


def _resposta(retorno) -> dict:
    """Achata o retorno da SEFAZ. O CT-e responde em dois níveis — o do LOTE e
    o do documento — e olhar só o de fora diz "lote recebido" enquanto o
    documento foi rejeitado."""
    def v(obj, campo):
        x = getattr(obj, campo, None)
        return getattr(x, "value", x)

    prot = getattr(retorno, "protCTe", None) or getattr(retorno, "protCte", None)
    inf = getattr(prot, "infProt", None) if prot is not None else None
    fonte = inf if inf is not None else retorno
    return {
        "cStat": str(v(fonte, "cStat") or v(retorno, "cStat") or ""),
        "xMotivo": str(v(fonte, "xMotivo") or v(retorno, "xMotivo") or ""),
        "cStat_lote": str(v(retorno, "cStat") or ""),
        "xMotivo_lote": str(v(retorno, "xMotivo") or ""),
        "protocolo": str(v(fonte, "nProt") or "") or None,
        "autorizado": str(v(fonte, "cStat") or "") == "100",
    }


# Onde os arquivos ficam. `data/` inteiro esta no .gitignore - e o repositorio
# do codigo e PUBLICO. Documento fiscal com CNPJ, valor e chave nao pode entrar
# em controle de versao nem por acidente.
DIR_EXPORTACAO = cadastro.ROOT / "data" / "cte_contrapartida"


def exportar(destino: str | None = None, ambiente: str = HOMOLOGACAO,
             desde: str | None = None) -> dict:
    """Grava em disco o `cteProc` de cada documento AUTORIZADO, para o ERP.

    Um arquivo por documento, nomeado pela CHAVE — que é como todo importador
    de CT-e espera encontrar, e o que evita sobrescrever um documento com
    outro. Separados por ambiente: misturar homologação com produção na mesma
    pasta é o caminho mais curto para alguém importar um documento de teste
    como se valesse.

    Reexportar é seguro: sobrescreve o mesmo arquivo com o mesmo conteúdo.
    """
    raiz = pathlib.Path(destino) if destino else DIR_EXPORTACAO
    pasta = raiz / ("producao" if ambiente == PRODUCAO else "homologacao")
    pasta.mkdir(parents=True, exist_ok=True)

    sql = ("SELECT chave, quando, xml, xml_prot FROM emissao"
           " WHERE ambiente=? AND cstat='100'"
           " AND xml IS NOT NULL AND xml_prot IS NOT NULL")
    par: list = [ambiente]
    if desde:
        sql += " AND quando >= ?"
        par.append(desde)
    sql += " ORDER BY id"

    with _conn() as c:
        linhas = [dict(r) for r in c.execute(sql, par)]

    escritos, falhas = [], []
    for r in linhas:
        alvo = pasta / f"{r['chave']}-procCTe.xml"
        try:
            alvo.write_text(montar_proc(r["xml"], r["xml_prot"]),
                            encoding="utf-8")
            escritos.append(str(alvo))
        except Exception as exc:  # noqa: BLE001
            # um arquivo que falha nao pode abortar a exportacao dos outros
            log.warning("falha ao exportar %s: %s", r["chave"], exc)
            falhas.append({"chave": r["chave"], "erro": str(exc)[:200]})

    # Sem protocolo nao ha processo: contamos a parte para o numero de
    # exportados nao parecer menor do que deveria sem explicacao.
    with _conn() as c:
        sem_proc = c.execute(
            "SELECT count(*) AS n FROM emissao WHERE ambiente=? AND cstat='100'"
            " AND (xml IS NULL OR xml_prot IS NULL)", (ambiente,)).fetchone()["n"]

    return {"pasta": str(pasta), "exportados": len(escritos),
            "falhas": falhas, "autorizados_sem_arquivo": sem_proc,
            "arquivos": escritos}


def por_dia(dias: int = 30) -> list[dict]:
    """Transmissões por DIA, separadas por ambiente e por resultado.

    Quatro séries e não duas: homologação e produção não se somam (uma não
    tem valor fiscal), e autorizado e recusado não se somam (recusado não
    emitiu nada). Juntar qualquer par produziria uma barra que parece
    trabalho feito e não é.

    O corte é por DATA da transmissão, não do CT-e de origem: o que este
    gráfico responde é "quanto saiu por dia", que é ritmo de operação.
    """
    with _conn() as c:
        linhas = [dict(r) for r in c.execute(
            "SELECT substr(quando,1,10) AS dia, ambiente,"
            " CASE WHEN cstat='100' THEN 1 ELSE 0 END AS ok,"
            " count(*) AS n"
            " FROM emissao WHERE date(quando) >= date('now', ?)"
            " GROUP BY 1,2,3 ORDER BY 1", (f"-{int(dias)} day",))]
    por: dict[str, dict] = {}
    for r in linhas:
        d = por.setdefault(r["dia"], {
            "dia": r["dia"], "homologacao_ok": 0, "homologacao_nao": 0,
            "producao_ok": 0, "producao_nao": 0})
        amb = "producao" if str(r["ambiente"]) == PRODUCAO else "homologacao"
        d[f"{amb}_{'ok' if r['ok'] else 'nao'}"] += r["n"]
    return [por[k] for k in sorted(por)]


def historico(limite: int = 50) -> list[dict]:
    """Sem a coluna `xml`: ela e grande e a tela nao a usa. Quem precisa do
    arquivo chama `xml_de`."""
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, quando, quem, ambiente, cnpj_emitente, serie, numero,"
            " chave, chave_origem, cstat, xmotivo, protocolo,"
            " (xml IS NOT NULL) AS tem_xml"
            " FROM emissao ORDER BY id DESC LIMIT ?", (limite,))]


def xml_de(chave: str) -> str | None:
    """O XML assinado de um documento ja transmitido."""
    with _conn() as c:
        r = c.execute("SELECT xml FROM emissao WHERE chave=? AND xml IS NOT NULL"
                      " ORDER BY id DESC LIMIT 1", (chave,)).fetchone()
    return r["xml"] if r else None


def proc_de(chave: str) -> str | None:
    """O `cteProc` — documento assinado + protocolo —, que é o arquivo que o
    ERP importa e que se arquiva.

    Só existe para documento AUTORIZADO: sem protocolo não há processo, e um
    `cteProc` montado com documento recusado seria um arquivo com cara de
    válido. Devolve None nos demais casos, de propósito.
    """
    with _conn() as c:
        r = c.execute(
            "SELECT xml, xml_prot FROM emissao"
            " WHERE chave=? AND cstat='100' AND xml IS NOT NULL"
            " AND xml_prot IS NOT NULL ORDER BY id DESC LIMIT 1",
            (chave,)).fetchone()
    if not r:
        return None
    return montar_proc(r["xml"], r["xml_prot"])


def montar_proc(xml_assinado: str, xml_protocolo: str) -> str:
    """Envelopa documento e protocolo no `cteProc`, como a SEFAZ define.

    Feito por texto e não por árvore: o XML assinado NÃO pode ser reserializado
    — qualquer mudança de espaço em branco ou de ordem de atributo quebra a
    assinatura, e o arquivo passa a ser recusado por quem for validar.
    """
    def _corpo(x: str) -> str:
        x = x.strip()
        if x.startswith("<?xml"):
            x = x[x.index("?>") + 2:].lstrip()
        return x

    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<cteProc xmlns="http://www.portalfiscal.inf.br/cte" versao="4.00">'
            + _corpo(xml_assinado) + _corpo(xml_protocolo) + '</cteProc>')
