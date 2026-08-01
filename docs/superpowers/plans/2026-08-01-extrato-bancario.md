# Extrato Bancário — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tela `extb` "Extrato Bancário" no grupo Financeiro que importa extratos OFX/CSV e valida, por conta e por dia, se `contacorrente_saldo` do ERP AVA bate com o banco real.

**Architecture:** Subpacote `api/extrato/` (padrão do `api/orcamento/`) com 5 módulos de responsabilidade única: `armazenamento` (SQLite `data/extrato.db`), `parser_ofx`, `parser_csv`, `comparacao` (função pura) e `servico` (orquestra). Endpoints em `api/main.py`, RBAC em `api/auth.py`, tela na SPA `api/static/index.html`, alertas em `api/alertas.py`.

**Tech Stack:** Python 3.14 + FastAPI + psycopg 3 (leitura do AVA) + sqlite3 (stdlib, escrita local) + JS vanilla no front. Testes: pytest. Sem dependência nova.

## Global Constraints

- **O AVA é réplica somente-leitura.** Nenhum INSERT/UPDATE/DELETE no PostgreSQL. Toda escrita vai para SQLite em `data/` (ignorado pelo git).
- **Banco AVA é LATIN-1:** nunca usar `—`, `→`, `≥`, `×` dentro de string SQL. Usar `-`.
- **`%` em LIKE dentro de SQL executado por `db.query` precisa ser `%%`.**
- **Sem dependência nova no `pyproject.toml`.** Upload chega como **corpo bruto** (`await req.body()`) com o nome do arquivo em query string — `UploadFile` exigiria `python-multipart`, que não está instalado e cujo `uv sync` no AutoDeploy é não-fatal (a API subiria sem a dep e o endpoint quebraria em produção).
- **Tolerância de comparação: R$ 0,01** (constante `TOLERANCIA = 0.01`).
- **Sinal do valor:** crédito positivo, débito negativo, em toda a stack.
- **Parse de valor pt-BR:** regex antes de converter; ponto em grupos de exatamente 3 dígitos é milhar (`1.234` = 1234,00); vírgula é decimal. Nunca `float()` direto.
- **Datas em horário local** (`date.today()`, `_iso()` no front — `toISOString()` em UTC−3 volta um dia).
- **Front:** toda tela nova entra na sidebar **e na gaveta mobile**; `type="text"` + `inputmode="decimal"` em campo de valor (nunca `type="number"`); ⓘ de procedência em todo card; `.tabroll` + contador "X de Y" em tabela longa.
- **Antes de gravar patch no `index.html`:** `node --check` no JS extraído; antes de gravar patch em `.py`: `ast.parse`. Substituição sempre por trecho literal único (nunca regex ampla — já engoliu constantes entre funções uma vez).
- **Validar imports após mexer em `api/`:** `uv run python -c "from api import main"`.
- Limite de upload: **8 MB por arquivo** (extrato OFX real tem dezenas/centenas de KB).

---

### Task 1: Persistência local (SQLite)

**Files:**
- Create: `api/extrato/__init__.py`
- Create: `api/extrato/armazenamento.py`
- Create: `tests/extrato/__init__.py`
- Test: `tests/extrato/test_armazenamento.py`

**Interfaces:**
- Consumes: nada (primeira task).
- Produces:
  - `DB_PATH: Path` (= `ROOT/data/extrato.db`)
  - `init_db(path: Path = DB_PATH) -> None`
  - `obter_ou_criar_conta(path, ident: str, rotulo: str) -> int` (devolve `conta_id`)
  - `mapear_conta(path, conta_id: int, erp_banco: int, erp_agencia: str, erp_conta: str, rotulo: str | None = None) -> None`
  - `salvar_mapa_csv(path, conta_id: int, mapa: dict) -> None`
  - `conta_por_ident(path, ident: str) -> dict | None`
  - `listar_contas(path) -> list[dict]`
  - `gravar_lancamentos(path, conta_id: int, itens: list[dict], arquivo: str, formato: str) -> dict` — devolve `{"importacao_id": int, "novas": int, "duplicadas": int}`; cada item é `{"dt": "YYYY-MM-DD", "valor": float, "tipo": "C"|"D", "historico": str, "numerodoc": str, "fitid": str | None}`
  - `gravar_saldo_extrato(path, conta_id: int, dt: str, saldo: float) -> None`
  - `saldos_extrato(path, conta_id: int) -> list[dict]` (ordenado por `dt`)
  - `lancamentos(path, conta_id: int, dt_de: str, dt_ate: str) -> list[dict]`
  - `listar_importacoes(path, limite: int = 20) -> list[dict]`
  - `apagar_importacao(path, importacao_id: int) -> int` (nº de lançamentos apagados)

- [ ] **Step 1: Write the failing test**

Create `tests/extrato/__init__.py` (empty file) and `tests/extrato/test_armazenamento.py`:

```python
"""Persistência local do extrato (SQLite) — sem AVA, sem rede."""
from __future__ import annotations

import pytest

from api.extrato import armazenamento as arm


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "extrato.db"
    arm.init_db(p)
    return p


def _item(dt="2026-07-01", valor=100.0, tipo="C", hist="TED RECEBIDA",
          doc="123", fitid="F1"):
    return {"dt": dt, "valor": valor, "tipo": tipo, "historico": hist,
            "numerodoc": doc, "fitid": fitid}


def test_conta_criada_uma_vez(db):
    a = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau 539349")
    b = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau 539349")
    assert a == b
    assert len(arm.listar_contas(db)) == 1


def test_grava_lancamentos_e_dedup_por_fitid(db):
    cid = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau")
    r1 = arm.gravar_lancamentos(db, cid, [_item(), _item(fitid="F2", valor=-50.0, tipo="D")],
                                "ext.ofx", "ofx")
    assert (r1["novas"], r1["duplicadas"]) == (2, 0)
    # re-upload do MESMO arquivo: nada entra de novo
    r2 = arm.gravar_lancamentos(db, cid, [_item(), _item(fitid="F2", valor=-50.0, tipo="D")],
                                "ext.ofx", "ofx")
    assert (r2["novas"], r2["duplicadas"]) == (0, 2)
    assert len(arm.lancamentos(db, cid, "2026-07-01", "2026-07-31")) == 2


def test_dedup_sem_fitid_usa_hash_e_preserva_repetidos_do_dia(db):
    cid = arm.obter_ou_criar_conta(db, "csv:itau", "Itau CSV")
    # dois lançamentos IDÊNTICOS no mesmo dia são legítimos (duas tarifas iguais)
    itens = [_item(fitid=None), _item(fitid=None)]
    r1 = arm.gravar_lancamentos(db, cid, itens, "ext.csv", "csv")
    assert (r1["novas"], r1["duplicadas"]) == (2, 0)
    r2 = arm.gravar_lancamentos(db, cid, itens, "ext.csv", "csv")
    assert (r2["novas"], r2["duplicadas"]) == (0, 2)


def test_apagar_importacao_remove_lancamentos(db):
    cid = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau")
    r = arm.gravar_lancamentos(db, cid, [_item()], "ext.ofx", "ofx")
    assert arm.apagar_importacao(db, r["importacao_id"]) == 1
    assert arm.lancamentos(db, cid, "2026-07-01", "2026-07-31") == []
    assert arm.listar_importacoes(db) == []


def test_mapeamento_erp_e_mapa_csv(db):
    cid = arm.obter_ou_criar_conta(db, "csv:itau", "Itau CSV")
    arm.mapear_conta(db, cid, 341, "0098", "539349", rotulo="Itau conta movimento")
    arm.salvar_mapa_csv(db, cid, {"dt": 0, "valor": 3, "historico": 1})
    c = arm.conta_por_ident(db, "csv:itau")
    assert (c["erp_banco"], c["erp_agencia"], c["erp_conta"]) == (341, "0098", "539349")
    assert c["rotulo"] == "Itau conta movimento"
    assert c["mapa_csv"] == {"dt": 0, "valor": 3, "historico": 1}


def test_saldo_extrato_upsert(db):
    cid = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau")
    arm.gravar_saldo_extrato(db, cid, "2026-07-31", 1000.0)
    arm.gravar_saldo_extrato(db, cid, "2026-07-31", 1200.0)   # reimport corrige
    assert arm.saldos_extrato(db, cid) == [{"dt": "2026-07-31", "saldo": 1200.0}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/extrato/test_armazenamento.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.extrato'`

- [ ] **Step 3: Write minimal implementation**

Create `api/extrato/__init__.py`:

```python
"""Importação de extrato bancário e validação de saldos/fluxo contra o ERP."""
```

Create `api/extrato/armazenamento.py`:

```python
"""Persistência local do extrato bancário (SQLite).

O ERP AVA é réplica somente-leitura, então o extrato importado é dado nosso.
Segue o padrão de `api/orcamento/armazenamento.py`: conexão curta com commit
automático e WAL.

Dedup (idempotência de re-upload): o OFX traz FITID, identificador único do
lançamento no banco -> chave natural. CSV não tem FITID: a chave passa a ser o
hash de (dt, valor, historico, numerodoc) + a ORDEM da ocorrência no dia, para
que dois lançamentos legitimamente idênticos no mesmo dia (duas tarifas iguais)
sejam preservados, mas o mesmo arquivo subido duas vezes não duplique nada.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "extrato.db"


@contextmanager
def _conn(path: Path):
    Path(path).parent.mkdir(exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        with c:
            yield c
    finally:
        c.close()


def init_db(path: Path = DB_PATH) -> None:
    with _conn(path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS ext_conta(
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ident       TEXT NOT NULL UNIQUE,
            rotulo      TEXT NOT NULL,
            erp_banco   INTEGER,
            erp_agencia TEXT,
            erp_conta   TEXT,
            mapa_csv    TEXT,
            criado_em   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS ext_importacao(
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            conta_id  INTEGER NOT NULL REFERENCES ext_conta(id) ON DELETE CASCADE,
            arquivo   TEXT NOT NULL,
            formato   TEXT NOT NULL,
            dt_de     TEXT,
            dt_ate    TEXT,
            novas     INTEGER NOT NULL DEFAULT 0,
            duplicadas INTEGER NOT NULL DEFAULT 0,
            ignoradas INTEGER NOT NULL DEFAULT 0,
            quando    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS ext_lancamento(
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            conta_id      INTEGER NOT NULL REFERENCES ext_conta(id) ON DELETE CASCADE,
            importacao_id INTEGER NOT NULL REFERENCES ext_importacao(id) ON DELETE CASCADE,
            dt            TEXT NOT NULL,
            valor         REAL NOT NULL,
            tipo          TEXT NOT NULL,
            historico     TEXT NOT NULL DEFAULT '',
            numerodoc     TEXT NOT NULL DEFAULT '',
            fitid         TEXT,
            chave         TEXT NOT NULL,
            UNIQUE (conta_id, chave)
        );
        CREATE TABLE IF NOT EXISTS ext_saldo(
            conta_id INTEGER NOT NULL REFERENCES ext_conta(id) ON DELETE CASCADE,
            dt       TEXT NOT NULL,
            saldo    REAL NOT NULL,
            PRIMARY KEY (conta_id, dt)
        );
        CREATE INDEX IF NOT EXISTS ix_ext_lanc_conta_dt ON ext_lancamento(conta_id, dt);
        CREATE INDEX IF NOT EXISTS ix_ext_lanc_imp ON ext_lancamento(importacao_id);
        """)


def _identidade(item: dict) -> str:
    """Identidade de conteúdo do lançamento. UMA definição só: o contador de
    ocorrência e o hash precisam concordar, senão a mesma transação recebe
    ocorrências diferentes conforme a ORDEM do arquivo e o re-upload duplica."""
    hist = " ".join((item.get("historico") or "").split()).upper()
    return "|".join([item["dt"], f"{float(item['valor']):.2f}", hist,
                     (item.get("numerodoc") or "").strip()])


def _chave(item: dict, ocorrencia: int) -> str:
    """FITID quando existe; senão hash da identidade + ordem da repetição."""
    fitid = (item.get("fitid") or "").strip()
    if fitid:
        return "fitid:" + fitid
    cru = f"{_identidade(item)}|{ocorrencia}"
    return "hash:" + hashlib.sha1(cru.encode("utf-8")).hexdigest()


def obter_ou_criar_conta(path: Path, ident: str, rotulo: str) -> int:
    with _conn(path) as c:
        row = c.execute("SELECT id FROM ext_conta WHERE ident=?", (ident,)).fetchone()
        if row:
            return int(row["id"])
        cur = c.execute("INSERT INTO ext_conta(ident, rotulo) VALUES(?,?)", (ident, rotulo))
        return int(cur.lastrowid)


def mapear_conta(path: Path, conta_id: int, erp_banco: int, erp_agencia: str,
                 erp_conta: str, rotulo: str | None = None) -> None:
    with _conn(path) as c:
        if rotulo:
            c.execute("UPDATE ext_conta SET erp_banco=?, erp_agencia=?, erp_conta=?, rotulo=? "
                      "WHERE id=?", (erp_banco, erp_agencia, erp_conta, rotulo, conta_id))
        else:
            c.execute("UPDATE ext_conta SET erp_banco=?, erp_agencia=?, erp_conta=? WHERE id=?",
                      (erp_banco, erp_agencia, erp_conta, conta_id))


def salvar_mapa_csv(path: Path, conta_id: int, mapa: dict) -> None:
    with _conn(path) as c:
        c.execute("UPDATE ext_conta SET mapa_csv=? WHERE id=?",
                  (json.dumps(mapa, ensure_ascii=False), conta_id))


def _conta_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["mapa_csv"] = json.loads(d["mapa_csv"]) if d.get("mapa_csv") else None
    return d


def conta_por_ident(path: Path, ident: str) -> dict | None:
    with _conn(path) as c:
        row = c.execute("SELECT * FROM ext_conta WHERE ident=?", (ident,)).fetchone()
    return _conta_dict(row) if row else None


def listar_contas(path: Path = DB_PATH) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute("SELECT * FROM ext_conta ORDER BY rotulo").fetchall()
    return [_conta_dict(r) for r in rows]


def gravar_lancamentos(path: Path, conta_id: int, itens: list[dict], arquivo: str,
                       formato: str, ignoradas: int = 0) -> dict:
    datas = sorted(i["dt"] for i in itens) or [None]
    novas = dupl = 0
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO ext_importacao(conta_id, arquivo, formato, dt_de, dt_ate, ignoradas) "
            "VALUES(?,?,?,?,?,?)", (conta_id, arquivo, formato, datas[0], datas[-1], ignoradas))
        imp_id = int(cur.lastrowid)
        vistos: dict[str, int] = {}
        for item in itens:
            base = _identidade(item)      # MESMA identidade que o hash usa
            vistos[base] = vistos.get(base, 0) + 1
            chave = _chave(item, vistos[base])
            ins = c.execute(
                "INSERT OR IGNORE INTO ext_lancamento"
                "(conta_id, importacao_id, dt, valor, tipo, historico, numerodoc, fitid, chave) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (conta_id, imp_id, item["dt"], float(item["valor"]),
                 ("C" if float(item["valor"]) >= 0 else "D"),
                 item.get("historico") or "", item.get("numerodoc") or "",
                 item.get("fitid"), chave))
            if ins.rowcount:
                novas += 1
            else:
                dupl += 1
        c.execute("UPDATE ext_importacao SET novas=?, duplicadas=? WHERE id=?",
                  (novas, dupl, imp_id))
        # importação que não trouxe nada novo não fica na trilha (poluiria a lista
        # de uploads com registros vazios a cada re-upload)
        if novas == 0:
            c.execute("DELETE FROM ext_importacao WHERE id=?", (imp_id,))
    return {"importacao_id": imp_id if novas else 0, "novas": novas, "duplicadas": dupl}


def gravar_saldo_extrato(path: Path, conta_id: int, dt: str, saldo: float) -> None:
    with _conn(path) as c:
        c.execute("INSERT INTO ext_saldo(conta_id, dt, saldo) VALUES(?,?,?) "
                  "ON CONFLICT(conta_id, dt) DO UPDATE SET saldo=excluded.saldo",
                  (conta_id, dt, float(saldo)))


def saldos_extrato(path: Path, conta_id: int) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute("SELECT dt, saldo FROM ext_saldo WHERE conta_id=? ORDER BY dt",
                         (conta_id,)).fetchall()
    return [dict(r) for r in rows]


def lancamentos(path: Path, conta_id: int, dt_de: str, dt_ate: str) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute(
            "SELECT dt, valor, tipo, historico, numerodoc FROM ext_lancamento "
            "WHERE conta_id=? AND dt BETWEEN ? AND ? ORDER BY dt, id", (conta_id, dt_de, dt_ate)
        ).fetchall()
    return [dict(r) for r in rows]


def listar_importacoes(path: Path = DB_PATH, limite: int = 20) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute(
            "SELECT i.*, c.rotulo AS conta_rotulo FROM ext_importacao i "
            "JOIN ext_conta c ON c.id=i.conta_id ORDER BY i.id DESC LIMIT ?", (limite,)
        ).fetchall()
    return [dict(r) for r in rows]


def apagar_importacao(path: Path, importacao_id: int) -> int:
    with _conn(path) as c:
        n = c.execute("DELETE FROM ext_lancamento WHERE importacao_id=?",
                      (importacao_id,)).rowcount
        c.execute("DELETE FROM ext_importacao WHERE id=?", (importacao_id,))
    return int(n)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/extrato/test_armazenamento.py -v`
