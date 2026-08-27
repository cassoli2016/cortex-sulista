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
from datetime import date, datetime

from api.contrapartida import cadastro, documento, sefaz

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
_MIGRACOES = ("ALTER TABLE emissao ADD COLUMN xml TEXT",)

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


def producao_liberada() -> bool:
    """Produção está destravada? PADRÃO: não, e ausência de registro é NÃO."""
    r = config_lida(CHAVE_PRODUCAO)
    return bool(r) and r["valor"] == "1"


def liberar_producao(ativa: bool, quem: str, confirmacao: str = "") -> dict:
    """Destrava (ou trava de volta) a emissão em produção.

    LIGAR exige a frase de confirmação; DESLIGAR não — desligar é sempre
    seguro e não pode depender de lembrar de uma frase no meio de um problema.
    """
    if ativa and confirmacao.strip().upper() != CONFIRMACAO_PRODUCAO:
        raise PermissionError(
            f"Para liberar produção, confirme com a frase "
            f"'{CONFIRMACAO_PRODUCAO}'. Em produção o documento é real e "
            f"emitido em nome de outra empresa: se sair errado, não se apaga "
            f"— cancela-se, dentro de prazo, com justificativa, e repercute na "
            f"escrituração dos dois lados.")
    return config_grava(CHAVE_PRODUCAO, ativa, quem, "liberacao_producao")


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
              xml: str | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente, serie,"
            " numero, chave, chave_origem, cstat, xmotivo, protocolo, xml)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), quem, ambiente,
             cnpj, serie, numero, chave, chave_origem, str(resp.get("cStat")),
             resp.get("xMotivo"), resp.get("protocolo"), xml))
        cadastro._audita(c, quem, "transmissao", cnpj,
                         f"amb {ambiente} · {serie}/{numero} · "
                         f"cStat {resp.get('cStat')}")


def transmitir(chave_origem: str, enq: documento.Enquadramento, *, quem: str,
               serie: int = SERIE_PADRAO, numero: int | None = None,
               ambiente: str = HOMOLOGACAO) -> dict:
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
    resp.update({"chave": chave, "serie": serie, "numero": numero,
                 "ambiente": ambiente, "cnpj_emitente": cnpj,
                 "chave_origem": d["chave_original"]})
    _registra(quem, ambiente, cnpj, serie, numero, chave,
              d["chave_original"], resp, xml_assinado)
    return resp


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
    """O XML assinado de um documento ja transmitido, para arquivo ou para
    importacao no ERP."""
    with _conn() as c:
        r = c.execute("SELECT xml FROM emissao WHERE chave=? AND xml IS NOT NULL"
                      " ORDER BY id DESC LIMIT 1", (chave,)).fetchone()
    return r["xml"] if r else None
