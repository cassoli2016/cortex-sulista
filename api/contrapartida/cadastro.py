# api/contrapartida/cadastro.py
"""Procurações e certificados dos agregados — o que autoriza emitir por eles.

POR QUE ISTO EXISTE ANTES DA EMISSÃO
====================================
Emitir CT-e com o certificado do agregado é ASSINAR COMO ELE. Não é uma
configuração: é um ato jurídico praticado por conta e ordem de terceiro. Isso
vira requisito de estrutura de dados, não recomendação de rodapé:

  - AUTORIZAÇÃO com ESCOPO e VALIDADE, por agregado, e a rotina não emite
    para quem não tem uma vigente. O nome do instrumento (procuração, cláusula
    de contrato, termo) é decisão do jurídico; o que o software exige é a
    validade — sem data de fim ele não sabe PARAR quando o agregado sai da
    frota — e o escopo, porque o certificado assina qualquer coisa, não só
    CT-e;
  - certificado A1 (arquivo). A3 mora em token físico e NÃO automatiza — quem
    for A3 fica marcado como impedido, com o motivo, em vez de falhar na hora
    da transmissão;
  - validade do certificado, que é de UM ANO. Sem monitor, a rotina para em
    silêncio e a empresa descobre pelo cliente;
  - trilha de auditoria de quem cadastrou o quê e quando.

ONDE MORA CADA COISA, E POR QUÊ
-------------------------------
  metadados (validade, escopo, tipo)  -> data/contrapartida.db (SQLite local)
  SENHA do certificado                -> data/certificados/senhas.json (0600)
  arquivo .pfx                        -> data/certificados/, 0600

`data/*` está inteiro no .gitignore — e isso importa porque **o repositório do
código é público**. Senha de certificado em banco versionado seria um vazamento
permanente; por isso a senha nunca entra nesta tabela, nem mascarada.

A senha segue a regra do cofre que o resto do sistema já usa: **entra e não
volta**: `tem_senha()` diz só SE existe, e `ler_senha()` é o único caminho de
saída — nenhum endpoint o expõe.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger("cortex.contrapartida.cadastro")

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "contrapartida.db"
DIR_CERT = ROOT / "data" / "certificados"

# Certificado A1 vale um ano. Avisar com 30 dias dá tempo de renovar sem
# parar a emissão; avisar no dia do vencimento não serve para nada.
ALERTA_VENCIMENTO_DIAS = 30

# Cofre PROPRIO das senhas de certificado. Nao usa api/credenciais.py de
# proposito: aquele cofre valida contra uma lista de credenciais NOMEADAS e
# FIXAS (token da Gobrax, senha de SMTP...), que a tela de Gestao edita uma a
# uma. Aqui e uma senha POR AGREGADO, dinamica - 54 hoje, outras amanha.
# Mesma disciplina: 0600, fora do git, valor entra e NAO volta.
SENHAS_PATH = ROOT / "data" / "certificados" / "senhas.json"


def _senhas() -> dict:
    if not SENHAS_PATH.exists():
        return {}
    try:
        return json.loads(SENHAS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        log.warning("cofre de senhas ilegivel - tratando como vazio")
        return {}


def gravar_senha(cnpj: str, senha: str) -> None:
    d = _senhas()
    if senha:
        d[cnpj] = {"valor": senha,
                   "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M")}
    else:
        d.pop(cnpj, None)
    SENHAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SENHAS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    SENHAS_PATH.chmod(0o600)


def tem_senha(cnpj: str) -> bool:
    """So diz SE existe. Quem for assinar um dia chama `ler_senha`."""
    return bool((_senhas().get(cnpj) or {}).get("valor"))


def ler_senha(cnpj: str) -> str | None:
    """Unico caminho de saida da senha, e nenhum endpoint o expoe."""
    return (_senhas().get(cnpj) or {}).get("valor")


_DDL = """
CREATE TABLE IF NOT EXISTS autorizacao (
  cnpj        TEXT PRIMARY KEY,
  escopo      TEXT NOT NULL,
  valida_de   TEXT NOT NULL,
  valida_ate  TEXT NOT NULL,
  observacao  TEXT,
  criado_em   TEXT NOT NULL,
  criado_por  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS certificado (
  cnpj        TEXT PRIMARY KEY,
  tipo        TEXT NOT NULL,          -- 'A1' | 'A3'
  arquivo     TEXT,                   -- nome do .pfx em data/certificados
  valida_ate  TEXT,
  titular     TEXT,
  criado_em   TEXT NOT NULL,
  criado_por  TEXT NOT NULL
);
-- Trilha de auditoria. Quem autorizou emitir em nome de quem, e quando, tem
-- de ser respondivel meses depois - inclusive contra o proprio CORTEX.
CREATE TABLE IF NOT EXISTS auditoria (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  quando      TEXT NOT NULL,
  quem        TEXT NOT NULL,
  acao        TEXT NOT NULL,
  cnpj        TEXT NOT NULL,
  detalhe     TEXT
);
"""


def _conn() -> sqlite3.Connection:
    """Conexao curta, WAL, commit automatico — mesmo padrao do auth.db."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(_DDL)
    _migrar_procuracao(c)
    return c


def _migrar_procuracao(c: sqlite3.Connection) -> None:
    """A tabela se chamava `procuracao`. Renomear jogando fora o que ja estava
    cadastrado obrigaria a redigitar - e o registro perdido seria justamente a
    autorizacao de alguem."""
    try:
        existe = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='procuracao'"
        ).fetchone()
        if not existe:
            return
        c.execute("INSERT OR IGNORE INTO autorizacao SELECT * FROM procuracao")
        c.execute("DROP TABLE procuracao")
        log.info("tabela procuracao migrada para autorizacao")
    except Exception as exc:  # noqa: BLE001
        log.warning("migracao procuracao->autorizacao falhou: %s", exc)