Expected: PASS (9 testes)

- [ ] **Step 5: Commit**

```bash
git add api/extrato/__init__.py api/extrato/armazenamento.py tests/extrato/
git commit -m "feat(extrato): persistencia local em SQLite com dedup idempotente"
```

---

### Task 2: Parser OFX

**Files:**
- Create: `api/extrato/parser_ofx.py`
- Test: `tests/extrato/test_parser_ofx.py`

**Interfaces:**
- Consumes: nada da Task 1 (parser é independente do armazenamento).
- Produces: `parse_ofx(bruto: bytes) -> list[dict]` — UM extrato por bloco `<STMTRS>`
  (OFX consolidado traz mais de uma conta; misturar tudo na primeira atribuiria
  lançamento à conta errada). Cada extrato:
  `{"ident": str, "banco": int | None, "agencia": str, "conta": str, "itens": list[dict], "saldo": dict | None, "ignoradas": int}`.
  Cada item tem as chaves que `armazenamento.gravar_lancamentos` consome:
  `dt, valor, tipo, historico, numerodoc, fitid`. `saldo` é `{"dt": str, "saldo": float}` ou `None`.
  Levanta `ValueError` com mensagem em português se o conteúdo não for OFX.

- [ ] **Step 1: Write the failing test**

Create `tests/extrato/test_parser_ofx.py`:

```python
"""Parser OFX — cobre SGML (OFX 1.x, o dos bancos BR) e XML (2.x)."""
from __future__ import annotations

import pytest

from api.extrato.parser_ofx import parse_ofx

OFX_SGML = """OFXHEADER:100
DATA:OFXSGML
CHARSET:1252

<OFX>
<BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>341
<BRANCHID>0098
<ACCTID>539349
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260701
<DTEND>20260731
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260702120000[-03:EBT]
<TRNAMT>15000.50
<FITID>202607020001
<CHECKNUM>998877
<MEMO>TED RECEBIDA TUPY
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260703
<TRNAMT>-2340.75
<FITID>202607030002
<MEMO>PAGAMENTO FORNECEDOR
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>123456.78
<DTASOF>20260731
</LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""

OFX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<BANKACCTFROM><BANKID>237</BANKID><BRANCHID>36455</BRANCHID>
<ACCTID>1239066</ACCTID></BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260710</DTPOSTED>
<TRNAMT>-99.90</TRNAMT><FITID>X1</FITID><MEMO>TARIFA</MEMO></STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>500.00</BALAMT><DTASOF>20260710</DTASOF></LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""


def test_parse_sgml_extrai_conta_lancamentos_e_saldo():
    d = parse_ofx(OFX_SGML.encode("cp1252"))
    assert (d["banco"], d["agencia"], d["conta"]) == (341, "0098", "539349")
    assert d["ident"] == "341/0098/539349"
    assert len(d["itens"]) == 2
    credito, debito = d["itens"]
    assert credito["dt"] == "2026-07-02"
    assert credito["valor"] == 15000.50
    assert credito["tipo"] == "C"
    assert credito["fitid"] == "202607020001"
    assert credito["numerodoc"] == "998877"
    assert credito["historico"] == "TED RECEBIDA TUPY"
    assert debito["valor"] == -2340.75
    assert debito["tipo"] == "D"
    assert d["saldo"] == {"dt": "2026-07-31", "saldo": 123456.78}


def test_parse_xml_ofx2():
    d = parse_ofx(OFX_XML.encode("utf-8"))
    assert (d["banco"], d["agencia"], d["conta"]) == (237, "36455", "1239066")
    assert d["itens"][0]["valor"] == -99.90
    assert d["itens"][0]["tipo"] == "D"
    assert d["saldo"]["saldo"] == 500.00


def test_acentuacao_latin1_preservada():
    bruto = OFX_SGML.replace("TED RECEBIDA TUPY", "TRANSFERENCIA DEVOLUCAO JUROS")
    d = parse_ofx(bruto.encode("cp1252"))
    assert "DEVOLUCAO" in d["itens"][0]["historico"]


def test_conteudo_nao_ofx_levanta_valueerror():
    with pytest.raises(ValueError, match="OFX"):
        parse_ofx(b"data;valor;historico\n01/07/2026;10,00;TED\n")


def test_lancamento_sem_valor_e_ignorado_e_contado():
    ruim = OFX_SGML.replace("<TRNAMT>-2340.75", "<TRNAMT>")
    d = parse_ofx(ruim.encode("cp1252"))
    assert len(d["itens"]) == 1
    assert d["ignoradas"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/extrato/test_parser_ofx.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.extrato.parser_ofx'`

- [ ] **Step 3: Write minimal implementation**

Create `api/extrato/parser_ofx.py`:

```python
"""Parser de OFX (Open Financial Exchange) — formato padrão dos internet
bankings brasileiros.

Cobre as duas variantes com um único caminho: OFX 1.x é SGML (tags sem
fechamento: `<TRNAMT>10.50` até o fim da linha) e 2.x é XML bem-formado. Uma
regex por tag atende os dois, o que evita depender de parser XML (que quebraria
no SGML) ou de biblioteca externa.

Encoding: OFX de banco BR costuma vir em cp1252/latin-1, não utf-8.
"""
from __future__ import annotations

import re

_TAG = r"<{t}>\s*([^<\r\n]*)"


def _decodificar(bruto: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1", errors="replace")


def _campo(bloco: str, tag: str) -> str:
    m = re.search(_TAG.format(t=tag), bloco, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _data(cru: str) -> str | None:
    """OFX grava YYYYMMDD, opcionalmente com hora e fuso ('20260702120000[-03:EBT]')."""
    m = re.match(r"\s*(\d{4})(\d{2})(\d{2})", cru or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _valor(cru: str) -> float | None:
    """TRNAMT é ponto-decimal (padrão OFX). Alguns bancos mandam vírgula."""
    txt = (cru or "").strip().replace(" ", "")
    if not txt:
        return None
    if "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt:
        txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def parse_ofx(bruto: bytes) -> dict:
    texto = _decodificar(bruto)
    if "<OFX" not in texto.upper():
        raise ValueError("Arquivo não parece ser um OFX (tag <OFX> não encontrada).")

    banco_cru = _campo(texto, "BANKID")
    agencia = _campo(texto, "BRANCHID")
    conta = _campo(texto, "ACCTID")
    try:
        banco = int(banco_cru) if banco_cru else None
    except ValueError:
        banco = None

    itens: list[dict] = []
    ignoradas = 0
    for bloco in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", texto, re.IGNORECASE | re.DOTALL):
        dt = _data(_campo(bloco, "DTPOSTED"))
        valor = _valor(_campo(bloco, "TRNAMT"))
        if dt is None or valor is None:
            ignoradas += 1
            continue
        # o sinal do TRNAMT é a fonte da verdade; TRNTYPE só confirma
        tipo = "C" if valor >= 0 else "D"
        itens.append({
            "dt": dt, "valor": valor, "tipo": tipo,
            "historico": _campo(bloco, "MEMO") or _campo(bloco, "NAME"),
            "numerodoc": _campo(bloco, "CHECKNUM"),
            "fitid": _campo(bloco, "FITID") or None,
        })

    saldo = None
    m = re.search(r"<LEDGERBAL>(.*?)</LEDGERBAL>", texto, re.IGNORECASE | re.DOTALL)
    if m:
        s_valor = _valor(_campo(m.group(1), "BALAMT"))
        s_dt = _data(_campo(m.group(1), "DTASOF"))
        if s_valor is not None and s_dt:
            saldo = {"dt": s_dt, "saldo": s_valor}

    if not itens and saldo is None:
        raise ValueError("OFX sem lançamentos nem saldo legíveis.")

    ident = "/".join([banco_cru or "?", agencia or "?", conta or "?"])
    return {"ident": ident, "banco": banco, "agencia": agencia, "conta": conta,
            "itens": itens, "saldo": saldo, "ignoradas": ignoradas}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/extrato/test_parser_ofx.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Commit**

```bash
git add api/extrato/parser_ofx.py tests/extrato/test_parser_ofx.py
git commit -m "feat(extrato): parser OFX (SGML 1.x e XML 2.x) com encoding BR"
```

---

### Task 3: Parser CSV com mapeamento de colunas

**Files:**
- Create: `api/extrato/parser_csv.py`
- Test: `tests/extrato/test_parser_csv.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `valor_br(txt: str) -> float | None` — parse estrito de valor pt-BR.
  - `preview_csv(bruto: bytes, linhas: int = 8) -> dict` → `{"delim": str, "amostra": list[list[str]]}`
  - `parse_csv(bruto: bytes, mapa: dict) -> dict` → mesmo formato de `parse_ofx`
    (`itens`, `ignoradas`, `saldo=None`), sem as chaves de conta (CSV não traz conta).
    `mapa` = `{"dt": int, "valor": int}` **ou** `{"dt": int, "credito": int, "debito": int}`,
    com opcionais `{"historico": int, "numerodoc": int, "cabecalho": int}`
    (`cabecalho` = quantas linhas iniciais pular; default 1).
    Levanta `ValueError` se o mapa não tiver `dt` e (`valor` ou `credito`/`debito`).

- [ ] **Step 1: Write the failing test**

Create `tests/extrato/test_parser_csv.py`:

