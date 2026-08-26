# api/contrapartida/cadastro.py
"""Procurações e certificados dos agregados — o que autoriza emitir por eles.

POR QUE ISTO EXISTE ANTES DA EMISSÃO
====================================
Emitir CT-e com o certificado do agregado é ASSINAR COMO ELE. Não é uma
configuração: é um ato jurídico praticado por conta e ordem de terceiro. Isso
vira requisito de estrutura de dados, não recomendação de rodapé:

  - procuração com ESCOPO e VALIDADE, por agregado, e a rotina não emite para
    quem não tem uma vigente;
  - certificado A1 (arquivo). A3 mora em token físico e NÃO automatiza — quem
    for A3 fica marcado como impedido, com o motivo, em vez de falhar na hora
    da transmissão;
  - validade do certificado, que é de UM ANO. Sem monitor, a rotina para em
    silêncio e a empresa descobre pelo cliente;
  - trilha de auditoria de quem cadastrou o quê e quando.

ONDE MORA CADA COISA, E POR QUÊ
-------------------------------
  metadados (validade, escopo, tipo)  -> data/contrapartida.db (SQLite local)
  SENHA do certificado                -> cofre data/credenciais.json (0600)
  arquivo .pfx                        -> data/certificados/, 0600

`data/*` está inteiro no .gitignore — e isso importa porque **o repositório do
código é público**. Senha de certificado em banco versionado seria um vazamento
permanente; por isso a senha nunca entra nesta tabela, nem mascarada.

A senha segue a regra do cofre que o resto do sistema já usa: **entra e não
volta**. Nenhuma função aqui devolve senha, nem para uso interno — quem
assinar, um dia, chama `api.credenciais.ler()` diretamente.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path

from api import credenciais

log = logging.getLogger("cortex.contrapartida.cadastro")

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "contrapartida.db"
DIR_CERT = ROOT / "data" / "certificados"

# Certificado A1 vale um ano. Avisar com 30 dias dá tempo de renovar sem
# parar a emissão; avisar no dia do vencimento não serve para nada.
ALERTA_VENCIMENTO_DIAS = 30

# Prefixo da chave no cofre. Uma senha POR AGREGADO — por isso não entra na
# lista CONHECIDAS de credenciais.py, que é de credenciais nomeadas e fixas.
PREFIXO_SENHA = "CERT_SENHA_"

_DDL = """
CREATE TABLE IF NOT EXISTS procuracao (
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
    return c


def _hoje() -> str:
    return date.today().isoformat()


def _audita(c: sqlite3.Connection, quem: str, acao: str, cnpj: str,
            detalhe: str = "") -> None:
    c.execute("INSERT INTO auditoria(quando, quem, acao, cnpj, detalhe)"
              " VALUES(?,?,?,?,?)",
              (datetime.now().isoformat(timespec="seconds"), quem, acao,
               cnpj, detalhe))


# --------------------------------------------------------------- escrita ---

def gravar_procuracao(cnpj: str, escopo: str, valida_de: str, valida_ate: str,
                      quem: str, observacao: str = "") -> dict:
    if not (cnpj and escopo and valida_de and valida_ate):
        raise ValueError("cnpj, escopo e as duas datas de validade são obrigatórios.")
    if valida_ate < valida_de:
        raise ValueError("A validade final é anterior à inicial.")
    with _conn() as c:
        c.execute(
            "INSERT INTO procuracao(cnpj, escopo, valida_de, valida_ate,"
            " observacao, criado_em, criado_por) VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(cnpj) DO UPDATE SET escopo=excluded.escopo,"
            " valida_de=excluded.valida_de, valida_ate=excluded.valida_ate,"
            " observacao=excluded.observacao, criado_em=excluded.criado_em,"
            " criado_por=excluded.criado_por",
            (cnpj, escopo, valida_de, valida_ate, observacao,
             datetime.now().isoformat(timespec="seconds"), quem))
        _audita(c, quem, "procuracao", cnpj, f"{valida_de} a {valida_ate}")
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
        credenciais.gravar(PREFIXO_SENHA + cnpj, senha)
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


def prontidao(cnpj: str, proc: dict | None, cert: dict | None,
              tem_senha: bool) -> dict:
    """Este agregado pode ter CT-e emitido por ele HOJE?

    Devolve sempre o MOTIVO, nao so o booleano: "não pronto" sem dizer o que
    falta obriga a abrir tres telas para descobrir.
    """
    faltas: list[str] = []
    alertas: list[str] = []

    if not proc:
        faltas.append("sem procuração cadastrada")
    else:
        d = _dias_ate(proc.get("valida_ate"))
        if d is not None and d < 0:
            faltas.append(f"procuração vencida há {abs(d)} dias")
        elif proc.get("valida_de", "") > _hoje():
            faltas.append("procuração ainda não vigente")
        elif d is not None and d <= ALERTA_VENCIMENTO_DIAS:
            alertas.append(f"procuração vence em {d} dias")

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
    """{cnpj: {procuracao, certificado, prontidao}} para a tela cruzar."""
    with _conn() as c:
        procs = {r["cnpj"]: dict(r) for r in c.execute("SELECT * FROM procuracao")}
        certs = {r["cnpj"]: dict(r) for r in c.execute("SELECT * FROM certificado")}
    out: dict[str, dict] = {}
    for cnpj in set(procs) | set(certs):
        cert = certs.get(cnpj)
        tem_senha = bool(credenciais.ler(PREFIXO_SENHA + cnpj)) if cert else False
        out[cnpj] = {
            "procuracao": procs.get(cnpj),
            # `arquivo` e nome, nunca conteudo; senha nunca sai daqui
            "certificado": cert,
            "tem_senha": tem_senha,
            "prontidao": prontidao(cnpj, procs.get(cnpj), cert, tem_senha),
        }
    return out


def auditoria(limite: int = 200) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM auditoria ORDER BY id DESC LIMIT ?", (limite,))]