def _hoje() -> str:
    return date.today().isoformat()


def _audita(c: sqlite3.Connection, quem: str, acao: str, cnpj: str,
            detalhe: str = "") -> None:
    c.execute("INSERT INTO auditoria(quando, quem, acao, cnpj, detalhe)"
              " VALUES(?,?,?,?,?)",
              (datetime.now().isoformat(timespec="seconds"), quem, acao,
               cnpj, detalhe))


# --------------------------------------------------------------- escrita ---

def gravar_autorizacao(cnpj: str, escopo: str, valida_de: str, valida_ate: str,
                      quem: str, observacao: str = "") -> dict:
    if not (cnpj and escopo and valida_de and valida_ate):
        raise ValueError("CNPJ, escopo e as duas datas de validade são obrigatórios.")
    if valida_ate < valida_de:
        raise ValueError("A validade final é anterior à inicial.")
    with _conn() as c:
        c.execute(
            "INSERT INTO autorizacao(cnpj, escopo, valida_de, valida_ate,"
            " observacao, criado_em, criado_por) VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(cnpj) DO UPDATE SET escopo=excluded.escopo,"
            " valida_de=excluded.valida_de, valida_ate=excluded.valida_ate,"
            " observacao=excluded.observacao, criado_em=excluded.criado_em,"
            " criado_por=excluded.criado_por",
            (cnpj, escopo, valida_de, valida_ate, observacao,
             datetime.now().isoformat(timespec="seconds"), quem))
        _audita(c, quem, "autorizacao", cnpj, f"{valida_de} a {valida_ate}")
    return {"ok": True}


def gravar_certificado(cnpj: str, tipo: str, quem: str, arquivo: str = "",
                       valida_ate: str = "", titular: str = "",
                       senha: str | None = None) -> dict:
    """A SENHA nao entra na tabela: vai para o cofre, e de la nao volta."""
    if tipo not in ("A1", "A3"):
        raise ValueError("Tipo de certificado deve ser A1 ou A3.")
    with _conn() as c:
        c.execute(
            "INSERT INTO certificado(cnpj, tipo, arquivo, valida_ate, titular,"
            " criado_em, criado_por) VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(cnpj) DO UPDATE SET tipo=excluded.tipo,"
            " arquivo=excluded.arquivo, valida_ate=excluded.valida_ate,"
            " titular=excluded.titular, criado_em=excluded.criado_em,"
            " criado_por=excluded.criado_por",
            (cnpj, tipo, arquivo or None, valida_ate or None, titular or None,
             datetime.now().isoformat(timespec="seconds"), quem))
        _audita(c, quem, "certificado", cnpj, f"{tipo} valido ate {valida_ate or '?'}")
    if senha:
        # cofre 0600, fora do git. A auditoria registra QUE houve senha, nunca
        # qual: o proprio log seria um vazamento.
        gravar_senha(cnpj, senha)
        with _conn() as c:
            _audita(c, quem, "senha_certificado", cnpj, "senha gravada no cofre")
    return {"ok": True}