```python
"""Parser CSV genérico com mapa de colunas por conta."""
from __future__ import annotations

import pytest

from api.extrato.parser_csv import parse_csv, preview_csv, valor_br

CSV_VALOR_UNICO = (
    "Data;Historico;Documento;Valor\n"
    "01/07/2026;TED RECEBIDA TUPY;998877;15.000,50\n"
    "03/07/2026;PAGAMENTO FORNECEDOR;;-2.340,75\n"
    "SALDO FINAL;;;123.456,78\n"
)

CSV_CRED_DEB = (
    "Data;Historico;Credito;Debito\n"
    "10/07/2026;DEPOSITO;1.200,00;\n"
    "11/07/2026;TARIFA;;99,90\n"
)


def test_valor_br_formatos():
    assert valor_br("15.000,50") == 15000.50
    assert valor_br("-2.340,75") == -2340.75
    assert valor_br("1.234") == 1234.00      # ponto em grupo de 3 = milhar
    assert valor_br("99,90") == 99.90
    assert valor_br("1234.56") == 1234.56    # ponto decimal (export en-US)
    assert valor_br("R$ 1.000,00") == 1000.00
    assert valor_br("") is None
    assert valor_br("abc") is None
    assert valor_br("1.2.3.4") is None       # não é milhar nem decimal válido


def test_preview_detecta_delimitador_e_amostra():
    p = preview_csv(CSV_VALOR_UNICO.encode("utf-8"))
    assert p["delim"] == ";"
    assert p["amostra"][0] == ["Data", "Historico", "Documento", "Valor"]
    assert len(p["amostra"]) == 4


def test_parse_coluna_valor_unica():
    d = parse_csv(CSV_VALOR_UNICO.encode("utf-8"),
                  {"dt": 0, "historico": 1, "numerodoc": 2, "valor": 3})
    assert len(d["itens"]) == 2
    assert d["itens"][0] == {"dt": "2026-07-01", "valor": 15000.50, "tipo": "C",
                             "historico": "TED RECEBIDA TUPY", "numerodoc": "998877",
                             "fitid": None}
    assert d["itens"][1]["valor"] == -2340.75
    assert d["itens"][1]["tipo"] == "D"
    assert d["ignoradas"] == 1          # a linha "SALDO FINAL" não tem data


def test_parse_colunas_credito_debito_separadas():
    # débito vem positivo na coluna e tem de sair NEGATIVO no lançamento
    d = parse_csv(CSV_CRED_DEB.encode("utf-8"),
                  {"dt": 0, "historico": 1, "credito": 2, "debito": 3, "cabecalho": 1})
    assert [i["tipo"] for i in d["itens"]] == ["C", "D"]
    assert d["itens"][0]["valor"] == 1200.00
    assert d["itens"][1]["valor"] == -99.90


def test_mapa_incompleto_levanta_valueerror():
    with pytest.raises(ValueError, match="coluna"):
        parse_csv(CSV_VALOR_UNICO.encode("utf-8"), {"historico": 1})


def test_encoding_latin1():
    bruto = "Data;Historico;Valor\n01/07/2026;TARIFA MANUTENCAO;-10,00\n".encode("latin-1")
    d = parse_csv(bruto, {"dt": 0, "historico": 1, "valor": 2})
    assert d["itens"][0]["historico"] == "TARIFA MANUTENCAO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/extrato/test_parser_csv.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.extrato.parser_csv'`

- [ ] **Step 3: Write minimal implementation**

Create `api/extrato/parser_csv.py`:

```python
"""Parser de extrato em CSV, com mapa de colunas por conta.

Cada banco exporta um layout diferente, então não há detecção automática de
colunas: no primeiro upload de uma conta o usuário aponta na tela qual coluna é
data/valor/histórico e o mapa fica salvo (`ext_conta.mapa_csv`).

Valor em formato BR exige parse ESTRITO: `parseFloat`/`float()` aceitam prefixo
válido e ignoram o resto ('1.234.56' viraria 1.234), e `type=number` no front
descarta a vírgula. Aqui a regex valida ANTES de converter.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date

_RE_MILHAR_VIRGULA = re.compile(r"^-?\d{1,3}(\.\d{3})*(,\d{1,2})?$")   # 1.234.567,89
_RE_SO_VIRGULA = re.compile(r"^-?\d+(,\d{1,2})?$")                     # 1234,89
_RE_PONTO_DEC = re.compile(r"^-?\d+(\.\d{1,2})?$")                     # 1234.89
_RE_MILHAR_PONTO = re.compile(r"^-?\d{1,3}(\.\d{3})+$")                # 1.234 (milhar)


def valor_br(txt: str) -> float | None:
    """Converte valor pt-BR (ou en-US simples) para float. None se inválido."""
    s = (txt or "").strip()
    if not s:
        return None
    s = s.replace("R$", "").replace(" ", "").replace("\xa0", "")
    negativo = s.startswith("(") and s.endswith(")")   # (1.234,56) = negativo
    if negativo:
        s = s[1:-1]
    if not s:
        return None
    if _RE_MILHAR_PONTO.match(s):          # 1.234 -> milhar, não decimal
        val = float(s.replace(".", ""))
    elif _RE_MILHAR_VIRGULA.match(s):
        val = float(s.replace(".", "").replace(",", "."))
    elif _RE_SO_VIRGULA.match(s):
        val = float(s.replace(",", "."))
    elif _RE_PONTO_DEC.match(s):
        val = float(s)
    else:
        return None
    return -val if negativo else val


def _decodificar(bruto: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1", errors="replace")


def _delimitador(texto: str) -> str:
    """Escolhe pela ESTRUTURA que o candidato produz, nao por contagem de
    caracteres: extrato BR usa ';' e tem virgula decimal e virgula dentro de
    campo entre aspas ("PGTO FORNEC, LTDA"), o que fazia a contagem crua eleger
    ',' e despedacar as colunas. `csv.reader` respeita aspas.
    """
    cabeca = texto.splitlines()[:5]
    melhor, melhor_nota = ";", (0, 0)
    for cand in (";", ",", "\t"):
        linhas = [r for r in csv.reader(io.StringIO("\n".join(cabeca)), delimiter=cand) if r]
        if not linhas:
            continue
        cols = [len(r) for r in linhas]
        if max(cols) < 2:
            continue                      # nao separou nada
        estavel = 1 if len(set(cols)) == 1 else 0
        nota = (estavel, max(cols))       # consistencia primeiro, largura depois
        if nota > melhor_nota:
            melhor, melhor_nota = cand, nota
    return melhor


def _data_br(txt: str) -> str | None:
    """DD/MM/AAAA (ou com '-'), e AAAA-MM-DD para exports ISO.

    Valida o CALENDARIO, nao so o formato: '31/13/2026' passaria pela regex e
    viraria um lancamento num dia inexistente, que nunca casa com nenhum dia do
    ERP e desaparece da comparacao sem aviso - escondendo divergencia real.
    """
    s = (txt or "").strip()
    m = re.match(r"^(\d{2})[/-](\d{2})[/-](\d{4})", s)
    if m:
        ano, mes, dia = m.group(3), m.group(2), m.group(1)
    else:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
        if not m:
            return None
        ano, mes, dia = m.group(1), m.group(2), m.group(3)
    try:
        return date(int(ano), int(mes), int(dia)).isoformat()
    except ValueError:
        return None


def _linhas(bruto: bytes) -> tuple[list[list[str]], str]:
    texto = _decodificar(bruto)
    delim = _delimitador(texto)
    return [r for r in csv.reader(io.StringIO(texto), delimiter=delim) if r], delim


def preview_csv(bruto: bytes, linhas: int = 8) -> dict:
    todas, delim = _linhas(bruto)
    return {"delim": delim, "amostra": todas[:linhas]}


def _col(linha: list[str], idx) -> str:
    if idx is None or idx < 0 or idx >= len(linha):
        return ""
    return (linha[idx] or "").strip()


def parse_csv(bruto: bytes, mapa: dict) -> dict:
    tem_valor = mapa.get("valor") is not None
    tem_cd = mapa.get("credito") is not None or mapa.get("debito") is not None
    if mapa.get("dt") is None or not (tem_valor or tem_cd):
        raise ValueError("Mapa de colunas incompleto: informe a coluna de data e "
                         "a de valor (ou as de crédito e débito).")

    todas, _ = _linhas(bruto)
    pular = int(mapa.get("cabecalho", 1) or 0)
    itens: list[dict] = []
    ignoradas = 0
    for linha in todas[pular:]:
        dt = _data_br(_col(linha, mapa.get("dt")))
        if dt is None:
            ignoradas += 1          # cabeçalho repetido, rodapé, linha de saldo
            continue
        if tem_valor:
            valor = valor_br(_col(linha, mapa.get("valor")))
        else:
            cred = valor_br(_col(linha, mapa.get("credito")))
            deb = valor_br(_col(linha, mapa.get("debito")))
            # `is not None`, nunca truthiness: credito legitimo de 0,00 e falsy
            # e desapareceria da trilha. Ambos preenchidos = liquido da linha.
            if cred is not None and deb is not None:
                valor = cred - abs(deb)
            elif cred is not None:
                valor = cred
            elif deb is not None:
                valor = -abs(deb)
            else:
                valor = None
        if valor is None:
            ignoradas += 1
            continue
        itens.append({
            "dt": dt, "valor": valor, "tipo": "C" if valor >= 0 else "D",
            "historico": _col(linha, mapa.get("historico")),
            "numerodoc": _col(linha, mapa.get("numerodoc")),
            "fitid": None,
        })
    if not itens:
        raise ValueError("Nenhuma linha do CSV foi reconhecida com o mapa de colunas atual.")
    return {"itens": itens, "saldo": None, "ignoradas": ignoradas}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/extrato/test_parser_csv.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add api/extrato/parser_csv.py tests/extrato/test_parser_csv.py
git commit -m "feat(extrato): parser CSV com mapa de colunas e parse estrito pt-BR"
```

---

### Task 4: Comparação conta×dia (função pura)

**Files:**
- Create: `api/extrato/comparacao.py`
- Test: `tests/extrato/test_comparacao.py`

**Interfaces:**
- Consumes: formato dos lançamentos de `armazenamento.lancamentos` (`dt`, `valor`, `tipo`) e dos saldos de `armazenamento.saldos_extrato` (`dt`, `saldo`).
- Produces:
  - `TOLERANCIA: float = 0.01`
  - `agregar_extrato(lancs: list[dict]) -> dict[str, dict]` — por data: `{"credito", "debito", "liquido", "qtd"}` (débito positivo em módulo).
  - `saldo_derivado(por_dia: dict, saldos: list[dict]) -> dict[str, float | None]` — saldo por dia ancorado no LEDGERBAL mais recente; `{}` se não houver âncora.
  - `comparar(lancs, saldos, erp_rows) -> list[dict]` — uma linha por data presente em qualquer dos lados, ordenada, com
    `{"dt", "ext_credito", "ext_debito", "ext_saldo", "erp_credito", "erp_debito", "erp_saldo", "d_credito", "d_debito", "d_saldo", "estado", "qtd"}`.
    `estado` ∈ `OK | DIVERGE | SO_EXTRATO | SO_ERP`. `erp_rows` = linhas de `contacorrente_saldo` com `dt`, `credito`, `debito`, `saldo`.
  - `farol(dias: list[dict], ultimo_upload: str | None, hoje: str, mapeada: bool = True) -> dict` —
    `{"estado": "ok"|"diverge"|"sem_mapa"|"desatualizado", "dt": str | None, "delta": float | None, "dias_sem_extrato": int | None}`.

- [ ] **Step 1: Write the failing test**

Create `tests/extrato/test_comparacao.py`:

```python
"""Comparação extrato x ERP — função pura, sem banco."""
from __future__ import annotations

from api.extrato.comparacao import (agregar_extrato, comparar, farol, saldo_derivado)


def _l(dt, valor):
    return {"dt": dt, "valor": valor, "tipo": "C" if valor >= 0 else "D"}


def _erp(dt, credito, debito, saldo):
    return {"dt": dt, "credito": credito, "debito": debito, "saldo": saldo}


def test_agregar_separa_credito_e_debito_por_dia():
    por_dia = agregar_extrato([_l("2026-07-01", 100.0), _l("2026-07-01", -30.0),
                               _l("2026-07-02", -5.0)])
    assert por_dia["2026-07-01"] == {"credito": 100.0, "debito": 30.0,
                                     "liquido": 70.0, "qtd": 2}
    assert por_dia["2026-07-02"]["debito"] == 5.0


def test_saldo_derivado_da_ancora_para_tras_e_para_frente():
    por_dia = agregar_extrato([_l("2026-07-01", 100.0), _l("2026-07-02", -40.0)])
    # ancora: saldo 1.060 ao fim de 02/07 -> fim de 01/07 = 1.100
    d = saldo_derivado(por_dia, [{"dt": "2026-07-02", "saldo": 1060.0}])
    assert round(d["2026-07-02"], 2) == 1060.00
    assert round(d["2026-07-01"], 2) == 1100.00


def test_saldo_derivado_sem_ancora_e_vazio():
    por_dia = agregar_extrato([_l("2026-07-01", 100.0)])
    assert saldo_derivado(por_dia, []) == {}


def test_dia_que_bate_ao_centavo_e_ok():
    dias = comparar([_l("2026-07-01", 100.0), _l("2026-07-01", -30.0)],
                    [{"dt": "2026-07-01", "saldo": 70.0}],
                    [_erp("2026-07-01", 100.0, 30.0, 70.0)])
    assert len(dias) == 1
    assert dias[0]["estado"] == "OK"
    assert dias[0]["d_saldo"] == 0.0


def test_diferenca_de_um_centavo_ainda_e_ok():
    dias = comparar([_l("2026-07-01", 100.0)], [{"dt": "2026-07-01", "saldo": 100.0}],
                    [_erp("2026-07-01", 100.01, 0.0, 100.0)])
    assert dias[0]["estado"] == "OK"


def test_divergencia_de_credito_marca_diverge_com_delta():
    dias = comparar([_l("2026-07-01", 100.0)], [{"dt": "2026-07-01", "saldo": 100.0}],
                    [_erp("2026-07-01", 90.0, 0.0, 100.0)])
    assert dias[0]["estado"] == "DIVERGE"
    assert round(dias[0]["d_credito"], 2) == 10.0


def test_divergencia_de_saldo_marca_diverge():
    dias = comparar([_l("2026-07-01", 100.0)], [{"dt": "2026-07-01", "saldo": 100.0}],
                    [_erp("2026-07-01", 100.0, 0.0, 95.0)])
    assert dias[0]["estado"] == "DIVERGE"
    assert round(dias[0]["d_saldo"], 2) == 5.0


def test_dia_so_no_extrato_e_so_no_erp():
    dias = comparar([_l("2026-07-01", 100.0)], [],
                    [_erp("2026-07-02", 50.0, 0.0, 150.0)])
    estados = {d["dt"]: d["estado"] for d in dias}
    assert estados == {"2026-07-01": "SO_EXTRATO", "2026-07-02": "SO_ERP"}


def test_sem_ancora_de_saldo_compara_so_fluxo():
    dias = comparar([_l("2026-07-01", 100.0)], [],
                    [_erp("2026-07-01", 100.0, 0.0, 999.0)])
    assert dias[0]["ext_saldo"] is None
    assert dias[0]["d_saldo"] is None
    assert dias[0]["estado"] == "OK"       # fluxo bate; saldo não é comparável


def test_farol_ok_diverge_sem_mapa_e_desatualizado():
    ok = [{"dt": "2026-07-31", "estado": "OK", "d_saldo": 0.0}]
    assert farol(ok, "2026-07-31", "2026-08-01")["estado"] == "ok"
    div = [{"dt": "2026-07-31", "estado": "DIVERGE", "d_saldo": -12.5}]
    f = farol(div, "2026-07-31", "2026-08-01")
    assert (f["estado"], f["delta"]) == ("diverge", -12.5)
    assert farol(ok, "2026-07-31", "2026-08-01", mapeada=False)["estado"] == "sem_mapa"
    # ultimo upload ha mais de 7 dias
    velho = farol(ok, "2026-07-20", "2026-08-01")
    assert velho["estado"] == "desatualizado"
    assert velho["dias_sem_extrato"] == 12


def test_farol_sem_nenhum_dia():
    f = farol([], None, "2026-08-01")
    assert f["estado"] == "desatualizado"
    assert f["dt"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/extrato/test_comparacao.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.extrato.comparacao'`

- [ ] **Step 3: Write minimal implementation**

Create `api/extrato/comparacao.py`:

```python
"""Cruzamento do extrato importado com o `contacorrente_saldo` do ERP.

Função pura: recebe as duas listas e devolve a comparação por conta x dia. Isso
mantém o cálculo testável sem AVA e sem SQLite.

Saldo: o extrato traz o saldo final (LEDGERBAL) numa data só, então o saldo dos
demais dias é DERIVADO a partir dessa âncora, somando/subtraindo o líquido de
cada dia. Sem âncora, `ext_saldo` fica None e o dia é julgado só pelo fluxo -
dizer "saldo divergente" sem ter saldo do banco seria falso positivo.
"""
from __future__ import annotations

from datetime import date

TOLERANCIA = 0.01


def agregar_extrato(lancs: list[dict]) -> dict[str, dict]:
    por_dia: dict[str, dict] = {}
    for l in lancs:
        d = por_dia.setdefault(l["dt"], {"credito": 0.0, "debito": 0.0,
                                         "liquido": 0.0, "qtd": 0})
        valor = float(l["valor"])
        if valor >= 0:
            d["credito"] += valor
        else:
            d["debito"] += -valor
        d["liquido"] += valor
        d["qtd"] += 1
    return por_dia


def saldo_derivado(por_dia: dict[str, dict], saldos: list[dict]) -> dict[str, float | None]:
    if not saldos:
        return {}
    ancora = max(saldos, key=lambda s: s["dt"])
    datas = sorted(set(por_dia) | {ancora["dt"]})
    out: dict[str, float | None] = {ancora["dt"]: float(ancora["saldo"])}
    # para trás: saldo do dia anterior = saldo do dia - liquido do dia
    i = datas.index(ancora["dt"])
    for k in range(i, 0, -1):
        liq = por_dia.get(datas[k], {}).get("liquido", 0.0)
        out[datas[k - 1]] = out[datas[k]] - liq
    # para frente: saldo do dia = saldo anterior + liquido do dia
    for k in range(i + 1, len(datas)):
        liq = por_dia.get(datas[k], {}).get("liquido", 0.0)
        out[datas[k]] = out[datas[k - 1]] + liq
    return out


def _difere(a: float | None, b: float | None) -> bool:
    """Tolerancia INCLUSIVA de um centavo. O round e obrigatorio: 100.01 nao tem
    representacao binaria exata e `abs(100.0 - 100.01)` vale 0.010000000000005,
    que passaria do limite e marcaria DIVERGE justo no caso de 1 centavo."""
    if a is None or b is None:
        return False
    return round(abs(a - b), 2) > TOLERANCIA


def comparar(lancs: list[dict], saldos: list[dict], erp_rows: list[dict]) -> list[dict]:
    por_dia = agregar_extrato(lancs)
    saldo_ext = saldo_derivado(por_dia, saldos)
    erp = {r["dt"]: r for r in erp_rows}
    out: list[dict] = []
    # inclui as datas que so existem no SALDO: ancora sem lancamento e sem linha
    # no ERP e um saldo do banco que o ERP nao registrou (SO_EXTRATO), e some da
    # saida se o dominio for so lancamento + ERP.
    for dt in sorted(set(por_dia) | set(erp) | set(saldo_ext)):
        e = por_dia.get(dt)
        r = erp.get(dt)
        ext_c = e["credito"] if e else None
        ext_d = e["debito"] if e else None
        ext_s = saldo_ext.get(dt)
        erp_c = float(r["credito"]) if r and r.get("credito") is not None else None
        erp_d = float(r["debito"]) if r and r.get("debito") is not None else None
        erp_s = float(r["saldo"]) if r and r.get("saldo") is not None else None
        # "tem extrato" inclui o dia que so tem SALDO derivado e nenhum
        # lancamento: e exatamente o dia da ancora do LEDGERBAL quando nao houve
        # movimento. Decidir por `e is None` marcava esse dia como SO_ERP e o
        # farol descartava a divergencia de saldo ja calculada - mostrando "ok"
        # no dia do fechamento do extrato, o pior modo de falha desta tela.
        tem_ext = e is not None or ext_s is not None
        if not tem_ext:
            estado = "SO_ERP"
        elif r is None:
            estado = "SO_EXTRATO"
        elif _difere(ext_c, erp_c) or _difere(ext_d, erp_d) or _difere(ext_s, erp_s):
            estado = "DIVERGE"
        else:
            estado = "OK"
        out.append({
            "dt": dt, "estado": estado, "qtd": (e["qtd"] if e else 0),
            "ext_credito": ext_c, "ext_debito": ext_d, "ext_saldo": ext_s,
            "erp_credito": erp_c, "erp_debito": erp_d, "erp_saldo": erp_s,
            "d_credito": (ext_c - erp_c) if not (ext_c is None or erp_c is None) else None,
            "d_debito": (ext_d - erp_d) if not (ext_d is None or erp_d is None) else None,
            "d_saldo": (ext_s - erp_s) if not (ext_s is None or erp_s is None) else None,
        })
    return out


def _dias_entre(de: str, ate: str) -> int:
    return (date.fromisoformat(ate) - date.fromisoformat(de)).days


def farol(dias: list[dict], ultimo_upload: str | None, hoje: str,
          mapeada: bool = True) -> dict:
    """Estado da conta = o último dia coberto pelo extrato.

    Ordem de precedência: sem mapeamento ERP (não há o que comparar) > extrato
    velho (o verde de 12 dias atrás não diz nada sobre hoje) > divergência.
    """
    validos = [d for d in dias if d["estado"] in ("OK", "DIVERGE")]
    ultimo = max(validos, key=lambda d: d["dt"]) if validos else None
    dias_sem = _dias_entre(ultimo_upload, hoje) if ultimo_upload else None
    if not mapeada:
        return {"estado": "sem_mapa", "dt": (ultimo or {}).get("dt"),
                "delta": None, "dias_sem_extrato": dias_sem}
    if ultimo is None or dias_sem is None or dias_sem > 7:
        return {"estado": "desatualizado", "dt": (ultimo or {}).get("dt"),
                "delta": (ultimo or {}).get("d_saldo"), "dias_sem_extrato": dias_sem}
    if ultimo["estado"] == "DIVERGE":
        return {"estado": "diverge", "dt": ultimo["dt"],
                "delta": ultimo.get("d_saldo"), "dias_sem_extrato": dias_sem}
    return {"estado": "ok", "dt": ultimo["dt"], "delta": ultimo.get("d_saldo"),
            "dias_sem_extrato": dias_sem}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/extrato/test_comparacao.py -v`
Expected: PASS (11 testes)

- [ ] **Step 5: Commit**

```bash
git add api/extrato/comparacao.py tests/extrato/test_comparacao.py
git commit -m "feat(extrato): comparacao conta x dia extrato vs contacorrente_saldo"
```

---

### Task 5: Serviço (orquestra importação e painel)

**Files:**
- Create: `api/extrato/servico.py`
- Test: `tests/extrato/test_servico.py`

**Interfaces:**
- Consumes: `armazenamento` (Task 1), `parser_ofx.parse_ofx` (Task 2), `parser_csv.parse_csv`/`preview_csv` (Task 3), `comparacao.comparar`/`farol` (Task 4), `api.db.query` (leitura do AVA).
- Produces:
  - `ERP_SALDO_SQL: str` — consulta de `contacorrente_saldo` por conta e período.
  - `importar(bruto: bytes, nome: str, path=DB_PATH, conta_id: int | None = None) -> dict`
    — devolve `{"ok": True, "conta_id", "conta", "novas", "duplicadas", "ignoradas", "dt_de", "dt_ate"}`,
    ou `{"ok": False, "precisa": "conta_csv"|"mapa_csv"|"mapa_erp", ...}`, ou levanta
    `ValueError` (arquivo ilegível). **CSV exige `conta_id`**: o arquivo não traz a
    conta, então derivar identidade do NOME do arquivo fazia dois `extrato.csv` de
    bancos diferentes virarem a mesma conta e misturar lançamentos. Sem `conta_id`
    devolve `precisa="conta_csv"` com `preview` e as contas conhecidas, sem gravar
    nada. OFX não muda (a conta está no arquivo) e ganha `pendentes` = quantas
    contas do arquivo ainda precisam de vínculo ERP.
  - `ident_csv(erp_banco: int, erp_agencia: str, erp_conta: str) -> str` —
    `"csv:<banco>/<agencia>/<conta>"`. A identidade de conta CSV é a conta bancária
    real, nunca o nome do arquivo.
  - `painel(dt_de: str, dt_ate: str, conta_id: int | None = None, path=DB_PATH) -> dict` —
    `{"kpis", "contas", "dias", "importacoes", "atualizado_em", "fonte"}`.
  - `contas_erp() -> list[dict]` — contas de `contacorrente_saldo` para o select de mapeamento.

- [ ] **Step 1: Write the failing test**

Create `tests/extrato/test_servico.py`:

```python
"""Serviço do extrato: importação ponta a ponta (SQLite real, AVA mockado)."""
from __future__ import annotations

import pytest

from api.extrato import armazenamento as arm
from api.extrato import servico
from tests.extrato.test_parser_ofx import OFX_SGML


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "extrato.db"
    arm.init_db(p)
    return p


def test_importar_ofx_conta_nova_pede_mapeamento(db):
    r = servico.importar(OFX_SGML.encode("cp1252"), "itau.ofx", path=db)
    assert r["ok"] is False
    assert r["precisa"] == "mapa_erp"
    assert r["conta"]["ident"] == "341/0098/539349"
    # os lançamentos JÁ ficam gravados — o mapeamento é só o vínculo com o ERP
    assert r["novas"] == 2
    assert len(r["contas"]) == 1        # um extrato por conta no arquivo


def test_importar_ofx_conta_mapeada_grava_e_reimport_nao_duplica(db):
    r1 = servico.importar(OFX_SGML.encode("cp1252"), "itau.ofx", path=db)
    arm.mapear_conta(db, r1["conta_id"], 341, "0098", "539349")
    r2 = servico.importar(OFX_SGML.encode("cp1252"), "itau.ofx", path=db)
    assert r2["ok"] is True
    assert (r2["novas"], r2["duplicadas"]) == (0, 2)
    assert r2["dt_de"] == "2026-07-02" and r2["dt_ate"] == "2026-07-03"
    # o saldo do LEDGERBAL entrou
    assert arm.saldos_extrato(db, r1["conta_id"]) == [{"dt": "2026-07-31", "saldo": 123456.78}]


def test_importar_csv_sem_mapa_pede_mapa_csv(db):
    bruto = b"Data;Historico;Valor\n01/07/2026;TED;10,00\n"
    r = servico.importar(bruto, "banco.csv", path=db)
    assert r["ok"] is False
    assert r["precisa"] == "mapa_csv"
    assert r["preview"]["amostra"][0] == ["Data", "Historico", "Valor"]


def test_importar_csv_com_mapa_salvo(db):
    bruto = b"Data;Historico;Valor\n01/07/2026;TED;10,00\n"
    r = servico.importar(bruto, "banco.csv", path=db)
    cid = r["conta_id"]
    arm.salvar_mapa_csv(db, cid, {"dt": 0, "historico": 1, "valor": 2})
    arm.mapear_conta(db, cid, 341, "0098", "539349")
    r2 = servico.importar(bruto, "banco.csv", path=db)
    assert r2["ok"] is True and r2["novas"] == 1


def test_importar_arquivo_ilegivel_levanta_valueerror(db):
    with pytest.raises(ValueError):
        servico.importar(b"\x00\x01 nao sou extrato", "x.ofx", path=db)


def test_painel_cruza_com_erp_mockado(db, monkeypatch):
    r = servico.importar(OFX_SGML.encode("cp1252"), "itau.ofx", path=db)
    arm.mapear_conta(db, r["conta_id"], 341, "0098", "539349")

    def fake_query(sql, params=None):
        return [{"dt": "2026-07-02", "credito": 15000.50, "debito": 0.0, "saldo": 15000.50},
                {"dt": "2026-07-03", "credito": 0.0, "debito": 2340.75, "saldo": 12659.75}]

    monkeypatch.setattr(servico.db, "query", fake_query)
    d = servico.painel("2026-07-01", "2026-07-31", path=db)
    assert d["kpis"]["contas"] == 1
    assert d["kpis"]["dias_validados"] == 2
    assert len(d["contas"]) == 1
    assert d["contas"][0]["farol"]["estado"] in ("ok", "diverge", "desatualizado")
    dias = {x["dt"]: x for x in d["dias"]}
    assert dias["2026-07-02"]["erp_credito"] == 15000.50


def test_painel_sem_conta_nenhuma_nao_quebra(db, monkeypatch):
    monkeypatch.setattr(servico.db, "query", lambda sql, params=None: [])
    d = servico.painel("2026-07-01", "2026-07-31", path=db)
    assert d["kpis"]["contas"] == 0
    assert d["dias"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/extrato/test_servico.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.extrato.servico'`