# ---------------------------------------------------------------- leitura ---

def _dias_ate(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return (date.fromisoformat(iso) - date.today()).days
    except ValueError:
        return None


def prontidao(cnpj: str, autz: dict | None, cert: dict | None,
              tem_senha: bool) -> dict:
    """Este agregado pode ter CT-e emitido por ele HOJE?

    Devolve sempre o MOTIVO, nao so o booleano: "não pronto" sem dizer o que
    falta obriga a abrir tres telas para descobrir.
    """
    faltas: list[str] = []
    alertas: list[str] = []

    if not autz:
        faltas.append("sem autorização cadastrada")
    else:
        d = _dias_ate(autz.get("valida_ate"))
        if d is not None and d < 0:
            faltas.append(f"autorização vencida há {abs(d)} dias")
        elif autz.get("valida_de", "") > _hoje():
            faltas.append("autorização ainda não vigente")
        elif d is not None and d <= ALERTA_VENCIMENTO_DIAS:
            alertas.append(f"autorização vence em {d} dias")

    if not cert:
        faltas.append("sem certificado cadastrado")
    elif cert.get("tipo") == "A3":
        # nao e pendencia que se resolve preenchendo campo: A3 exige o token
        # fisico presente a cada assinatura.
        faltas.append("certificado A3 (token físico) — não automatiza")
    else:
        d = _dias_ate(cert.get("valida_ate"))
        if d is None:
            alertas.append("validade do certificado não informada")
        elif d < 0:
            faltas.append(f"certificado vencido há {abs(d)} dias")
        elif d <= ALERTA_VENCIMENTO_DIAS:
            alertas.append(f"certificado vence em {d} dias")
        if not cert.get("arquivo"):
            faltas.append("arquivo .pfx não enviado")
        if not tem_senha:
            faltas.append("senha do certificado não cadastrada")

    return {"pronto": not faltas, "faltas": faltas, "alertas": alertas}


def mapa() -> dict[str, dict]:
    """{cnpj: {autorizacao, certificado, prontidao}} para a tela cruzar."""
    with _conn() as c:
        autz = {r["cnpj"]: dict(r) for r in c.execute("SELECT * FROM autorizacao")}
        certs = {r["cnpj"]: dict(r) for r in c.execute("SELECT * FROM certificado")}
    out: dict[str, dict] = {}
    for cnpj in set(autz) | set(certs):
        cert = certs.get(cnpj)
        ts = tem_senha(cnpj) if cert else False
        out[cnpj] = {
            "autorizacao": autz.get(cnpj),
            # `arquivo` e nome, nunca conteudo; senha nunca sai daqui
            "certificado": cert,
            "tem_senha": ts,
            "prontidao": prontidao(cnpj, autz.get(cnpj), cert, ts),
        }
    return out


def auditoria(limite: int = 200) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM auditoria ORDER BY id DESC LIMIT ?", (limite,))]


def ie_utilizavel(ie: str | None) -> bool:
    """IE que serve para emitir tem DIGITO. "ISENTO", "-" ou vazio, nao.

    Mora AQUI e nao na camada de tela porque quem emite tambem precisa da
    regra. Ela nascera em `servico`, so a tela consultava, e o lote saia
    emitindo para quem nao tem IE - a SEFAZ recusava com "229 - IE do emitente
    nao informada", documento a documento, exatamente o que o comentario
    original dizia que aconteceria. Regra de aptidao usada por duas camadas
    tem de ficar embaixo das duas.

    Nao se afirma que quem esta como ISENTO fica de fora para sempre - pode
    ser cadastro velho no ERP. Mas nao da para tratar como PRONTO quem talvez
    nem possa emitir.
    """
    return bool("".join(c for c in (ie or "") if c.isdigit()))