- [ ] **Step 3: Write minimal implementation**

Create `api/extrato/servico.py`:

```python
"""Orquestra a importação de extrato e monta o painel de validação.

Importação: parse -> grava (dedup) -> devolve resultado. Conta cujo vínculo com
o ERP ainda não existe grava os lançamentos e volta pedindo o mapeamento; não
perder o upload evita o usuário subir o arquivo duas vezes.

Painel: para cada conta mapeada, lê `contacorrente_saldo` (lado ERP) e cruza com
o extrato local pela função pura de `comparacao`.
"""
from __future__ import annotations

from datetime import date, datetime

from api import db
from api.extrato import armazenamento as arm
from api.extrato import comparacao as cmp
from api.extrato.parser_csv import parse_csv, preview_csv
from api.extrato.parser_ofx import parse_ofx

# Lado ERP da comparação. Uma linha por dia da conta; `valorsaldo` é a posição
# de fechamento do dia. Sem `—` na string (o banco é LATIN-1).
ERP_SALDO_SQL = """
SELECT dtmovimento::date AS dt,
       coalesce(valorcredito,0)::float8 AS credito,
       coalesce(valordebito,0)::float8  AS debito,
       coalesce(valorsaldo,0)::float8   AS saldo
FROM contacorrente_saldo
WHERE banco = %(banco)s AND agencia = %(agencia)s AND conta = %(conta)s
  AND dtmovimento BETWEEN %(dt_de)s AND %(dt_ate)s
ORDER BY dtmovimento
"""

# Contas que o ERP movimenta, para o select de mapeamento. Só as com movimento
# recente: a lista completa traz contas encerradas anos atrás.
ERP_CONTAS_SQL = """
SELECT banco, agencia, conta,
       max(dtmovimento)::date AS ultimo_movimento,
       count(*)::int AS dias
FROM contacorrente_saldo
WHERE dtmovimento >= current_date - 400
GROUP BY 1,2,3
ORDER BY max(dtmovimento) DESC, banco
"""


def _formato(nome: str) -> str:
    return "ofx" if nome.lower().endswith((".ofx", ".qfx")) else "csv"


def _erp_dias(conta: dict, dt_de: str, dt_ate: str) -> list[dict]:
    if conta.get("erp_banco") is None:
        return []
    rows = db.query(ERP_SALDO_SQL, {
        "banco": conta["erp_banco"], "agencia": conta["erp_agencia"],
        "conta": conta["erp_conta"], "dt_de": dt_de, "dt_ate": dt_ate})
    return [{"dt": r["dt"].isoformat() if hasattr(r["dt"], "isoformat") else str(r["dt"]),
             "credito": r["credito"], "debito": r["debito"], "saldo": r["saldo"]}
            for r in rows]


def contas_erp() -> list[dict]:
    rows = db.query(ERP_CONTAS_SQL)
    out = []
    for r in rows:
        ultimo = r["ultimo_movimento"]
        out.append({
            "banco": r["banco"], "agencia": r["agencia"], "conta": r["conta"],
            "ultimo_movimento": ultimo.isoformat() if hasattr(ultimo, "isoformat") else str(ultimo),
            "dias": r["dias"],
            "rotulo": f"{r['banco']} / ag {r['agencia']} / cc {r['conta']}",
        })
    return out


def importar(bruto: bytes, nome: str, path=arm.DB_PATH) -> dict:
    arm.init_db(path)
    formato = _formato(nome)

    if formato == "ofx":
        # parse_ofx devolve UM extrato por conta do arquivo (export consolidado
        # traz varias). Grava todas; o resultado reporta a primeira que ainda
        # precisa de mapeamento, para a tela pedir o vinculo.
        extratos = parse_ofx(bruto)
        resultados = []
        for d in extratos:
            rotulo = f"{d['banco'] or '?'} / cc {d['conta'] or '?'}"
            conta_id = arm.obter_ou_criar_conta(path, d["ident"], rotulo)
            conta = arm.conta_por_ident(path, d["ident"])
            res = arm.gravar_lancamentos(path, conta_id, d["itens"], nome, "ofx",
                                         d["ignoradas"])
            if d["saldo"]:
                arm.gravar_saldo_extrato(path, conta_id, d["saldo"]["dt"],
                                         d["saldo"]["saldo"])
            datas = sorted(i["dt"] for i in d["itens"]) or [None]
            resultados.append({"conta_id": conta_id, "conta": conta,
                               "novas": res["novas"], "duplicadas": res["duplicadas"],
                               "ignoradas": d["ignoradas"],
                               "dt_de": datas[0], "dt_ate": datas[-1]})
        # agrega os totais do arquivo; contas = uma linha por conta encontrada
        total = {"novas": sum(r["novas"] for r in resultados),
                 "duplicadas": sum(r["duplicadas"] for r in resultados),
                 "ignoradas": sum(r["ignoradas"] for r in resultados),
                 "contas": resultados}
        datas_todas = sorted(d for r in resultados for d in (r["dt_de"], r["dt_ate"]) if d)
        primeira = resultados[0]
        base = {"conta_id": primeira["conta_id"], "conta": primeira["conta"],
                "dt_de": (datas_todas[0] if datas_todas else None),
                "dt_ate": (datas_todas[-1] if datas_todas else None), **total}
        sem_mapa = [r for r in resultados if r["conta"].get("erp_banco") is None]
        if sem_mapa:
            return {"ok": False, "precisa": "mapa_erp", **base,
                    "conta_id": sem_mapa[0]["conta_id"], "conta": sem_mapa[0]["conta"]}
        return {"ok": True, **base}

    # CSV: a conta não vem no arquivo, então o ident sai do nome do arquivo
    ident = "csv:" + nome.rsplit(".", 1)[0].strip().lower()
    conta_id = arm.obter_ou_criar_conta(path, ident, nome.rsplit(".", 1)[0])
    conta = arm.conta_por_ident(path, ident)
    if not conta.get("mapa_csv"):
        return {"ok": False, "precisa": "mapa_csv", "conta_id": conta_id, "conta": conta,
                "preview": preview_csv(bruto), "novas": 0, "duplicadas": 0, "ignoradas": 0}
    d = parse_csv(bruto, conta["mapa_csv"])
    res = arm.gravar_lancamentos(path, conta_id, d["itens"], nome, "csv", d["ignoradas"])
    datas = sorted(i["dt"] for i in d["itens"]) or [None]
    base = {"conta_id": conta_id, "conta": conta, "novas": res["novas"],
            "duplicadas": res["duplicadas"], "ignoradas": d["ignoradas"],
            "dt_de": datas[0], "dt_ate": datas[-1]}
    if conta.get("erp_banco") is None:
        return {"ok": False, "precisa": "mapa_erp", **base}
    return {"ok": True, **base}


def painel(dt_de: str, dt_ate: str, conta_id: int | None = None, path=arm.DB_PATH) -> dict:
    arm.init_db(path)
    hoje = date.today().isoformat()
    contas = arm.listar_contas(path)
    imps = arm.listar_importacoes(path)
    ult_por_conta: dict[int, str] = {}
    for i in imps:
        cid = i["conta_id"]
        if i.get("dt_ate") and (cid not in ult_por_conta or i["dt_ate"] > ult_por_conta[cid]):
            ult_por_conta[cid] = i["dt_ate"]

    resumo, dias_sel = [], []
    tot_div = tot_val = 0
    pior = None
    for c in contas:
        lancs = arm.lancamentos(path, c["id"], dt_de, dt_ate)
        saldos = arm.saldos_extrato(path, c["id"])
        dias = cmp.comparar(lancs, saldos, _erp_dias(c, dt_de, dt_ate))
        f = cmp.farol(dias, ult_por_conta.get(c["id"]), hoje,
                      mapeada=c.get("erp_banco") is not None)
        validos = [d for d in dias if d["estado"] in ("OK", "DIVERGE")]
        divergentes = [d for d in dias if d["estado"] == "DIVERGE"]
        tot_val += len(validos)
        tot_div += len(divergentes)
        for d in divergentes:
            # o maior desvio do dia e o MAIOR dos tres em modulo. A cadeia `or`
            # priorizava d_saldo mesmo sem ser a causa e usava truthiness: um
            # residuo de 0,007 no saldo vencia um d_credito de 500,00 e o KPI
            # "Maior diferenca" escondia a divergencia real.
            deltas = [abs(v) for v in (d.get("d_saldo"), d.get("d_credito"),
                                       d.get("d_debito")) if v is not None]
            delta = max(deltas) if deltas else 0.0
            if pior is None or delta > pior["delta"]:
                pior = {"delta": delta, "conta": c["rotulo"], "dt": d["dt"]}
        resumo.append({
            "conta_id": c["id"], "rotulo": c["rotulo"], "ident": c["ident"],
            "mapeada": c.get("erp_banco") is not None,
            "erp": (f"{c['erp_banco']} / ag {c['erp_agencia']} / cc {c['erp_conta']}"
                    if c.get("erp_banco") is not None else None),
            "formato_csv": bool(c.get("mapa_csv")),
            "farol": f, "dias_validados": len(validos), "dias_divergentes": len(divergentes),
            "ultimo_extrato": ult_por_conta.get(c["id"]),
        })
        if conta_id is not None and c["id"] == conta_id:
            dias_sel = dias
    # sem conta escolhida, a tabela dia a dia abre na primeira conta com dado
    if conta_id is None:
        for c in contas:
            lancs = arm.lancamentos(path, c["id"], dt_de, dt_ate)
            if lancs:
                dias_sel = cmp.comparar(lancs, arm.saldos_extrato(path, c["id"]),
                                        _erp_dias(c, dt_de, dt_ate))
                conta_id = c["id"]
                break

    return {
        "kpis": {
            "contas": len(contas),
            "contas_sem_mapa": sum(1 for r in resumo if not r["mapeada"]),
            "dias_validados": tot_val,
            "dias_divergentes": tot_div,
            "maior_diferenca": (pior or {}).get("delta"),
            "maior_diferenca_conta": (pior or {}).get("conta"),
            "maior_diferenca_dt": (pior or {}).get("dt"),
            "ultimo_upload": (imps[0]["quando"] if imps else None),
        },
        "conta_selecionada": conta_id,
        "contas": resumo,
        "dias": dias_sel,
        "importacoes": imps,
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": "extrato importado (OFX/CSV) x contacorrente_saldo do ERP AVA",
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/extrato/ -v`
Expected: PASS (todos: 9 + 5 + 6 + 11 + 7 = 38 testes)

- [ ] **Step 5: Commit**

```bash
git add api/extrato/servico.py tests/extrato/test_servico.py
git commit -m "feat(extrato): servico de importacao e painel de validacao"
```

---

### Task 6: Endpoints + RBAC

**Files:**
- Modify: `api/main.py` (endpoints novos, ao lado dos de orçamento)
- Modify: `api/auth.py` (`TELAS`, `ROTA_TELAS`, `_PERFIS_MODELO`, seed `perfis_modelo_v19`)
- Test: `tests/extrato/test_rbac_extrato.py`

**Interfaces:**
- Consumes: `servico.importar`, `servico.painel`, `servico.contas_erp`, `armazenamento.mapear_conta`, `armazenamento.salvar_mapa_csv`, `armazenamento.apagar_importacao` (Tasks 1 e 5).
- Produces (contrato consumido pelo front na Task 7):
  - `GET /api/financeiro/extrato?dt_de=&dt_ate=&conta_id=` → payload de `servico.painel`.
  - `POST /api/financeiro/extrato/importar?nome=<arquivo>&conta_id=<id>` — corpo bruto
  do arquivo. `conta_id` é opcional para OFX e OBRIGATÓRIO para CSV (sem ele a
  resposta é `precisa="conta_csv"`, que a tela usa para perguntar a conta).
  - `POST /api/financeiro/extrato/mapear` — JSON `{conta_id, erp_banco, erp_agencia,
  erp_conta, rotulo?}` e/ou `{conta_id, mapa_csv:{...}}`. Para CRIAR conta CSV (sem
  `conta_id`), aceita `{formato:"csv", erp_banco, erp_agencia, erp_conta, mapa_csv}`
  e cria a conta com `servico.ident_csv(...)` — a identidade sai da conta bancária,
  não do nome do arquivo.
  - `DELETE /api/financeiro/extrato/importacao/{imp_id}`.
  - `GET /api/financeiro/extrato/contas-erp` → `{"contas": [...]}`.

- [ ] **Step 1: Write the failing test**

Create `tests/extrato/test_rbac_extrato.py`:

```python
"""RBAC da tela extb: mapeamento de rota e ordem dos prefixos."""
from __future__ import annotations

from api import auth


def test_tela_extb_registrada_no_grupo_financeiro():
    assert auth.TELAS["extb"] == ("Extrato Bancário", "Financeiro")


def test_rotas_do_extrato_mapeadas_para_extb():
    for rota in ("/api/financeiro/extrato",
                 "/api/financeiro/extrato/importar",
                 "/api/financeiro/extrato/contas-erp",
                 "/api/financeiro/extrato/importacao/7"):
        telas = auth._telas_da_rota(rota)
        assert telas == frozenset({"extb"}), rota


def test_prefixo_do_extrato_vem_antes_de_prefixos_genericos():
    # /api/financeiro/extrato NÃO pode ser capturado por uma regra mais curta
    # que venha antes na lista (o casamento é por prefixo, primeira que casa)
    ordem = [p for p, _ in auth.ROTA_TELAS]
    i_ext = ordem.index("/api/financeiro/extrato")
    for p in ordem[:i_ext]:
        assert not "/api/financeiro/extrato".startswith(p) or p == "/api/financeiro/extrato"


def test_perfil_financeiro_modelo_inclui_extb():
    telas = dict((nome, t) for nome, _desc, t in auth._PERFIS_MODELO)
    assert "extb" in telas["Financeiro"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/extrato/test_rbac_extrato.py -v`
Expected: FAIL com `KeyError: 'extb'`

- [ ] **Step 3: Write minimal implementation**

3a. In `api/auth.py`, add the screen to `TELAS` right after the `"cob"` line (line ~53):

```python
    "cob":     ("Régua de Cobrança", "Financeiro"),
    "extb":    ("Extrato Bancário", "Financeiro"),
```

3b. In `api/auth.py`, add to `ROTA_TELAS` immediately **before** the `/api/financeiro/dre` entry (a rota do extrato não colide com nenhuma existente, mas manter as específicas juntas e antes das curtas é a regra da lista):

```python
    ("/api/financeiro/extrato",       frozenset({"extb"})),
    ("/api/financeiro/dre",           frozenset({"dre"})),
```

3c. In `api/auth.py`, add `"extb"` to the Financeiro model profile:

```python
    ("Financeiro",  "Caixa, recebíveis, pagáveis, cobrança e extrato bancário.",
     ["fluxo", "receber", "pagar", "cob", "extb"]),
```

3d. In `api/auth.py`, append the seed migration at the end of the seed block (after the `perfis_modelo_v18` block, keeping the same shape):

```python
    # v19 (extrato bancário 2026-08-01): tela 'extb' aos perfis Financeiro e
    # Controladoria. A tela nasceu depois que os perfis já existiam nas bases em
    # uso — editar _PERFIS_MODELO só vale para instalação nova (mesmo caso da
    # v8/'qual', v17/'orc' e v18/'prem').
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v19'").fetchone():
        for nome_perfil in ("Financeiro", "Controladoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=?", (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                          (row["id"], "extb"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v19', '1')")
```

3e. In `api/main.py`, add the endpoints right after the `orcamento_reabrir` endpoint block (search for `@app.post("/api/controladoria/orcamento/reabrir")` and place after its function ends). **Anchor on a literal unique trecho, never a regex over the file.**

```python
# ---------------------------------------------------------------- Extrato bancário

_EXT_MAX_BYTES = 8 * 1024 * 1024   # extrato OFX real tem dezenas/centenas de KB


@app.get("/api/financeiro/extrato")
def extrato(dt_de: str | None = None, dt_ate: str | None = None,
            conta_id: int | None = None) -> JSONResponse:
    from api.extrato.servico import painel
    # padrão = mês corrente (mesmo estilo dos outros endpoints deste arquivo,
    # que resolvem o período com date.today() — não há helper compartilhado)
    hoje = date.today()
    de = dt_de or hoje.replace(day=1).isoformat()
    ate = dt_ate or hoje.isoformat()
    try:
        return JSONResponse(painel(de, ate, conta_id))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a validação do extrato."})


@app.post("/api/financeiro/extrato/importar")
async def extrato_importar(req: Request, nome: str = "",
                           conta_id: int | None = None) -> JSONResponse:
    """Recebe o arquivo como CORPO BRUTO (um POST por arquivo).

    Sem multipart de propósito: `UploadFile` exige python-multipart, que não é
    dependência do projeto — e o `uv sync` do AutoDeploy é não-fatal, então a
    API poderia subir em produção sem a dep e derrubar só este endpoint.
    """
    from api.extrato.servico import importar
    bruto = await req.body()
    if not bruto:
        return JSONResponse(status_code=422, content={
            "erro": "arquivo_vazio", "mensagem": "Nenhum conteúdo recebido."})
    if len(bruto) > _EXT_MAX_BYTES:
        return JSONResponse(status_code=413, content={
            "erro": "arquivo_grande",
            "mensagem": f"Arquivo acima do limite de {_EXT_MAX_BYTES // (1024 * 1024)} MB."})
    arquivo = (nome or "extrato.ofx").strip()
    try:
        return JSONResponse(importar(bruto, arquivo, conta_id=conta_id))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "arquivo_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato_importar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_importacao", "mensagem": "Erro ao importar o extrato."})


@app.post("/api/financeiro/extrato/mapear")
async def extrato_mapear(req: Request) -> JSONResponse:
    """Vincula uma conta ao ERP e/ou salva o mapa de colunas do CSV.

    Sem `conta_id` e com `formato="csv"`, CRIA a conta: a identidade sai da conta
    bancária (`servico.ident_csv`), nunca do nome do arquivo — dois `extrato.csv`
    de bancos diferentes cairiam na mesma conta e misturariam lançamentos.
    """
    from api.extrato import armazenamento as arm
    from api.extrato.servico import ident_csv
    try:
        body = await req.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo inválido."})
    conta_id = body.get("conta_id")
    # criação de conta CSV: precisa da conta do ERP para formar a identidade
    if conta_id is None:
        if body.get("formato") != "csv" or body.get("erp_banco") is None:
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": "Informe conta_id, ou formato=csv com a conta do ERP."})
        try:
            arm.init_db(arm.DB_PATH)
            banco = int(body["erp_banco"])
            agencia = str(body.get("erp_agencia") or "")
            conta = str(body.get("erp_conta") or "")
            ident = ident_csv(banco, agencia, conta)
            rotulo = body.get("rotulo") or f"{banco} / ag {agencia} / cc {conta}"
            conta_id = arm.obter_ou_criar_conta(arm.DB_PATH, ident, rotulo)
        except (TypeError, ValueError):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido", "mensagem": "Conta do ERP inválida."})
    if not isinstance(conta_id, int):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "conta_id inválido."})
    try:
        arm.init_db(arm.DB_PATH)
        if body.get("erp_banco") is not None:
            arm.mapear_conta(arm.DB_PATH, conta_id, int(body["erp_banco"]),
                             str(body.get("erp_agencia") or ""),
                             str(body.get("erp_conta") or ""),
                             rotulo=(body.get("rotulo") or None))
        mapa = body.get("mapa_csv")
        if isinstance(mapa, dict):
            limpo = {k: int(v) for k, v in mapa.items() if isinstance(v, (int, float))}
            arm.salvar_mapa_csv(arm.DB_PATH, conta_id, limpo)
        # devolve o conta_id: no fluxo CSV a tela precisa dele para reenviar o
        # arquivo (importar exige conta_id explicito para CSV)
        return JSONResponse({"ok": True, "conta_id": conta_id})
    except (TypeError, ValueError):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Valores de mapeamento inválidos."})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato_mapear falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao salvar o mapeamento."})


@app.delete("/api/financeiro/extrato/importacao/{imp_id}")
def extrato_apagar(imp_id: int) -> JSONResponse:
    from api.extrato import armazenamento as arm
    try:
        arm.init_db(arm.DB_PATH)
        n = arm.apagar_importacao(arm.DB_PATH, imp_id)
        return JSONResponse({"ok": True, "apagados": n})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato_apagar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao desfazer a importação."})


@app.get("/api/financeiro/extrato/contas-erp")
def extrato_contas_erp() -> JSONResponse:
    from api.extrato.servico import contas_erp
    try:
        return JSONResponse({"contas": contas_erp()})
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato_contas_erp falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao listar as contas do ERP."})
```

**Já verificado:** `api/main.py:13` tem `from datetime import date` e `Request`/`JSONResponse`/`log`/`psycopg` já estão em uso no arquivo — nenhum import novo é necessário.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/extrato/ tests/test_auth_migracao.py -v`
Expected: PASS (36 + 4 novos + os de migração já existentes)

Run: `uv run python -c "from api import main; print('imports OK')"`
Expected: `imports OK`

- [ ] **Step 5: Commit**

```bash
git add api/main.py api/auth.py tests/extrato/test_rbac_extrato.py
git commit -m "feat(extrato): endpoints do extrato bancario e RBAC da tela extb"
```

---

### Task 7: Tela no front (SPA)

**Files:**
- Modify: `api/static/index.html` (seção da vista, loader/render, registros, sidebar, gaveta mobile)

**Interfaces:**
- Consumes: os 5 endpoints da Task 6 com o payload de `servico.painel`.
- Produces: vista `extb` navegável em `#extb`, com upload, mapeamento, farol e comparação dia a dia.

**Regra de patch (o projeto já se queimou com isso 3 vezes):** cada inserção usa
o helper `rep()` com assert de âncora literal única; rodar `node --check` no JS
extraído antes de gravar. Nunca regex ampla sobre o arquivo inteiro.

- [ ] **Step 1: Register the view in the 6 registration points**

Cada item é uma substituição literal única:

1. `const VIEWS = {` — adicionar `extb:'Extrato Bancário',` após `cob:'Régua de Cobrança',`
2. `const VIEW_GROUP = {` — na linha `fluxo:'Fin',receber:'Fin',pagar:'Fin',cob:'Fin',` acrescentar `extb:'Fin',`
3. `const DATAMAP={` — acrescentar `extb:DATAEXTB,`
4. `const LOADMAP={` — acrescentar `extb:loadExtb,`
5. `function semFilterbar(v){` — incluir `||v==='extb'` na expressão (a tela tem filtros próprios: conta + período)
6. Declarar as variáveis de estado junto às demais `DATA*`: `let DATAEXTB=null, extbSeq=0;`

- [ ] **Step 2: Add the view section in the HTML**

Inserir após o fechamento de `<section class="view" id="view-cob">` (âncora literal: o `</section>` seguido do comentário da próxima vista):

```html
      <!-- ===================== EXTRATO BANCÁRIO ===================== -->
      <section class="view" id="view-extb">
        <div class="card">
          <div class="head"><h2>Extrato Bancário</h2>
            <span class="hint">valida saldo e fluxo do ERP contra o extrato do banco
              <span class="ihelp" title="Extrato importado (OFX/CSV) comparado com contacorrente_saldo do ERP AVA, por conta e por dia. Tolerância de R$ 0,01.">ⓘ</span></span>
          </div>
          <div class="cardfilters" id="extb-filtros">
            <select id="fExtbConta" aria-label="Conta" onchange="loadExtb()"></select>
            <input type="text" id="fExtbDe" placeholder="Data inicial" inputmode="numeric" aria-label="Data inicial">
            <input type="text" id="fExtbAte" placeholder="Data final" inputmode="numeric" aria-label="Data final">
            <button class="ghost" onclick="loadExtb()">Aplicar</button>
            <button class="ghost" onclick="document.getElementById('extbArquivo').click()">⬆ Importar extrato</button>
            <input type="file" id="extbArquivo" accept=".ofx,.qfx,.csv,.txt" multiple style="display:none" onchange="extbEnviar(this.files)">
          </div>
        </div>
        <div id="extb-aviso"></div>
        <div class="kpis k4" id="kpis-extb"></div>
        <div class="card"><div class="head"><h2>Situação por conta</h2>
          <span class="hint" id="hintExtbContas"></span></div>
          <div class="tablewrap tabroll" id="extb-contas"></div></div>
        <div class="card"><div class="head"><h2>Comparação dia a dia</h2>
          <span class="hint" id="hintExtbDias"></span></div>
          <div class="tablewrap tabroll" id="extb-dias"></div></div>
        <div class="card"><div class="head"><h2>Importações recentes</h2>
          <span class="hint" id="hintExtbImps"></span></div>
          <div class="tablewrap tabroll" id="extb-imps"></div></div>
      </section>
```

- [ ] **Step 3: Add the loader and renderers**

Inserir junto aos demais loaders (após `renderCob`, âncora literal do fim daquela função):

```javascript
/* ---------------- Extrato Bancário ---------------- */
// O BRL global do painel tem maximumFractionDigits:0 — aqui a tolerância é de
// R$ 0,01, então esconder centavos faria uma divergência real aparecer como zero.
const BRL2 = new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL',
                                            minimumFractionDigits:2,maximumFractionDigits:2});
const brl2 = v => (v==null ? '—' : BRL2.format(v));
const EXTB_FAROL = {ok:['good','bate com o banco'], diverge:['bad','divergente'],
                    sem_mapa:['warn','sem vínculo com o ERP'],
                    desatualizado:['warn','extrato desatualizado']};

async function loadExtb(){
  const seq=++extbSeq, btn=document.getElementById('btnRefresh'); if(btn) btn.disabled=true;
  document.getElementById('content').classList.add('loading');
  skelKpis('kpis-extb',4);
  const de=document.getElementById('fExtbDe'), ate=document.getElementById('fExtbAte');
  if(de && !de.value){ const h=new Date(); de.value=_iso(new Date(h.getFullYear(),h.getMonth(),1)); }
  if(ate && !ate.value){ ate.value=_iso(new Date()); }
  try{
    const p=new URLSearchParams();
    p.set('dt_de', de.value); p.set('dt_ate', ate.value);
    const c=(document.getElementById('fExtbConta')||{}).value;
    if(c) p.set('conta_id', c);
    const r=await fetch('/api/financeiro/extrato?'+p.toString(),{cache:'no-store'});
    const d=await r.json(); if(seq!==extbSeq) return;
    if(!r.ok){ showBanner(d.mensagem||'Erro ao consultar o extrato.', d.detalhe); return; }
    hideBanner(); DATAEXTB=d; LOADEDQS.extb=''; renderExtb(d);
  }catch(e){ if(seq===extbSeq) showBanner('Não foi possível falar com a API.', e.message); }
  finally{ if(seq===extbSeq){ if(btn) btn.disabled=false;
    document.getElementById('content').classList.remove('loading'); } }
}

function renderExtb(d){
  const ts=new Date();
  document.getElementById('meta').innerHTML='<b>Atualizado '+ts.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})+'</b><br>'+ts.toLocaleDateString('pt-BR');
  const k=d.kpis||{};
  // conta sem extrato nenhum: a tela explica o que fazer em vez de mostrar zeros
  if(!(d.contas||[]).length){
    document.getElementById('kpis-extb').innerHTML='';
    document.getElementById('extb-aviso').innerHTML=
      '<div class="card"><p>Nenhum extrato importado ainda. Use <b>⬆ Importar extrato</b> '
      +'e escolha o arquivo OFX (ou CSV) baixado do internet banking. '
      +'Na primeira vez de cada conta você aponta a qual conta do ERP ela corresponde.</p></div>';
    ['extb-contas','extb-dias','extb-imps'].forEach(id=>document.getElementById(id).innerHTML='');
    return;
  }
  document.getElementById('extb-aviso').innerHTML='';
  const semMapa=k.contas_sem_mapa||0;
  document.getElementById('kpis-extb').innerHTML=
     kpi('Contas monitoradas', String(k.contas||0),
         semMapa?(semMapa+' sem vínculo com o ERP'):'todas vinculadas ao ERP',
         semMapa?'warn':'', 'Contas com extrato importado. Só as vinculadas a uma conta do ERP podem ser comparadas.')
   + kpi('Dias validados', String(k.dias_validados||0), 'no período filtrado', '',
         'Dias em que existe extrato E movimento do ERP para comparar.')
   + kpi('Dias divergentes', String(k.dias_divergentes||0),
         (k.dias_divergentes?'exigem conferência':'nenhuma divergência'),
         (k.dias_divergentes?'bad':'good'),
         'Dia em que crédito, débito ou saldo diferem em mais de R$ 0,01.')
   + kpi('Maior diferença', (k.maior_diferenca!=null?brl2(k.maior_diferenca):'—'),
         (k.maior_diferenca_conta?esc(k.maior_diferenca_conta)+' · '+fmtD(k.maior_diferenca_dt):'sem divergência'),
         (k.maior_diferenca?'bad':''), 'Maior diferença absoluta encontrada no período.');

  // ---- situação por conta
  const contas=d.contas||[];
  document.getElementById('hintExtbContas').textContent=
    contas.length+' conta'+(contas.length===1?'':'s')+' · farol = último dia com extrato';
  document.getElementById('extb-contas').innerHTML=
    '<table><thead><tr><th>Conta</th><th>Conta no ERP</th><th>Último dia</th>'
    +'<th class="num">Diferença de saldo</th><th class="num">Dias validados</th>'
    +'<th class="num">Divergentes</th><th>Estado</th></tr></thead><tbody>'
    + contas.map(c=>{
        const f=c.farol||{}, par=EXTB_FAROL[f.estado]||['',''];
        const acao = c.mapeada ? '' :
          ` <button class="ghost" onclick="extbMapearConta(${c.conta_id})">vincular</button>`;
        const dias = f.dias_sem_extrato;
        const sub = (f.estado==='desatualizado' && dias!=null)
          ? `${dias} ${dias===1?'dia':'dias'} sem extrato` : par[1];
        return `<tr><td>${esc(c.rotulo)}${acao}</td>`
          +`<td>${c.erp?esc(c.erp):'<span style="color:var(--n500)">não vinculada</span>'}</td>`
          +`<td>${f.dt?fmtD(f.dt):'—'}</td>`
          +`<td class="num">${f.delta!=null?brl2(f.delta):'—'}</td>`
          +`<td class="num">${c.dias_validados}</td>`
          +`<td class="num">${c.dias_divergentes||'—'}</td>`
          +`<td>${statChip(par[0], sub)}</td></tr>`;
      }).join('')
    + '</tbody></table>';

  // select de conta da tabela dia a dia
  const sel=document.getElementById('fExtbConta');
  if(sel){
    const atual=String(d.conta_selecionada||'');
    sel.innerHTML=contas.map(c=>`<option value="${c.conta_id}">${esc(c.rotulo)}</option>`).join('');
    if(atual) sel.value=atual;
  }

  // ---- comparação dia a dia
  const dias=d.dias||[];
  document.getElementById('hintExtbDias').textContent= dias.length
    ? dias.length+' dia'+(dias.length===1?'':'s')+' · clique na linha para ver os lançamentos do extrato'
    : 'sem dias no período para a conta selecionada';
  const EST={OK:['good','bate'],DIVERGE:['bad','diverge'],
             SO_EXTRATO:['warn','só no extrato'],SO_ERP:['warn','só no ERP']};
  document.getElementById('extb-dias').innerHTML= !dias.length ? '' :
    '<table><thead><tr><th>Dia</th><th class="num">Créditos extrato</th>'
    +'<th class="num">Créditos ERP</th><th class="num">Débitos extrato</th>'
    +'<th class="num">Débitos ERP</th><th class="num">Saldo extrato</th>'
    +'<th class="num">Saldo ERP</th><th class="num">Diferença</th><th>Estado</th></tr></thead><tbody>'
    + dias.map((x,i)=>{
        const par=EST[x.estado]||['',''];
        const dif=[x.d_saldo,x.d_credito,x.d_debito].find(v=>v!=null&&Math.abs(v)>0.01);
        return `<tr class="forn-row" onclick="extbDetalhe(${i})">`
          +`<td>${fmtD(x.dt)}</td>`
          +`<td class="num">${x.ext_credito!=null?brl2(x.ext_credito):'—'}</td>`
          +`<td class="num">${x.erp_credito!=null?brl2(x.erp_credito):'—'}</td>`
          +`<td class="num">${x.ext_debito!=null?brl2(x.ext_debito):'—'}</td>`
          +`<td class="num">${x.erp_debito!=null?brl2(x.erp_debito):'—'}</td>`
          +`<td class="num">${x.ext_saldo!=null?brl2(x.ext_saldo):'<span style="color:var(--n500)" title="O arquivo não trouxe saldo final (LEDGERBAL): sem âncora não é possível derivar o saldo do dia.">n/d</span>'}</td>`
          +`<td class="num">${x.erp_saldo!=null?brl2(x.erp_saldo):'—'}</td>`
          +`<td class="num">${dif!=null?brl2(dif):'—'}</td>`
          +`<td>${statChip(par[0], par[1])}</td></tr>`
          +`<tr class="forn-det" id="extb-det-${i}" style="display:none"><td colspan="9"></td></tr>`;
      }).join('')
    + '</tbody></table>';

  // ---- importações
  const imps=d.importacoes||[];
  document.getElementById('hintExtbImps').textContent=
    imps.length? imps.length+' importação'+(imps.length===1?'':'ões')+' · desfazer remove os lançamentos daquele arquivo'
               : 'nenhuma importação registrada';
  document.getElementById('extb-imps').innerHTML= !imps.length ? '' :
    '<table><thead><tr><th>Quando</th><th>Arquivo</th><th>Conta</th><th>Período</th>'
    +'<th class="num">Novos</th><th class="num">Duplicados</th><th class="num">Ignorados</th>'
    +'<th></th></tr></thead><tbody>'
    + imps.map(i=>`<tr><td>${fmtDT(i.quando)}</td><td>${esc(i.arquivo)}</td>`
        +`<td>${esc(i.conta_rotulo)}</td>`
        +`<td>${i.dt_de?fmtD(i.dt_de)+' a '+fmtD(i.dt_ate):'—'}</td>`
        +`<td class="num">${i.novas}</td><td class="num">${i.duplicadas||'—'}</td>`
        +`<td class="num">${i.ignoradas||'—'}</td>`
        +`<td><button class="ghost" onclick="extbDesfazer(${i.id})">desfazer</button></td></tr>`).join('')
    + '</tbody></table>';
}

function extbDetalhe(i){
  const tr=document.getElementById('extb-det-'+i); if(!tr) return;
  const aberto = tr.style.display!=='none';
  tr.style.display = aberto ? 'none' : '';
  if(aberto || tr.dataset.pronto) return;
  const x=(DATAEXTB.dias||[])[i]; if(!x) return;
  const p=new URLSearchParams({dt_de:x.dt, dt_ate:x.dt});
  const c=(document.getElementById('fExtbConta')||{}).value; if(c) p.set('conta_id', c);
  fetch('/api/financeiro/extrato?'+p.toString(),{cache:'no-store'})
    .then(r=>r.json()).then(d=>{
      const lan=(d.lancamentos_dia||[]);
      tr.querySelector('td').innerHTML = lan.length
        ? '<table><thead><tr><th>Data</th><th>Histórico</th><th>Documento</th>'
          +'<th class="num">Valor</th></tr></thead><tbody>'
          + lan.map(l=>`<tr><td>${fmtD(l.dt)}</td><td>${esc(l.historico||'')}</td>`
              +`<td>${esc(l.numerodoc||'')}</td>`
              +`<td class="num ${l.valor<0?'neg':''}">${brl2(l.valor)}</td></tr>`).join('')
          + '</tbody></table>'
        : '<p style="color:var(--n500)">Nenhum lançamento do extrato neste dia (o movimento está só no ERP).</p>';
      tr.dataset.pronto='1';
    }).catch(()=>{ tr.querySelector('td').innerHTML='<p style="color:var(--n500)">Erro ao carregar os lançamentos.</p>'; });
}

async function extbEnviar(files){
  if(!files || !files.length) return;
  const btn=document.getElementById('btnRefresh'); if(btn) btn.disabled=true;
  const resumo=[];
  for(const f of files){
    try{
      const r=await fetch('/api/financeiro/extrato/importar?nome='+encodeURIComponent(f.name),
                          {method:'POST', body:f});
      const d=await r.json();
      if(!r.ok){ resumo.push(esc(f.name)+': '+esc(d.mensagem||'erro')); continue; }
      if(d.ok===false && d.precisa==='mapa_erp'){
        await extbMapearConta(d.conta_id);
      }else if(d.ok===false && d.precisa==='mapa_csv'){
        extbMapearCsv(d);
        resumo.push(esc(f.name)+': aponte as colunas do CSV e envie novamente.');
        continue;
      }
      resumo.push(esc(f.name)+`: ${d.novas} novo(s), ${d.duplicadas} duplicado(s)`
        + (d.ignoradas?`, ${d.ignoradas} ignorado(s)`:''));
    }catch(e){ resumo.push(esc(f.name)+': falha no envio'); }
  }
  document.getElementById('extbArquivo').value='';
  if(btn) btn.disabled=false;
  showBanner('Importação: '+resumo.join(' · '));
  loadExtb();
}

async function extbMapearConta(contaId){
  let contas=[];
  try{
    const r=await fetch('/api/financeiro/extrato/contas-erp',{cache:'no-store'});
    const d=await r.json(); contas=d.contas||[];
  }catch(e){ showBanner('Não foi possível listar as contas do ERP.'); return; }
  const lista=contas.map((c,i)=>`${i+1}) ${c.rotulo} (último movimento ${c.ultimo_movimento})`).join('\n');
  const esc0=prompt('A qual conta do ERP este extrato corresponde?\n\n'+lista
    +'\n\nDigite o número da opção:');
  const idx=parseInt(esc0,10);
  if(!idx || idx<1 || idx>contas.length) return;
  const c=contas[idx-1];
  await fetch('/api/financeiro/extrato/mapear',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({conta_id:contaId, erp_banco:c.banco, erp_agencia:c.agencia,
                         erp_conta:c.conta, rotulo:c.rotulo})});
  loadExtb();
}

function extbMapearCsv(d){
  const cab=((d.preview||{}).amostra||[])[0]||[];
  const lista=cab.map((h,i)=>`${i}) ${h}`).join('\n');
  const pergunta=(rot)=>{
    const v=prompt(`Colunas do arquivo:\n${lista}\n\nQual é o índice da coluna de ${rot}?`
      +'\n(deixe vazio se não existir)');
    const n=parseInt(v,10); return isNaN(n)?null:n;
  };
  const mapa={dt:pergunta('DATA'), valor:pergunta('VALOR (deixe vazio se houver crédito e débito separados)')};
  if(mapa.valor===null){ mapa.credito=pergunta('CRÉDITO'); mapa.debito=pergunta('DÉBITO'); }
  mapa.historico=pergunta('HISTÓRICO'); mapa.numerodoc=pergunta('DOCUMENTO');
  Object.keys(mapa).forEach(k=>{ if(mapa[k]===null) delete mapa[k]; });
  if(mapa.dt===undefined){ showBanner('Mapeamento cancelado: a coluna de data é obrigatória.'); return; }
  fetch('/api/financeiro/extrato/mapear',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({conta_id:d.conta_id, mapa_csv:mapa})})
    .then(()=>showBanner('Colunas salvas. Envie o arquivo novamente para importar.'));
}

async function extbDesfazer(impId){
  if(!confirm('Desfazer esta importação? Os lançamentos daquele arquivo serão removidos.')) return;
  try{
    const r=await fetch('/api/financeiro/extrato/importacao/'+impId,{method:'DELETE'});
    const d=await r.json();
    if(!r.ok){ showBanner(d.mensagem||'Erro ao desfazer.'); return; }
    showBanner(`Importação desfeita (${d.apagados} lançamento(s) removido(s)).`);
    loadExtb();
  }catch(e){ showBanner('Falha ao desfazer a importação.'); }
}
```

**Nota de contrato:** `extbDetalhe` espera `lancamentos_dia` no payload. Adicionar
em `api/extrato/servico.py`, no `return` do `painel`, logo após `"dias": dias_sel,`:

```python
        "lancamentos_dia": (arm.lancamentos(path, conta_id, dt_de, dt_ate)
                            if conta_id is not None else []),
```

- [ ] **Step 4: Add the links (sidebar + mobile drawer)**

No `<aside id="sidebar">`, dentro de `subsFin`, após o link da Régua de Cobrança:

```html
          <a href="#extb" data-tela="extb">Extrato Bancário</a>
```

Na gaveta mobile (`.drawer`), no painel do grupo Financeiro, o mesmo link — a
estrutura `h3` + `<a>` irmãos **não** pode mudar (`aplicarPermissoes` depende dela).

- [ ] **Step 5: Verify the front and commit**

```bash
# JS válido (extrai o script e checa) — o projeto já gravou SyntaxError em disco
uv run python - <<'PY'
import re, pathlib, subprocess, tempfile
html = pathlib.Path("api/static/index.html").read_text()
js = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write(js); p = f.name
print(subprocess.run(["node", "--check", p], capture_output=True, text=True))
PY
uv run python -c "from api import main; print('imports OK')"
uv run pytest tests/extrato/ -q
```
Expected: `node --check` sem erro, `imports OK`, testes passando.

```bash
git add api/static/index.html api/extrato/servico.py
git commit -m "feat(extrato): tela Extrato Bancario na SPA (upload, farol e comparacao diaria)"
```

---

### Task 8: Alertas no digest

**Files:**
- Modify: `api/alertas.py`
- Test: `tests/extrato/test_alertas_extrato.py`

**Interfaces:**
- Consumes: `servico.painel` (Task 5).
- Produces: itens de alerta no `build_alertas()` existente (formato `{"nivel","titulo","texto"}`).

- [ ] **Step 1: Write the failing test**

Create `tests/extrato/test_alertas_extrato.py`:

```python
"""Alertas do extrato: divergência e extrato parado."""
from __future__ import annotations

from api import alertas


def _painel(contas):
    return {"kpis": {}, "contas": contas, "dias": [], "importacoes": []}


def test_divergencia_gera_alerta_critico():
    p = _painel([{"rotulo": "Itau 539349", "mapeada": True, "dias_divergentes": 2,
                  "farol": {"estado": "diverge", "dt": "2026-07-31", "delta": -1250.40,
                            "dias_sem_extrato": 1}}])
    itens = alertas._alertas_extrato(p)
    assert len(itens) == 1
    nivel, titulo, texto = itens[0]
    assert nivel == "critico"
    assert "Itau 539349" in texto and "31/07/2026" in texto
    assert "1.250,40" in texto


def test_extrato_parado_gera_atencao():
    p = _painel([{"rotulo": "Bradesco 1239066", "mapeada": True, "dias_divergentes": 0,
                  "farol": {"estado": "desatualizado", "dt": "2026-07-20", "delta": 0.0,
                            "dias_sem_extrato": 12}}])
    itens = alertas._alertas_extrato(p)
    assert itens and itens[0][0] == "atencao"
    assert "12 dias" in itens[0][2]


def test_conta_sem_vinculo_nao_alerta():
    p = _painel([{"rotulo": "CSV novo", "mapeada": False, "dias_divergentes": 0,
                  "farol": {"estado": "sem_mapa", "dt": None, "delta": None,
                            "dias_sem_extrato": None}}])
    assert alertas._alertas_extrato(p) == []


def test_tudo_ok_nao_alerta():
    p = _painel([{"rotulo": "Itau", "mapeada": True, "dias_divergentes": 0,
                  "farol": {"estado": "ok", "dt": "2026-07-31", "delta": 0.0,
                            "dias_sem_extrato": 1}}])
    assert alertas._alertas_extrato(p) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/extrato/test_alertas_extrato.py -v`
Expected: FAIL com `AttributeError: module 'api.alertas' has no attribute '_alertas_extrato'`

- [ ] **Step 3: Write minimal implementation**

Add to `api/alertas.py`, before `def build_alertas()`:

```python
def _alertas_extrato(painel: dict) -> list[tuple[str, str, str]]:
    """(nivel, titulo, texto) por conta com problema. Função pura para teste."""
    out: list[tuple[str, str, str]] = []
    for c in painel.get("contas") or []:
        if not c.get("mapeada"):
            continue          # sem vínculo com o ERP não há o que comparar
        f = c.get("farol") or {}
        if f.get("estado") == "diverge":
            delta = f.get("delta") or 0.0
            out.append((
                "critico", "Extrato bancário divergente",
                f"A conta {c['rotulo']} fecha {_fmt_brl(abs(delta))} "
                f"{'acima' if delta > 0 else 'abaixo'} do ERP em "
                f"{_data_br(f.get('dt'))}. Detalhe: Financeiro > Extrato Bancário."))
        elif f.get("estado") == "desatualizado" and f.get("dias_sem_extrato"):
            d = f["dias_sem_extrato"]
            out.append((
                "atencao", "Extrato bancário sem atualização",
                f"A conta {c['rotulo']} está há {d} {'dia' if d == 1 else 'dias'} "
                "sem extrato importado - a validação de saldo está cega nesse período."))
    return out


def _data_br(iso: str | None) -> str:
    if not iso:
        return "-"
    p = str(iso).split("-")
    return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 else str(iso)
```

And inside `build_alertas()`, after the existing `try` blocks:

```python
    try:
        from api.extrato.servico import painel as extrato_painel
        hoje = date.today()
        p = extrato_painel(hoje.replace(day=1).isoformat(), hoje.isoformat())
        for nivel, titulo, texto in _alertas_extrato(p):
            add(nivel, titulo, texto)
    except Exception as exc:  # noqa: BLE001
        log.warning("alertas extrato: %s", exc)
```

**Já verificado:** `api/alertas.py:13` tem `from datetime import date` — nenhum import novo é necessário.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/extrato/ -v && uv run python -c "from api import alertas; print(len(alertas.build_alertas()), 'alertas')"`
Expected: testes PASS; o segundo comando imprime a contagem sem exceção.

- [ ] **Step 5: Commit**

```bash
git add api/alertas.py tests/extrato/test_alertas_extrato.py
git commit -m "feat(extrato): alertas de divergencia e extrato parado no digest"
```

---

### Task 9: Validação no navegador e deploy

**Files:**
- Create: `/private/tmp/claude-501/.../scratchpad/extrato_smoke.py` (harness temporário, fora do repo)
- Modify: `docs/superpowers/specs/2026-08-01-extrato-bancario-design.md` (registrar a decisão de corpo bruto em vez de multipart)

**Interfaces:**
- Consumes: tudo das Tasks 1-8.
- Produces: evidência de que a tela funciona ponta a ponta e o deploy em produção.

- [ ] **Step 1: Generate a realistic OFX fixture and import it via the API**

Escrever no scratchpad um OFX de teste com a conta REAL do ERP (Itaú 341/0098/539349,
que tem 142 dias de movimento em 2026) e dias que existam em `contacorrente_saldo`,
para a comparação produzir OK e DIVERGE de verdade. Rodar a API local
(`scripts/run_api.sh`) e:

```bash
curl -s -X POST "http://127.0.0.1:8000/api/financeiro/extrato/importar?nome=itau.ofx" \
  --data-binary @/private/tmp/claude-501/*/scratchpad/itau_teste.ofx | head -20
curl -s "http://127.0.0.1:8000/api/financeiro/extrato?dt_de=2026-07-01&dt_ate=2026-07-31" | head -40
```
Expected: JSON com `novas > 0` e, após o mapeamento, `dias` com `estado` preenchido.

- [ ] **Step 2: Drive the screen with Playwright (desktop + mobile viewport)**

Reusar o harness já usado no projeto (servidor de teste com `auth.DB_PATH` isolado
em DB temporário + `init_db()`, `uv run --with playwright`, chromium já em
`~/Library/Caches/ms-playwright`). Checar: login → `#extb` → KPIs renderizados →
tabela de contas com farol → expandir um dia → gaveta mobile (390×844) mostra o
link "Extrato Bancário". `wait_for_selector('#loginOverlay.oculto', state='attached')`.

Expected: nenhum erro de console; os 4 KPIs presentes; link visível na gaveta.

- [ ] **Step 3: Run the structural check and full test suite**

```bash
uv run python scratchpad/estrutura.py   # atributo com aspa, .val fora de .kpi, aspa curva
uv run pytest tests/ -q
```
Expected: verificação estrutural sem falha; suíte inteira verde.

- [ ] **Step 4: Update the spec with the multipart decision**

Na seção "Endpoints" do spec, trocar a linha do upload multipart por:

```markdown
- `POST /api/financeiro/extrato/importar?nome=<arquivo>` — **corpo bruto** do
  arquivo (um POST por arquivo; o front itera a seleção múltipla). Sem multipart
  de propósito: `UploadFile` exigiria `python-multipart`, que não é dependência
  do projeto, e o `uv sync` do AutoDeploy é não-fatal — a API poderia subir em
  produção sem a dep e derrubar só este endpoint. Limite de 8 MB por arquivo.
```

- [ ] **Step 5: Commit and deploy**

```bash
git add docs/superpowers/specs/2026-08-01-extrato-bancario-design.md
git commit -m "docs(extrato): registra upload por corpo bruto em vez de multipart"
git push origin main
ssh -o ClearAllForwardings=yes cortex-ava-tunnel "schtasks /run /tn \"Cortex Sulista - AutoDeploy\""
```

Aguardar ~1 min e confirmar que produção subiu no commit novo:

```bash
ssh -o ClearAllForwardings=yes cortex-ava-tunnel "type C:\\Users\\inteligencia\\Documents\\cortex-sulista\\logs\\deployed.txt"
ssh -o ClearAllForwardings=yes cortex-ava-tunnel "curl -s -o NUL -w %%{http_code} http://127.0.0.1:8010/api/health"
```
Expected: `deployed.txt` com o hash do commit novo; health 200.

---

## Self-Review

**1. Spec coverage** — cada requisito do spec tem task:

| Requisito do spec | Task |
|---|---|
| SQLite `data/extrato.db`, 4 tabelas, dedup FITID/hash, desfazer por importação | 1 |
| Parser OFX 1.x/2.x + encoding BR + LEDGERBAL | 2 |
| Parser CSV + mapeamento de colunas + parse estrito pt-BR | 3 |
| Comparação conta×dia, tolerância R$ 0,01, estados, saldo derivado, farol | 4 |
| Orquestração import + painel + `contas-erp` | 5 |
| 5 endpoints + RBAC (`extb`, ROTA_TELAS, seed v19) | 6 |
| Tela: KPIs, farol, comparação expansível, uploads, modal de mapeamento, mobile | 7 |
| Alertas de divergência e de extrato parado no digest | 8 |
| Testes puros + Playwright + deploy | 9 |

**2. Placeholder scan** — nenhum "TBD"/"implementar depois"/"tratar erros apropriadamente"; todo step de código traz o código.

**3a. Helpers do front conferidos contra o `index.html` real** (evita a task travar
com `ReferenceError`): existem e são usados como está — `esc` (2544), `_iso` (3108),
`fmtD` (2540), `fmtDT` (2542), `statChip(cls,texto,titulo,ic)` (3310), `kpi()` (3285),
`skelKpis(id,n)` (5073), `showBanner/hideBanner` (3192), `LOADEDQS`, classes CSS `.num`
e `.neg`. **Não existem** e por isso não são usados: `fmtBRL` (o formatador de moeda é
`BRL`, com 0 decimais — a tela define `brl2` com centavos) e `.muted` (texto atenuado
sai com `style="color:var(--n500)"`).

**3. Type consistency** — verificado: `parse_ofx`/`parse_csv` devolvem itens com exatamente as chaves que `gravar_lancamentos` consome (`dt, valor, tipo, historico, numerodoc, fitid`); `comparar` consome `dt/valor/tipo` de `lancamentos` e `dt/credito/debito/saldo` de `_erp_dias`; `farol` recebe a lista de `comparar` e devolve o dict que `renderExtb` e `_alertas_extrato` leem (`estado`, `dt`, `delta`, `dias_sem_extrato`); `painel` devolve `lancamentos_dia`, exigido por `extbDetalhe` (adicionado explicitamente na Task 7, Step 3).

**Desvios do spec, deliberados e registrados:** (a) upload por corpo bruto em vez de multipart, para não adicionar dependência que o AutoDeploy pode não instalar — spec atualizado na Task 9; (b) mapeamento de conta/colunas via `prompt()` em vez de modal desenhado, para manter a Task 7 num único patch — evoluir para modal se o uso incomodar.
