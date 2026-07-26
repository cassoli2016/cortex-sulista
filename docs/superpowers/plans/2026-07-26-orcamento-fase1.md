# Módulo Orçamentário — Fase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derivar um orçamento anual por conta contábil a partir do histórico, deixar a controladoria ajustá-lo e acompanhar orçado × realizado na cascata da DRE.

**Architecture:** Pacote novo `api/orcamento/` com a lógica pura de derivação separada do acesso a dados (mesmo padrão de `api/dre_cliente/`). O orçamento mora em SQLite local (`data/orcamento.db`) porque o ERP é réplica somente-leitura. O realizado e o rollup conta → agrupador → linha reusam o caminho que `get_dre` já percorre, de modo que reclassificar uma conta move orçado e realizado juntos.

**Tech Stack:** Python 3.14, FastAPI, psycopg 3, SQLite (stdlib), pytest, SPA vanilla JS em `api/static/index.html`.

## Global Constraints

- **O banco AVA é somente-leitura.** Nenhum `INSERT`/`UPDATE`/`CREATE` no PostgreSQL. Toda escrita vai para `data/orcamento.db`.
- **PostgreSQL 9.3:** sem `FILTER (WHERE …)`, sem `LATERAL`. Usar `CASE WHEN`.
- **SQL sempre com `coalesce(l.valorcredito,0) - coalesce(l.valordebito,0)`** — o lado vazio é `NULL` e propaga, descartando a linha.
- **Sempre excluir `coalesce(l.historico,0) <> 18`** (lançamentos de apuração).
- **`psycopg` reserva `%`:** literais com `%` em SQL passado a `cur.execute` precisam de `%%`, ou usar `position(x in y)=1` no lugar de `LIKE 'x%'`.
- **`ast.parse(s)` antes de gravar qualquer `.py`**; `node --check` sobre o `<script>` antes de gravar `index.html`.
- **Nunca rodar substituição em massa de aspas** no `index.html` (quebrou a Visão Geral em 2026-07-26).
- **Mês corrente nunca entra em base histórica.**
- **Cor de desvio pelo efeito no resultado, nunca pelo sinal.**
- Responder e rotular tudo em **pt-BR**, com vírgula decimal.

---

### Task 1: Derivação pura (mês espelho + tendência)

**Files:**
- Create: `api/orcamento/__init__.py` (vazio nesta task)
- Create: `api/orcamento/derivacao.py`
- Test: `tests/orcamento/__init__.py`, `tests/orcamento/test_derivacao.py`

**Interfaces:**
- Consumes: nada (função pura, primeira task).
- Produces: `derivar(historico, meses_base, fator) -> list[dict]`, onde cada dict é
  `{"conta": str, "mes": int(1-12), "valor_baseline": float, "origem": str, "meses_com_dado": int}`
  e `origem ∈ {"espelho", "mediana", "sem_base"}`. Constante `RECORRENCIA_MIN = 0.75`.

- [ ] **Step 1: Criar os pacotes vazios**

```bash
mkdir -p api/orcamento tests/orcamento
touch api/orcamento/__init__.py tests/orcamento/__init__.py
```

- [ ] **Step 2: Escrever o teste que falha**

Criar `tests/orcamento/test_derivacao.py`:

```python
"""Testes da derivação do baseline orçamentário (mês espelho + tendência)."""
from __future__ import annotations

from api.orcamento.derivacao import RECORRENCIA_MIN, derivar

# 12 meses fechados de base: ago/25 .. jul/26
MESES = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12",
         "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]


def _por_mes(linhas, conta):
    return {l["mes"]: l for l in linhas if l["conta"] == conta}


def test_conta_recorrente_usa_mes_espelho():
    # valor diferente em cada mês: o alvo tem de pegar o MESMO mês-calendário
    hist = {"1|100": {m: float(i + 1) * 1000 for i, m in enumerate(MESES)}}
    linhas = derivar(hist, MESES, 0.0)
    got = _por_mes(linhas, "1|100")
    assert got[12]["valor_baseline"] == 5000.0   # dez alvo <- 2025-12 (5º da lista)
    assert got[1]["valor_baseline"] == 6000.0    # jan alvo <- 2026-01
    assert got[7]["valor_baseline"] == 12000.0   # jul alvo <- 2026-07
    assert all(l["origem"] == "espelho" for l in got.values())


def test_fator_de_tendencia_multiplica():
    hist = {"1|100": {m: 1000.0 for m in MESES}}
    linhas = derivar(hist, MESES, -0.10)
    assert _por_mes(linhas, "1|100")[3]["valor_baseline"] == 900.0


def test_sazonalidade_de_dezembro_e_preservada():
    # dez vale 40% dos demais — o baseline de dezembro tem de refletir isso
    hist = {"1|100": {m: (4000.0 if m.endswith("-12") else 10000.0) for m in MESES}}
    got = _por_mes(derivar(hist, MESES, 0.0), "1|100")
    assert got[12]["valor_baseline"] == 4000.0
    assert got[11]["valor_baseline"] == 10000.0


def test_conta_esporadica_cai_para_mediana_e_marca_base_fraca():
    # 2 meses de 12 = 17% < 75%: não é recorrente
    hist = {"9|900": {"2025-09": 300.0, "2026-02": 100.0}}
    linhas = derivar(hist, MESES, 0.0)
    got = _por_mes(linhas, "9|900")
    assert len(got) == 12
    assert all(l["origem"] == "mediana" for l in got.values())
    assert all(l["valor_baseline"] == 200.0 for l in got.values())  # mediana(100,300)
    assert all(l["meses_com_dado"] == 2 for l in got.values())


def test_corte_de_recorrencia_em_75_por_cento():
    assert RECORRENCIA_MIN == 0.75
    # 9 de 12 = 75% -> recorrente
    nove = {m: 1000.0 for m in MESES[:9]}
    got = _por_mes(derivar({"1|100": nove}, MESES, 0.0), "1|100")
    assert got[8]["origem"] == "espelho"      # ago tem base
    # 8 de 12 = 67% -> mediana
    oito = {m: 1000.0 for m in MESES[:8]}
    got8 = _por_mes(derivar({"1|101": oito}, MESES, 0.0), "1|101")
    assert all(l["origem"] == "mediana" for l in got8.values())


def test_mes_sem_base_em_conta_recorrente_sai_zerado_e_marcado():
    # recorrente (11 de 12), mas sem dezembro: dez alvo não pode inventar valor
    hist = {"1|100": {m: 1000.0 for m in MESES if m != "2025-12"}}
    got = _por_mes(derivar(hist, MESES, 0.0), "1|100")
    assert got[12]["valor_baseline"] == 0.0
    assert got[12]["origem"] == "sem_base"
    assert got[1]["origem"] == "espelho"


def test_valores_negativos_de_custo_sao_preservados():
    # custo entra como credito-debito, ou seja, negativo
    hist = {"4|400": {m: -2500.0 for m in MESES}}
    got = _por_mes(derivar(hist, MESES, 0.20), "4|400")
    assert got[5]["valor_baseline"] == -3000.0


def test_conta_sem_nenhum_movimento_sai_sem_base():
    got = _por_mes(derivar({"7|700": {}}, MESES, 0.0), "7|700")
    assert len(got) == 12
    assert all(l["origem"] == "sem_base" and l["valor_baseline"] == 0.0
               for l in got.values())


def test_zero_nao_conta_como_mes_com_movimento():
    # conta lançada com 0 em 10 meses e valor em 2 não é recorrente
    hist = {"5|500": {m: 0.0 for m in MESES}}
    hist["5|500"]["2026-01"] = 500.0
    hist["5|500"]["2026-02"] = 700.0
    got = _por_mes(derivar(hist, MESES, 0.0), "5|500")
    assert all(l["origem"] == "mediana" for l in got.values())
    assert all(l["meses_com_dado"] == 2 for l in got.values())


def test_todas_as_contas_recebem_12_meses():
    hist = {"1|100": {m: 1.0 for m in MESES}, "2|200": {"2026-03": 5.0}}
    linhas = derivar(hist, MESES, 0.0)
    assert len(linhas) == 24
    assert sorted({l["mes"] for l in linhas}) == list(range(1, 13))
```

- [ ] **Step 3: Rodar o teste e confirmar que falha**

Run: `uv run --with pytest python -m pytest tests/orcamento/test_derivacao.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.orcamento.derivacao'`

- [ ] **Step 4: Implementar a derivação**

Criar `api/orcamento/derivacao.py`:

```python
"""Derivação do baseline orçamentário a partir do histórico.

Método: MÊS ESPELHO + fator de tendência. Cada mês do ano orçado parte do mesmo
mês-calendário da base, o que preserva a sazonalidade real (dezembro cai ~40% na
Sulista) em vez de achatá-la numa média.

Contas esporádicas quebram o espelho: 41 das 355 contas aparecem em 1 ou 2 meses,
e espelhar isso produziria orçamento errático com aparência de número. Abaixo do
corte de recorrência a conta sai pela mediana e nasce marcada para revisão.

Módulo PURO: não conhece banco nem HTTP, para poder ser testado isolado.
"""
from __future__ import annotations

from statistics import median

# 75% dos meses da base (9 de 12). Separa as 212 contas recorrentes das 41 esporádicas.
RECORRENCIA_MIN = 0.75


def derivar(historico: dict[str, dict[str, float]],
            meses_base: list[str],
            fator: float) -> list[dict]:
    """Gera o baseline de 12 meses para cada conta.

    historico:   {conta: {'YYYY-MM': valor}} — SOMENTE meses fechados.
    meses_base:  os 'YYYY-MM' da base, em ordem cronológica.
    fator:       tendência, ex.: -0.05 para orçar 5% abaixo do espelho.

    Devolve uma linha por conta × mês (1-12) com valor, origem e cobertura.
    """
    minimo = RECORRENCIA_MIN * len(meses_base)
    # mês-calendário -> 'YYYY-MM' da base (o mais recente, se a base tiver repetição)
    espelho_de: dict[int, str] = {}
    for m in meses_base:
        espelho_de[int(m[5:7])] = m

    linhas: list[dict] = []
    for conta, serie in sorted(historico.items()):
        # valor 0 não é movimento: conta lançada zerada não vira recorrente
        com_dado = {m: v for m, v in serie.items() if m in meses_base and v}
        n = len(com_dado)
        recorrente = n >= minimo
        med = median(com_dado.values()) if com_dado else 0.0

        for mes in range(1, 13):
            fonte = espelho_de.get(mes)
            valor_espelho = com_dado.get(fonte) if fonte else None

            if recorrente and valor_espelho is not None:
                valor, origem = valor_espelho * (1 + fator), "espelho"
            elif com_dado:
                valor, origem = med * (1 + fator), "mediana"
            else:
                valor, origem = 0.0, "sem_base"

            # conta recorrente sem o mês espelho não inventa valor
            if recorrente and valor_espelho is None:
                valor, origem = 0.0, "sem_base"

            linhas.append({
                "conta": conta,
                "mes": mes,
                "valor_baseline": round(valor, 2),
                "origem": origem,
                "meses_com_dado": n,
            })
    return linhas
```

- [ ] **Step 5: Rodar os testes e confirmar que passam**

Run: `uv run --with pytest python -m pytest tests/orcamento/ -q`
Expected: PASS, 10 testes.

- [ ] **Step 6: Rodar a suíte inteira para não regredir**

Run: `uv run --with pytest python -m pytest -q`
Expected: PASS (78 anteriores + 10 novos = 88).

- [ ] **Step 7: Commit**

```bash
git add api/orcamento/ tests/orcamento/
git commit -m "Orçamento: derivação por mês espelho + tendência

Método puro, sem banco. Preserva sazonalidade (dezembro cai 40% na Sulista, o que
uma média achataria) e separa as contas esporádicas: abaixo de 75% dos meses da
base a conta sai pela mediana marcada como base fraca, porque espelhar 2 meses de
movimento produz orçamento errático com cara de número. Mês sem base sai zerado e
marcado, nunca com valor inventado."
```

---

### Task 2: Armazenamento SQLite com preservação de ajuste

**Files:**
- Create: `api/orcamento/armazenamento.py`
- Test: `tests/orcamento/test_armazenamento.py`

**Interfaces:**
- Consumes: as linhas de `derivar()` (Task 1) no formato `{"conta","mes","valor_baseline","origem","meses_com_dado"}`.
- Produces:
  - `init_db(path: Path) -> None`
  - `criar_versao(path, ano: int, rotulo: str, fator: float, quem: str) -> int`
  - `gravar_baseline(path, versao_id: int, linhas: list[dict]) -> int`
  - `ajustar(path, versao_id: int, conta: str, mes: int, valor: float | None, quem: str) -> None`
  - `ler_linhas(path, versao_id: int) -> list[dict]` — cada dict tem `valor_efetivo`
  - `listar_versoes(path, ano: int | None = None) -> list[dict]`
  - `ler_log(path, versao_id: int, limite: int = 200) -> list[dict]`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/orcamento/test_armazenamento.py`:

```python
"""Testes do armazenamento local do orçamento (SQLite)."""
from __future__ import annotations

import pytest

from api.orcamento import armazenamento as arm


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "orcamento.db"
    arm.init_db(p)
    return p


def _linhas(conta="1|100", valor=1000.0, origem="espelho"):
    return [{"conta": conta, "mes": m, "valor_baseline": valor,
             "origem": origem, "meses_com_dado": 12} for m in range(1, 13)]


def test_cria_versao_e_le_de_volta(db):
    vid = arm.criar_versao(db, 2027, "Orçamento 2027", -0.05, "cristian")
    vs = arm.listar_versoes(db, 2027)
    assert len(vs) == 1
    assert vs[0]["id"] == vid
    assert vs[0]["ano"] == 2027
    assert vs[0]["fator_tendencia"] == -0.05
    assert vs[0]["status"] == "rascunho"


def test_grava_baseline_e_valor_efetivo_cai_no_baseline(db):
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian")
    n = arm.gravar_baseline(db, vid, _linhas())
    assert n == 12
    linhas = arm.ler_linhas(db, vid)
    assert len(linhas) == 12
    assert all(l["valor_efetivo"] == 1000.0 for l in linhas)
    assert all(l["valor_ajustado"] is None for l in linhas)


def test_ajuste_sobrepoe_o_baseline(db):
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian")
    arm.gravar_baseline(db, vid, _linhas())
    arm.ajustar(db, vid, "1|100", 3, 7777.0, "cristian")
    m3 = next(l for l in arm.ler_linhas(db, vid) if l["mes"] == 3)
    assert m3["valor_ajustado"] == 7777.0
    assert m3["valor_baseline"] == 1000.0
    assert m3["valor_efetivo"] == 7777.0


def test_regerar_baseline_preserva_o_ajuste_manual(db):
    """O requisito central: recalcular não pode jogar fora o trabalho da controladoria."""
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian")
    arm.gravar_baseline(db, vid, _linhas(valor=1000.0))
    arm.ajustar(db, vid, "1|100", 3, 7777.0, "cristian")

    arm.gravar_baseline(db, vid, _linhas(valor=2000.0))   # regera com outro fator

    m3 = next(l for l in arm.ler_linhas(db, vid) if l["mes"] == 3)
    assert m3["valor_baseline"] == 2000.0    # baseline atualizou
    assert m3["valor_ajustado"] == 7777.0    # ajuste sobreviveu
    assert m3["valor_efetivo"] == 7777.0
    m4 = next(l for l in arm.ler_linhas(db, vid) if l["mes"] == 4)
    assert m4["valor_efetivo"] == 2000.0     # sem ajuste, segue o baseline novo


def test_limpar_ajuste_volta_para_o_baseline(db):
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian")
    arm.gravar_baseline(db, vid, _linhas())
    arm.ajustar(db, vid, "1|100", 3, 7777.0, "cristian")
    arm.ajustar(db, vid, "1|100", 3, None, "cristian")
    m3 = next(l for l in arm.ler_linhas(db, vid) if l["mes"] == 3)
    assert m3["valor_ajustado"] is None
    assert m3["valor_efetivo"] == 1000.0


def test_cada_ajuste_vira_linha_de_auditoria(db):
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian")
    arm.gravar_baseline(db, vid, _linhas())
    arm.ajustar(db, vid, "1|100", 3, 7777.0, "cristian")
    arm.ajustar(db, vid, "1|100", 3, 8888.0, "ana")
    log = arm.ler_log(db, vid)
    assert len(log) == 2
    assert log[0]["quem"] == "ana"            # mais recente primeiro
    assert log[0]["valor_de"] == 7777.0
    assert log[0]["valor_para"] == 8888.0
    assert log[1]["valor_de"] == 1000.0       # primeiro ajuste partiu do baseline
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run --with pytest python -m pytest tests/orcamento/test_armazenamento.py -q`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar o armazenamento**

Criar `api/orcamento/armazenamento.py`:

```python
"""Persistência local do orçamento (SQLite).

O ERP AVA é réplica somente-leitura, então o orçamento é dado nosso. Segue o
padrão de `api/auth.py`: conexão curta com commit automático e WAL.

Regra central: `valor_efetivo = coalesce(valor_ajustado, valor_baseline)`.
Regerar o baseline recalcula APENAS `valor_baseline` — o ajuste manual sobrevive,
senão recalcular jogaria fora o trabalho da controladoria.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "orcamento.db"


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
        CREATE TABLE IF NOT EXISTS orc_versao(
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ano             INTEGER NOT NULL,
            rotulo          TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'rascunho',
            fator_tendencia REAL    NOT NULL DEFAULT 0,
            criado_em       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            criado_por      TEXT
        );
        CREATE TABLE IF NOT EXISTS orc_linha(
            versao_id      INTEGER NOT NULL REFERENCES orc_versao(id) ON DELETE CASCADE,
            conta          TEXT    NOT NULL,
            mes            INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
            valor_baseline REAL    NOT NULL DEFAULT 0,
            valor_ajustado REAL,
            origem         TEXT    NOT NULL DEFAULT 'sem_base',
            meses_com_dado INTEGER NOT NULL DEFAULT 0,
            ajustado_em    TEXT,
            ajustado_por   TEXT,
            PRIMARY KEY (versao_id, conta, mes)
        );
        CREATE TABLE IF NOT EXISTS orc_log(
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            versao_id  INTEGER NOT NULL,
            conta      TEXT    NOT NULL,
            mes        INTEGER NOT NULL,
            valor_de   REAL,
            valor_para REAL,
            quem       TEXT,
            quando     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS ix_orc_linha_versao ON orc_linha(versao_id);
        CREATE INDEX IF NOT EXISTS ix_orc_log_versao   ON orc_log(versao_id, id DESC);
        """)


def criar_versao(path: Path, ano: int, rotulo: str, fator: float, quem: str) -> int:
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO orc_versao(ano, rotulo, fator_tendencia, criado_por) "
            "VALUES (?,?,?,?)", (ano, rotulo, fator, quem))
        return int(cur.lastrowid)


def gravar_baseline(path: Path, versao_id: int, linhas: list[dict]) -> int:
    """Insere ou atualiza o baseline. NÃO toca em valor_ajustado."""
    with _conn(path) as c:
        c.executemany("""
            INSERT INTO orc_linha(versao_id, conta, mes, valor_baseline, origem, meses_com_dado)
            VALUES (:v, :conta, :mes, :valor_baseline, :origem, :meses_com_dado)
            ON CONFLICT(versao_id, conta, mes) DO UPDATE SET
                valor_baseline = excluded.valor_baseline,
                origem         = excluded.origem,
                meses_com_dado = excluded.meses_com_dado
        """, [{**l, "v": versao_id} for l in linhas])
        return len(linhas)


def ajustar(path: Path, versao_id: int, conta: str, mes: int,
            valor: float | None, quem: str) -> None:
    """Grava (ou limpa, com valor=None) o ajuste manual de uma célula."""
    with _conn(path) as c:
        row = c.execute(
            "SELECT valor_baseline, valor_ajustado FROM orc_linha "
            "WHERE versao_id=? AND conta=? AND mes=?", (versao_id, conta, mes)).fetchone()
        if row is None:
            raise KeyError(f"linha inexistente: versao={versao_id} conta={conta} mes={mes}")
        de = row["valor_ajustado"] if row["valor_ajustado"] is not None else row["valor_baseline"]
        c.execute(
            "UPDATE orc_linha SET valor_ajustado=?, "
            "ajustado_em=datetime('now','localtime'), ajustado_por=? "
            "WHERE versao_id=? AND conta=? AND mes=?", (valor, quem, versao_id, conta, mes))
        c.execute(
            "INSERT INTO orc_log(versao_id, conta, mes, valor_de, valor_para, quem) "
            "VALUES (?,?,?,?,?,?)", (versao_id, conta, mes, de, valor, quem))


def ler_linhas(path: Path, versao_id: int) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute("""
            SELECT conta, mes, valor_baseline, valor_ajustado, origem, meses_com_dado,
                   ajustado_em, ajustado_por,
                   coalesce(valor_ajustado, valor_baseline) AS valor_efetivo
            FROM orc_linha WHERE versao_id=? ORDER BY conta, mes
        """, (versao_id,)).fetchall()
        return [dict(r) for r in rows]


def listar_versoes(path: Path, ano: int | None = None) -> list[dict]:
    sql = "SELECT * FROM orc_versao"
    par: tuple = ()
    if ano is not None:
        sql += " WHERE ano=?"
        par = (ano,)
    sql += " ORDER BY ano DESC, id DESC"
    with _conn(path) as c:
        return [dict(r) for r in c.execute(sql, par).fetchall()]


def ler_log(path: Path, versao_id: int, limite: int = 200) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute(
            "SELECT * FROM orc_log WHERE versao_id=? ORDER BY id DESC LIMIT ?",
            (versao_id, limite)).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `uv run --with pytest python -m pytest tests/orcamento/ -q`
Expected: PASS, 16 testes.

- [ ] **Step 5: Garantir que o .db não vá para o git**

Run: `grep -n 'data/' .gitignore`
Se `data/*.db` não estiver coberto, acrescentar:

```bash
printf 'data/orcamento.db\ndata/orcamento.db-wal\ndata/orcamento.db-shm\n' >> .gitignore
```

- [ ] **Step 6: Commit**

```bash
git add api/orcamento/armazenamento.py tests/orcamento/test_armazenamento.py .gitignore
git commit -m "Orçamento: armazenamento local em SQLite com preservação de ajuste

O ERP é réplica somente-leitura, então o orçamento mora em data/orcamento.db,
no padrão do auth.db. Regerar o baseline atualiza só valor_baseline e mantém
valor_ajustado — sem isso, recalcular apagaria o trabalho da controladoria.
Todo ajuste vira linha de auditoria com valor de/para e autor."
```

---

### Task 3: SQL do histórico e do realizado por conta

**Files:**
- Create: `api/orcamento/sql.py`
- Test: `tests/orcamento/test_sql.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces:
  - `HIST_CONTA_SQL: str` — params `%(de)s`, `%(ate)s`; colunas `conta, mes, valor`
  - `REAL_CONTA_SQL: str` — params `%(de)s`, `%(ate)s`; colunas `conta, mes, valor`
  - `AGRUP_CONTA_SQL: str` — sem params; colunas `conta, agrupador`
  - `meses_fechados(hoje: date, n: int = 12) -> list[str]` — os n meses `YYYY-MM` anteriores ao mês corrente

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/orcamento/test_sql.py`:

```python
"""Testes da montagem do SQL e da janela de meses fechados."""
from __future__ import annotations

from datetime import date

from api.orcamento.sql import (AGRUP_CONTA_SQL, HIST_CONTA_SQL, REAL_CONTA_SQL,
                               meses_fechados)


def test_mes_corrente_nunca_entra_na_base():
    # em 26/07/2026 a base termina em junho: julho está pela metade
    ms = meses_fechados(date(2026, 7, 26), 12)
    assert ms[-1] == "2026-06"
    assert "2026-07" not in ms
    assert len(ms) == 12
    assert ms[0] == "2025-07"


def test_janela_atravessa_a_virada_do_ano():
    ms = meses_fechados(date(2026, 1, 15), 12)
    assert ms[-1] == "2025-12"
    assert ms[0] == "2025-01"


def test_primeiro_dia_do_mes_tambem_exclui_o_corrente():
    ms = meses_fechados(date(2026, 3, 1), 3)
    assert ms == ["2025-12", "2026-01", "2026-02"]


def test_sql_nao_usa_recursos_ausentes_no_postgres_93():
    for sql in (HIST_CONTA_SQL, REAL_CONTA_SQL, AGRUP_CONTA_SQL):
        assert "FILTER (WHERE" not in sql.upper()
        assert "LATERAL" not in sql.upper()


def test_sql_trata_o_lado_nulo_do_lancamento():
    # valorcredito/valordebito vêm NULL no lado vazio: sem coalesce a linha some
    for sql in (HIST_CONTA_SQL, REAL_CONTA_SQL):
        assert "coalesce(l.valorcredito,0)" in sql
        assert "coalesce(l.valordebito,0)" in sql
        assert "coalesce(l.historico, 0) <> 18" in sql


def test_sql_usa_a_mesma_chave_de_conta_da_dre():
    for sql in (HIST_CONTA_SQL, REAL_CONTA_SQL, AGRUP_CONTA_SQL):
        assert "l.grupo::text || '|' || l.reduzido::text" in sql or \
               "ag.grupo::text || '|' || ag.reduzido::text" in sql
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run --with pytest python -m pytest tests/orcamento/test_sql.py -q`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar**

Criar `api/orcamento/sql.py`:

```python
"""SQL do módulo orçamentário — histórico, realizado e mapa de agrupador.

A chave de conta é `grupo|reduzido`, a MESMA que a DRE Gerencial (DRE_AG_SQL) e a
tela de Contabilidade usam. Isso garante que reclassificar uma conta mova orçado e
realizado juntos, sem abrir divergência entre as telas.

PostgreSQL 9.3: nada de FILTER/LATERAL. `%` é reservado pelo psycopg, então os
prefixos de estrutural usam position(...)=1 em vez de LIKE.
"""
from __future__ import annotations

from datetime import date

# Base compartilhada: mesmos filtros de DRE_AG_SQL (ver api/queries.py).
_BASE = """
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  AND p.ativoinativo = 1
LEFT JOIN sulista.agrupadorgerencial ag ON ag.reduzido = l.reduzido
  AND ag.grupo = l.grupo
WHERE l.dtlancamento >= %(de)s::date AND l.dtlancamento < %(ate)s::date
  AND coalesce(l.historico, 0) <> 18
  AND (ag.descricao IS NOT NULL OR position('3' in p.estrutural) = 1
       OR position('4' in p.estrutural) = 1)
"""

_SELECT = """
SELECT l.grupo::text || '|' || l.reduzido::text AS conta,
       to_char(l.dtlancamento,'YYYY-MM') AS mes,
       sum(coalesce(l.valorcredito,0) - coalesce(l.valordebito,0))::float8 AS valor
"""

# Histórico para derivar o baseline (meses fechados).
HIST_CONTA_SQL = _SELECT + _BASE + " GROUP BY 1, 2"

# Realizado do ano orçado. Mesma forma: o consumidor recorta o intervalo.
REAL_CONTA_SQL = _SELECT + _BASE + " GROUP BY 1, 2"

# Conta -> agrupador gerencial, para o rollup até a linha da DRE.
AGRUP_CONTA_SQL = """
SELECT ag.grupo::text || '|' || ag.reduzido::text AS conta,
       ag.descricao AS agrupador
FROM sulista.agrupadorgerencial ag
WHERE ag.descricao IS NOT NULL
"""


def meses_fechados(hoje: date, n: int = 12) -> list[str]:
    """Os n meses 'YYYY-MM' anteriores ao mês corrente, em ordem cronológica.

    O mês corrente NUNCA entra: em jul/26 o custo variável aparece pela metade
    (R$ 3,4 mi contra R$ 6,5 mi normais) e contaminaria todo o baseline.
    """
    ano, mes = hoje.year, hoje.month
    saida: list[str] = []
    for _ in range(n):
        mes -= 1
        if mes == 0:
            mes, ano = 12, ano - 1
        saida.append(f"{ano:04d}-{mes:02d}")
    return list(reversed(saida))
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `uv run --with pytest python -m pytest tests/orcamento/ -q`
Expected: PASS, 22 testes.

- [ ] **Step 5: Validar o SQL contra o banco real**

Run:

```bash
uv run --with 'psycopg[binary,pool]' --with python-dotenv python -c "
import sys; sys.path.insert(0,'.')
from api.db import query
from api.orcamento.sql import HIST_CONTA_SQL, AGRUP_CONTA_SQL, meses_fechados
from datetime import date
ms = meses_fechados(date.today(), 12)
r = query(HIST_CONTA_SQL, {'de': ms[0]+'-01', 'ate': ms[-1][:4]+'-'+ms[-1][5:7]+'-01'})
print('linhas historico:', len(r), '| contas:', len({x[\"conta\"] for x in r}))
a = query(AGRUP_CONTA_SQL)
print('mapa agrupador:', len(a), 'contas')
"
```

Expected: ~350 contas no histórico e o mapa de agrupador com centenas de linhas, **sem erro de sintaxe**.
Se o túnel estiver fora do ar: `pgrep -f 'ssh.*15432'` e reiniciar o LaunchAgent antes de repetir.

- [ ] **Step 6: Commit**

```bash
git add api/orcamento/sql.py tests/orcamento/test_sql.py
git commit -m "Orçamento: SQL do histórico e do realizado por conta

Chave grupo|reduzido, a mesma da DRE Gerencial e da tela de Contabilidade, para
que reclassificar conta mova orçado e realizado juntos. meses_fechados() exclui
sempre o mês corrente — jul/26 tem custo variável pela metade e contaminaria o
baseline inteiro. Sem FILTER/LATERAL (PG 9.3) e sem % literal (reservado pelo
psycopg)."
```

---

### Task 4: Rollup conta → agrupador → linha da DRE

**Files:**
- Create: `api/orcamento/rollup.py`
- Test: `tests/orcamento/test_rollup.py`

**Interfaces:**
- Consumes: `AGRUP_CONTA_SQL` (Task 3) fornece `{conta: agrupador}`.
- Produces:
  - `linha_da_conta(conta, agrupador_por_conta, ajustes) -> str | None`
  - `mapa_conta_linha(agrupador_por_conta, ajustes) -> dict[str, str | None]`
  - `contas_sem_agrupador(contas, agrupador_por_conta, ajustes) -> list[str]`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/orcamento/test_rollup.py`:

```python
"""Testes do rollup conta -> agrupador -> linha da DRE."""
from __future__ import annotations

from api.orcamento.rollup import (contas_sem_agrupador, linha_da_conta,
                                  mapa_conta_linha)

AGRUP = {
    "1|100": "CV - COMBUSTIVEL",
    "1|101": "CF - LOCACAO DE EQUIPAMENTOS",
    "1|102": "OVERHEAD - DESPESAS ADM",
    "1|103": "RECEITA OPERACIONAL BRUTA",
    "1|104": "IMPOSTOS FEDERAIS",
}


def test_conta_cai_na_linha_certa_da_cascata():
    assert linha_da_conta("1|100", AGRUP, {}) == "CUSTO VARIAVEL"
    assert linha_da_conta("1|101", AGRUP, {}) == "CUSTO FIXO"
    assert linha_da_conta("1|102", AGRUP, {}) == "OVERHEAD"
    assert linha_da_conta("1|103", AGRUP, {}) == "RECEITA BRUTA"
    assert linha_da_conta("1|104", AGRUP, {}) == "IMPOSTOS FEDERAIS"


def test_ajuste_contabil_local_muda_a_linha():
    """Reclassificar na tela de Contabilidade tem de mover o orçado junto."""
    ajustes = {"1|100": {"agrupador": "CF - LOCACAO DE EQUIPAMENTOS"}}
    assert linha_da_conta("1|100", AGRUP, ajustes) == "CUSTO FIXO"


def test_conta_sem_agrupador_nao_tem_linha():
    assert linha_da_conta("9|999", AGRUP, {}) is None


def test_mapa_cobre_todas_as_contas_conhecidas():
    m = mapa_conta_linha(AGRUP, {})
    assert set(m) == set(AGRUP)
    assert m["1|100"] == "CUSTO VARIAVEL"


def test_lista_as_contas_que_precisam_ser_classificadas():
    contas = ["1|100", "9|998", "9|999"]
    assert contas_sem_agrupador(contas, AGRUP, {}) == ["9|998", "9|999"]


def test_ajuste_resolve_conta_antes_sem_agrupador():
    ajustes = {"9|999": {"agrupador": "CV - MANUTENCAO"}}
    assert contas_sem_agrupador(["9|999"], AGRUP, ajustes) == []
    assert linha_da_conta("9|999", AGRUP, ajustes) == "CUSTO VARIAVEL"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run --with pytest python -m pytest tests/orcamento/test_rollup.py -q`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar**

Criar `api/orcamento/rollup.py`:

```python
"""Rollup conta -> agrupador -> linha da cascata da DRE.

Reusa `_dre_aloca` de api/queries.py, que é exatamente o mapeamento que a DRE
Gerencial já usa (DRE_MODELO). Aplicar aqui os mesmos ajustes contábeis locais
garante que reclassificar uma conta mova orçado e realizado juntos — sem isso as
duas telas divergiriam e ninguém saberia qual está certa.
"""
from __future__ import annotations

from api.queries import _dre_aloca


def _agrupador(conta: str, agrupador_por_conta: dict[str, str],
               ajustes: dict) -> str | None:
    aj = ajustes.get(conta)
    if aj and aj.get("agrupador"):
        return aj["agrupador"]
    return agrupador_por_conta.get(conta)


def linha_da_conta(conta: str, agrupador_por_conta: dict[str, str],
                   ajustes: dict) -> str | None:
    """Rótulo da linha do DRE_MODELO onde a conta soma, ou None se não classificada."""
    ag = _agrupador(conta, agrupador_por_conta, ajustes)
    if not ag:
        return None
    return _dre_aloca(ag)


def mapa_conta_linha(agrupador_por_conta: dict[str, str],
                     ajustes: dict) -> dict[str, str | None]:
    contas = set(agrupador_por_conta) | set(ajustes)
    return {c: linha_da_conta(c, agrupador_por_conta, ajustes) for c in sorted(contas)}


def contas_sem_agrupador(contas: list[str], agrupador_por_conta: dict[str, str],
                         ajustes: dict) -> list[str]:
    """Contas que não somam em linha nenhuma — precisam ser classificadas antes."""
    return [c for c in contas if not _agrupador(c, agrupador_por_conta, ajustes)]
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `uv run --with pytest python -m pytest tests/orcamento/ -q`
Expected: PASS, 28 testes.

Se `test_conta_cai_na_linha_certa_da_cascata` falhar, imprimir o que `_dre_aloca` devolve para cada agrupador do fixture e alinhar o teste ao `DRE_MODELO` real — o modelo é a fonte da verdade, o teste é que se ajusta:

```bash
uv run python -c "
import sys; sys.path.insert(0,'.')
from api.queries import _dre_aloca
for a in ['CV - COMBUSTIVEL','CF - LOCACAO DE EQUIPAMENTOS','OVERHEAD - DESPESAS ADM','RECEITA OPERACIONAL BRUTA','IMPOSTOS FEDERAIS']:
    print(f'{a:32} -> {_dre_aloca(a)}')"
```

- [ ] **Step 5: Commit**

```bash
git add api/orcamento/rollup.py tests/orcamento/test_rollup.py
git commit -m "Orçamento: rollup conta -> agrupador -> linha da DRE

Reusa _dre_aloca e aplica os mesmos ajustes contábeis locais que a DRE Gerencial,
para que reclassificar uma conta mova orçado e realizado juntos. Conta sem
agrupador devolve None e entra na lista de pendências em vez de sumir num total."
```

---

### Task 5: Orquestração e endpoints

**Files:**
- Create: `api/orcamento/servico.py`
- Modify: `api/orcamento/__init__.py`
- Modify: `api/main.py` (acrescentar endpoints ao final do bloco de Controladoria)
- Modify: `api/auth.py` (TELAS e ROTA_TELAS)
- Test: `tests/orcamento/test_servico.py`

**Interfaces:**
- Consumes: `derivar` (T1), `armazenamento.*` (T2), `HIST_CONTA_SQL`/`REAL_CONTA_SQL`/`AGRUP_CONTA_SQL`/`meses_fechados` (T3), `mapa_conta_linha`/`contas_sem_agrupador` (T4).
- Produces:
  - `montar_comparativo(linhas_orc, realizado, mapa_linha, ate_mes) -> dict`
  - `meses_faltando(historico, meses) -> list[str]`
  - `gerar(ano, rotulo, fator, quem) -> dict`
  - `comparativo(versao_id, ate_mes) -> dict`
  - Endpoints: `GET /api/controladoria/orcamento`, `GET /api/controladoria/orcamento/versoes`, `POST /api/controladoria/orcamento/gerar`, `POST /api/controladoria/orcamento/ajustar`

- [ ] **Step 1: Escrever o teste que falha (só a parte pura da agregação)**

Criar `tests/orcamento/test_servico.py`:

```python
"""Testes da agregação orçado x realizado por linha da DRE."""
from __future__ import annotations

from api.orcamento.servico import montar_comparativo

MAPA = {"1|100": "CUSTO VARIAVEL", "1|101": "CUSTO VARIAVEL",
        "1|103": "RECEITA BRUTA", "9|999": None}


def _orc(conta, mes, valor):
    return {"conta": conta, "mes": mes, "valor_efetivo": valor,
            "valor_baseline": valor, "valor_ajustado": None,
            "origem": "espelho", "meses_com_dado": 12}


def test_soma_orcado_e_realizado_por_linha_ate_o_mes():
    linhas_orc = [_orc("1|100", m, -1000.0) for m in range(1, 13)]
    linhas_orc += [_orc("1|103", m, 5000.0) for m in range(1, 13)]
    realizado = {("1|100", 1): -900.0, ("1|100", 2): -1200.0,
                 ("1|103", 1): 4000.0, ("1|103", 2): 4000.0}
    r = montar_comparativo(linhas_orc, realizado, MAPA, ate_mes=2)
    por_linha = {l["linha"]: l for l in r["linhas"]}
    assert por_linha["CUSTO VARIAVEL"]["orcado"] == -2000.0
    assert por_linha["CUSTO VARIAVEL"]["realizado"] == -2100.0
    assert por_linha["RECEITA BRUTA"]["orcado"] == 10000.0
    assert por_linha["RECEITA BRUTA"]["realizado"] == 8000.0


def test_desvio_de_custo_acima_do_orcado_e_desfavoravel():
    """Custo realizado maior que o orçado estoura: favoravel=False."""
    linhas_orc = [_orc("1|100", 1, -1000.0)]
    r = montar_comparativo(linhas_orc, {("1|100", 1): -1300.0}, MAPA, ate_mes=1)
    cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert cv["desvio"] == -300.0
    assert cv["favoravel"] is False


def test_custo_abaixo_do_orcado_e_favoravel():
    linhas_orc = [_orc("1|100", 1, -1000.0)]
    r = montar_comparativo(linhas_orc, {("1|100", 1): -700.0}, MAPA, ate_mes=1)
    cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert cv["desvio"] == 300.0
    assert cv["favoravel"] is True


def test_receita_abaixo_do_orcado_e_desfavoravel():
    linhas_orc = [_orc("1|103", 1, 5000.0)]
    r = montar_comparativo(linhas_orc, {("1|103", 1): 4000.0}, MAPA, ate_mes=1)
    rb = next(l for l in r["linhas"] if l["linha"] == "RECEITA BRUTA")
    assert rb["desvio"] == -1000.0
    assert rb["favoravel"] is False


def test_conta_sem_linha_nao_entra_no_total_e_e_reportada():
    linhas_orc = [_orc("1|100", 1, -1000.0), _orc("9|999", 1, -500.0)]
    r = montar_comparativo(linhas_orc, {}, MAPA, ate_mes=1)
    total_cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert total_cv["orcado"] == -1000.0
    assert "9|999" in r["sem_linha"]


def test_meses_depois_do_corte_ficam_fora_do_acumulado():
    linhas_orc = [_orc("1|100", m, -1000.0) for m in range(1, 13)]
    r = montar_comparativo(linhas_orc, {}, MAPA, ate_mes=3)
    cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert cv["orcado"] == -3000.0


def test_meses_faltando_na_base_sao_reportados():
    """Derivar espelho sobre base furada viraria zero com cara de orçamento."""
    from api.orcamento.servico import meses_faltando

    meses = ["2025-08", "2025-09", "2025-10"]
    hist = {"1|100": {"2025-08": 1.0}, "2|200": {"2025-09": 2.0}}
    assert meses_faltando(hist, meses) == ["2025-10"]


def test_base_completa_nao_reporta_falta():
    from api.orcamento.servico import meses_faltando

    meses = ["2025-08", "2025-09"]
    hist = {"1|100": {"2025-08": 1.0}, "2|200": {"2025-09": 2.0}}
    assert meses_faltando(hist, meses) == []


def test_serie_mensal_marca_o_mes_sem_realizado():
    """Mês sem realizado não pode virar barra zerada no gráfico."""
    linhas_orc = [_orc("1|100", m, -1000.0) for m in range(1, 13)]
    r = montar_comparativo(linhas_orc, {("1|100", 1): -900.0}, MAPA, ate_mes=1)
    serie = {s["mes"]: s for s in r["mensal"]}
    assert serie[1]["realizado"] == -900.0
    assert serie[1]["fechado"] is True
    assert serie[5]["realizado"] is None
    assert serie[5]["fechado"] is False
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run --with pytest python -m pytest tests/orcamento/test_servico.py -q`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar a agregação pura**

Criar `api/orcamento/servico.py`:

```python
"""Orquestração do módulo orçamentário: deriva, grava e compara.

A parte pura (montar_comparativo) fica separada do acesso a dados para poder ser
testada sem banco.
"""
from __future__ import annotations

from datetime import date

from api import db
from api.orcamento import armazenamento as arm
from api.orcamento.derivacao import derivar
from api.orcamento.rollup import contas_sem_agrupador, mapa_conta_linha
from api.orcamento.sql import (AGRUP_CONTA_SQL, HIST_CONTA_SQL, REAL_CONTA_SQL,
                               meses_fechados)
from api.queries import DRE_MODELO, ler_ajustes

# Linhas da cascata em que MENOS é melhor (custo/despesa): desvio positivo é bom.
_LINHAS_CUSTO = {"CSP", "CUSTO FIXO", "CUSTO VARIAVEL", "DESPESAS", "OVERHEAD",
                 "INDENIZACOES", "OUTRAS DESPESAS/RECEITAS OPERACIONAIS",
                 "DEDUCOES DA RECEITA", "IMPOSTOS FEDERAIS", "IMPOSTOS ESTADUAIS",
                 "IMPOSTOS MUNICIPAIS", "CONTRIBUICAO PREVIDENCIARIA",
                 "ANULACOES", "DESCONTOS"}


def montar_comparativo(linhas_orc: list[dict], realizado: dict,
                       mapa_linha: dict, ate_mes: int) -> dict:
    """Agrega orçado e realizado por linha da DRE até `ate_mes` (inclusive).

    linhas_orc: saída de armazenamento.ler_linhas()
    realizado:  {(conta, mes): valor}
    mapa_linha: {conta: rótulo da linha DRE | None}
    """
    por_linha: dict[str, dict] = {}
    por_conta: dict[str, dict] = {}
    mensal: dict[int, dict] = {m: {"mes": m, "orcado": 0.0, "realizado": None,
                                   "fechado": m <= ate_mes} for m in range(1, 13)}
    sem_linha: set[str] = set()

    for l in linhas_orc:
        conta, mes = l["conta"], l["mes"]
        orc = l["valor_efetivo"] or 0.0
        mensal[mes]["orcado"] += orc
        if mes <= ate_mes:
            real = realizado.get((conta, mes))
            if real is not None:
                if mensal[mes]["realizado"] is None:
                    mensal[mes]["realizado"] = 0.0
                mensal[mes]["realizado"] += real

        rot = mapa_linha.get(conta)
        if rot is None:
            sem_linha.add(conta)
            continue
        if mes > ate_mes:
            continue

        alvo = por_linha.setdefault(rot, {"linha": rot, "orcado": 0.0, "realizado": 0.0})
        alvo["orcado"] += orc
        alvo["realizado"] += realizado.get((conta, mes), 0.0)

        c = por_conta.setdefault(conta, {"conta": conta, "linha": rot,
                                         "orcado": 0.0, "realizado": 0.0,
                                         "origem": l["origem"]})
        c["orcado"] += orc
        c["realizado"] += realizado.get((conta, mes), 0.0)

    def _fecha(d: dict) -> dict:
        d["desvio"] = d["realizado"] - d["orcado"]
        base = abs(d["orcado"])
        d["desvio_pct"] = (100.0 * d["desvio"] / base) if base else None
        # custo: desvio positivo (gastou menos, valor menos negativo) é favorável
        d["favoravel"] = d["desvio"] >= 0
        return d

    linhas = [_fecha(v) for v in por_linha.values()]
    contas = [_fecha(v) for v in por_conta.values()]
    ordem = {rot: i for i, (rot, _n, _t, _s) in enumerate(DRE_MODELO)}
    linhas.sort(key=lambda x: ordem.get(x["linha"], 999))
    contas.sort(key=lambda x: abs(x["desvio"]), reverse=True)

    return {
        "linhas": linhas,
        "contas": contas,
        "mensal": [mensal[m] for m in range(1, 13)],
        "sem_linha": sorted(sem_linha),
        "ate_mes": ate_mes,
    }


def meses_faltando(historico: dict[str, dict[str, float]],
                   meses: list[str]) -> list[str]:
    """Meses da base sem nenhum lançamento em conta alguma. Função pura."""
    presentes = {m for serie in historico.values() for m in serie}
    return [m for m in meses if m not in presentes]


def _historico(meses: list[str]) -> dict[str, dict[str, float]]:
    de = f"{meses[0]}-01"
    ate_ano, ate_mes = int(meses[-1][:4]), int(meses[-1][5:7])
    ate_mes += 1
    if ate_mes == 13:
        ate_mes, ate_ano = 1, ate_ano + 1
    ate = f"{ate_ano:04d}-{ate_mes:02d}-01"
    rows = db.query(HIST_CONTA_SQL, {"de": de, "ate": ate})
    hist: dict[str, dict[str, float]] = {}
    for r in rows:
        hist.setdefault(r["conta"], {})[r["mes"]] = r["valor"]
    return hist


def _mapa() -> tuple[dict, dict]:
    rows = db.query(AGRUP_CONTA_SQL)
    agrup = {r["conta"]: r["agrupador"] for r in rows}
    return agrup, ler_ajustes()


def gerar(ano: int, rotulo: str, fator: float, quem: str,
          path=arm.DB_PATH, hoje: date | None = None) -> dict:
    """Deriva o baseline do ano e grava numa versão nova."""
    hoje = hoje or date.today()
    meses = meses_fechados(hoje, 12)
    hist = _historico(meses)
    if not hist:
        raise ValueError("Sem histórico fechado para derivar o baseline.")
    # a spec exige bloquear quando a base não tem os 12 meses fechados: derivar mês
    # espelho sobre uma base incompleta produziria zeros disfarçados de orçamento
    faltam = meses_faltando(hist, meses)
    if faltam:
        raise ValueError(
            f"A base precisa de {len(meses)} meses fechados e faltam {len(faltam)}: "
            + ", ".join(faltam))
    linhas = derivar(hist, meses, fator)

    agrup, ajustes = _mapa()
    pendentes = contas_sem_agrupador(sorted(hist), agrup, ajustes)
    # conta sem agrupador não soma em linha nenhuma: fica fora e é reportada
    linhas = [l for l in linhas if l["conta"] not in set(pendentes)]

    arm.init_db(path)
    vid = arm.criar_versao(path, ano, rotulo, fator, quem)
    arm.gravar_baseline(path, vid, linhas)
    return {"versao_id": vid, "linhas": len(linhas), "meses_base": meses,
            "contas_sem_agrupador": pendentes}


def comparativo(versao_id: int, ate_mes: int | None = None,
                path=arm.DB_PATH, hoje: date | None = None) -> dict:
    """Orçado x realizado da versão, acumulado até o último mês fechado."""
    hoje = hoje or date.today()
    versoes = {v["id"]: v for v in arm.listar_versoes(path)}
    if versao_id not in versoes:
        raise KeyError(f"versão inexistente: {versao_id}")
    v = versoes[versao_id]
    ano = v["ano"]

    if ate_mes is None:
        ate_mes = (hoje.month - 1) if hoje.year == ano else (12 if hoje.year > ano else 0)
    ate_mes = max(0, min(12, ate_mes))

    linhas_orc = arm.ler_linhas(path, versao_id)
    realizado: dict = {}
    if ate_mes > 0:
        fim_ano, fim_mes = (ano, ate_mes + 1) if ate_mes < 12 else (ano + 1, 1)
        rows = db.query(REAL_CONTA_SQL, {"de": f"{ano}-01-01",
                                         "ate": f"{fim_ano:04d}-{fim_mes:02d}-01"})
        for r in rows:
            realizado[(r["conta"], int(r["mes"][5:7]))] = r["valor"]

    agrup, ajustes = _mapa()
    mapa = mapa_conta_linha(agrup, ajustes)
    out = montar_comparativo(linhas_orc, realizado, mapa, ate_mes)
    out["versao"] = dict(v)
    out["fonte"] = ("Orçado: data/orcamento.db (baseline derivado + ajustes). "
                    "Realizado: ERP AVA, lancamento x planoconta, mesma base da DRE.")
    return out
```

- [ ] **Step 4: Expor a API pública do pacote**

Substituir `api/orcamento/__init__.py` por:

```python
"""Módulo orçamentário do Cortex (Fase 1: derivar, ajustar e acompanhar)."""
from api.orcamento.servico import comparativo, gerar, montar_comparativo

__all__ = ["comparativo", "gerar", "montar_comparativo"]
```

- [ ] **Step 5: Rodar os testes e confirmar que passam**

Run: `uv run --with pytest python -m pytest tests/orcamento/ -q`
Expected: PASS, 37 testes.

- [ ] **Step 6: Registrar a tela no controle de acesso**

Em `api/auth.py`, no dicionário `TELAS`, logo após a linha de `"qual"`:

```python
    "orc":     ("Orçamento", "Controladoria"),
```

No `ROTA_TELAS`, **antes** de `("/api/financeiro/dre", ...)` para não haver conflito de prefixo:

```python
    ("/api/controladoria/orcamento", frozenset({"orc"})),
```

E no perfil padrão "Controladoria", acrescentar `"orc"` à lista:

```python
     ["dre", "cont", "drecli", "qual", "orc"]),
```

- [ ] **Step 7: Acrescentar os endpoints**

Em `api/main.py`, junto dos demais endpoints de Controladoria:

```python
@app.get("/api/controladoria/orcamento/versoes")
def orcamento_versoes(ano: int | None = None) -> JSONResponse:
    from api.orcamento import armazenamento as arm
    try:
        arm.init_db(arm.DB_PATH)
        return JSONResponse({"versoes": arm.listar_versoes(arm.DB_PATH, ano)})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento_versoes falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao listar as versões do orçamento."})


@app.get("/api/controladoria/orcamento")
def orcamento(versao_id: int | None = None, ate_mes: int | None = None) -> JSONResponse:
    from api.orcamento import armazenamento as arm
    from api.orcamento.servico import comparativo
    if ate_mes is not None and not (0 <= ate_mes <= 12):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "ate_mes deve estar entre 0 e 12."})
    try:
        arm.init_db(arm.DB_PATH)
        if versao_id is None:
            vs = arm.listar_versoes(arm.DB_PATH)
            if not vs:
                return JSONResponse({"vazio": True,
                                     "mensagem": "Nenhuma versão de orçamento criada ainda."})
            versao_id = vs[0]["id"]
        return JSONResponse(comparativo(versao_id, ate_mes))
    except KeyError:
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": "Versão de orçamento inexistente."})
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar o orçamento."})


@app.post("/api/controladoria/orcamento/gerar")
async def orcamento_gerar(req: Request) -> JSONResponse:
    from api.orcamento.servico import gerar
    body = await req.json()
    ano = body.get("ano")
    fator = body.get("fator", 0.0)
    rotulo = (body.get("rotulo") or f"Orçamento {ano}").strip()
    if not isinstance(ano, int) or not (2020 <= ano <= 2100):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe um ano entre 2020 e 2100."})
    if not isinstance(fator, (int, float)) or not (-0.9 <= fator <= 3.0):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "O fator de tendência deve estar entre -0,9 e 3,0."})
    try:
        quem = getattr(req.state, "usuario_nome", None) or "sistema"
        return JSONResponse(gerar(ano, rotulo, float(fator), quem))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "sem_historico", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento_gerar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao gerar o orçamento."})


@app.post("/api/controladoria/orcamento/ajustar")
async def orcamento_ajustar(req: Request) -> JSONResponse:
    from api.orcamento import armazenamento as arm
    body = await req.json()
    try:
        versao_id = int(body["versao_id"])
        conta = str(body["conta"])
        mes = int(body["mes"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe versao_id, conta e mes."})
    if not (1 <= mes <= 12):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "mes deve estar entre 1 e 12."})
    valor = body.get("valor")
    if valor is not None:
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido", "mensagem": "valor deve ser numérico ou nulo."})
    try:
        quem = getattr(req.state, "usuario_nome", None) or "sistema"
        arm.ajustar(arm.DB_PATH, versao_id, conta, mes, valor, quem)
        return JSONResponse({"ok": True})
    except KeyError:
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": "Célula inexistente nessa versão."})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento_ajustar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao salvar o ajuste."})
```

Conferir no topo de `api/main.py` que `Request` está importado de `fastapi`; se não estiver, acrescentar ao import existente.

- [ ] **Step 8: Validar sintaxe e subir o servidor de teste**

Run:

```bash
uv run python -c "import ast;[ast.parse(open(f).read()) for f in ['api/main.py','api/auth.py','api/orcamento/servico.py']];print('py ok')"
uv run --with pytest python -m pytest -q
```

Expected: `py ok` e todos os testes passando.

- [ ] **Step 9: Testar o fluxo ponta a ponta contra o banco real**

Subir o servidor de teste e exercitar geração + leitura:

```bash
pkill -f servidor_teste.py; sleep 1
nohup .venv/bin/python /private/tmp/claude-501/*/scratchpad/servidor_teste.py > /tmp/srv.log 2>&1 &
sleep 15
```

Depois, com Playwright autenticado (mesmo padrão de `scratchpad/smoke.py`), chamar:
`POST /api/controladoria/orcamento/gerar` com `{"ano": 2026, "fator": -0.05}` e
`GET /api/controladoria/orcamento`.

Expected: a geração devolve `linhas` ≈ 4.140 (345 contas × 12) e `contas_sem_agrupador` com ~10 itens; o comparativo devolve `linhas` com os rótulos do `DRE_MODELO` e `mensal` com 12 entradas.

- [ ] **Step 10: Commit**

```bash
git add api/orcamento/ api/main.py api/auth.py tests/orcamento/
git commit -m "Orçamento: orquestração, endpoints e controle de acesso

montar_comparativo é puro e testado sem banco. A semântica de desvio é a regra
que mais importa: custo abaixo do orçado é FAVORÁVEL e receita abaixo é
desfavorável — a flag favoravel sai daí, e não do sinal do número. Mês sem
realizado devolve None, não zero, para o gráfico não desenhar barra de mês que
ainda não aconteceu. Contas sem agrupador ficam fora do orçamento e voltam na
resposta como pendência."
```

---

### Task 6: Tela — aba Acompanhamento

**Files:**
- Modify: `api/static/index.html` (HTML da vista, menu, `qsView`, loader/render, `NAV_KW`, gaveta mobile)

**Interfaces:**
- Consumes: `GET /api/controladoria/orcamento?versao_id&ate_mes` (Task 5), que devolve `{linhas[], contas[], mensal[], sem_linha[], versao, ate_mes, fonte}`.
- Produces: `loadOrc()`, `renderOrc(d)`, `DATAORC`, vista `#orc`.

- [ ] **Step 1: Acrescentar a vista no HTML**

Inserir a `<section>` logo após a vista `view-cont` (Contabilidade), seguindo o padrão de abas de Gestão:

```html
      <!-- ===================== ORÇAMENTO ===================== -->
      <section class="view" id="view-orc">
        <div class="card">
          <div class="head"><h2>Orçamento</h2><span class="hint">orçado × realizado por linha da DRE</span></div>
          <div class="ges-tabs">
            <button class="ghost" id="otab-acomp" aria-pressed="true" onclick="orcTab('acomp')">Acompanhamento</button>
            <button class="ghost" id="otab-mont" aria-pressed="false" onclick="orcTab('mont')">Montagem</button>
          </div>
          <div class="cardfilters" id="orc-filtros">
            <select id="fOrcVersao" aria-label="Versão do orçamento" onchange="loadOrc()"></select>
            <select id="fOrcAte" aria-label="Acumulado até o mês" onchange="loadOrc()"></select>
          </div>
        </div>
        <div id="orc-acomp">
          <div class="kpis k4" id="kpis-orc"></div>
          <div class="card"><div class="head"><h2>Orçado × realizado por linha</h2><span class="hint" id="hintOrcCasc"></span></div>
            <div class="tablewrap tabroll" id="orc-cascata"></div></div>
          <div class="card"><div class="head"><h2>Evolução mensal</h2><span class="hint">mês não fechado mostra só o orçado</span></div>
            <div class="chartwrap"><svg id="chartOrc" viewBox="0 0 960 250" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Orçado e realizado por mês."></svg></div></div>
          <div class="card"><div class="head"><h2>Maiores desvios</h2><span class="hint" id="hintOrcDesv"></span></div>
            <div class="tablewrap tabroll" id="orc-desvios"></div></div>
        </div>
        <div id="orc-mont" style="display:none"></div>
      </section>
```

- [ ] **Step 2: Acrescentar o item de menu**

No grupo Controladoria (`subsCtr`), após o link de Qualidade:

```html
        <a href="#orc" class="sub" data-view="orc" title="Orçamento — orçado × realizado"><span class="ic" data-ic="dre"></span><span>Orçamento</span></a>
```

E na gaveta mobile, junto dos demais itens de Controladoria:

```html
        <a href="#orc" onclick="fecharDrawer()"><span class="ic" data-ic="dre"></span>Orçamento</a>
```

- [ ] **Step 3: Registrar a vista no roteamento**

Em `VIEWS`, acrescentar `orc:'Orçamento',`.
Em `NAV_KW`, acrescentar `orc:['orcamento','orçamento','orcado','orçado','budget','previsto','desvio','meta de custo'],`.
Declarar `let DATAORC = null;` junto das demais.
No mapa de grupo do menu, acrescentar `orc:'Ctr',`.
No `DATAMAP`, acrescentar `orc:DATAORC,`.

Conferir que os seis registros entraram:

```bash
for t in "orc:'Orçamento'" "orc:\[" "let DATAORC" "orc:'Ctr'" "orc:DATAORC" 'data-view="orc"'; do
  printf '%-22s %s\n' "$t" "$(grep -c "$t" api/static/index.html)"
done
```

Expected: todos com contagem ≥ 1.

- [ ] **Step 4: Implementar o loader e o render**

Acrescentar antes da biblioteca de gráficos:

```javascript
// ---------------- Orçamento ----------------
let orcSeq = 0, ORC_ABA = 'acomp';
function orcTab(a){
  ORC_ABA = a;
  document.getElementById('otab-acomp').setAttribute('aria-pressed', String(a==='acomp'));
  document.getElementById('otab-mont').setAttribute('aria-pressed', String(a==='mont'));
  document.getElementById('orc-acomp').style.display = a==='acomp' ? '' : 'none';
  document.getElementById('orc-mont').style.display  = a==='mont'  ? '' : 'none';
  if(a==='mont') renderOrcMontagem();
}
async function loadOrc(){
  const seq=++orcSeq, btn=document.getElementById('btnRefresh'); if(btn) btn.disabled=true;
  document.getElementById('content').classList.add('loading');
  skelKpis('kpis-orc',4);
  try{
    const p=new URLSearchParams();
    const v=(document.getElementById('fOrcVersao')||{}).value;
    const a=(document.getElementById('fOrcAte')||{}).value;
    if(v) p.set('versao_id', v);
    if(a) p.set('ate_mes', a);
    const r=await fetch('/api/controladoria/orcamento?'+p.toString(),{cache:'no-store'});
    const d=await r.json(); if(seq!==orcSeq) return;
    if(!r.ok){ showBanner(d.mensagem||'Erro ao consultar o orçamento.', d.detalhe); return; }
    hideBanner(); DATAORC=d; LOADEDQS.orc=''; renderOrc(d);
  }catch(e){ if(seq===orcSeq) showBanner('Não foi possível falar com a API.', e.message); }
  finally{ if(seq===orcSeq){ if(btn) btn.disabled=false; document.getElementById('content').classList.remove('loading'); } }
}
function renderOrc(d){
  if(d.vazio){
    document.getElementById('kpis-orc').innerHTML='';
    document.getElementById('orc-cascata').innerHTML=
      `<div style="padding:26px 18px;color:var(--n500)">${esc(d.mensagem||'Nenhum orçamento criado.')} `
      +`Use a aba <b>Montagem</b> para gerar o primeiro.</div>`;
    document.getElementById('orc-desvios').innerHTML='';
    return;
  }
  const L=d.linhas||[];
  const pega=r=>L.find(x=>x.linha===r)||{orcado:0,realizado:0,desvio:0,desvio_pct:null,favoravel:true};
  const rec=pega('RECEITA BRUTA'), csp=pega('CSP'), res=pega('RESULTADO DO EXERCICIO');
  const estouradas=(d.contas||[]).filter(c=>c.desvio<0).length;
  // chip de desvio: a cor segue o EFEITO no resultado, nunca o sinal
  const chip=x=>x.desvio_pct==null?'' : statChip(x.favoravel?'good':'bad',
      (x.desvio>=0?'+':'')+x.desvio_pct.toLocaleString('pt-BR',{maximumFractionDigits:1})+'%',
      x.favoravel?'dentro do orçado':'fora do orçado');
  document.getElementById('kpis-orc').innerHTML=[
    kpi('Receita', BRL.format(rec.realizado), 'orçado '+BRL.format(rec.orcado),
        rec.favoravel?'pos':'neg',
        'Realizado acumulado do ano até o mês selecionado, contra o orçado do mesmo intervalo. Receita abaixo do orçado é desfavorável.', chip(rec)),
    kpi('Custo (CSP)', BRL.format(csp.realizado), 'orçado '+BRL.format(csp.orcado),
        csp.favoravel?'pos':'neg',
        'Custo dos serviços prestados acumulado contra o orçado. Gastar MENOS que o orçado é favorável — por isso um custo abaixo do previsto aparece em verde.', chip(csp)),
    kpi('Resultado', BRL.format(res.realizado), 'orçado '+BRL.format(res.orcado),
        res.favoravel?'pos':'neg',
        'Última linha da cascata: resultado do exercício realizado contra o orçado no mesmo intervalo.', chip(res)),
    kpi('Contas estouradas', estouradas.toLocaleString('pt-BR'),
        'de '+(d.contas||[]).length+' contas com movimento', estouradas>0?'warn':'pos',
        'Contas cujo realizado acumulado passou do orçado acumulado no mesmo intervalo. É a lista da aba de maiores desvios.'),
  ].join('');
  const cel=x=>{
    const c = x.favoravel ? 'var(--green)' : 'var(--red)';
    return `<td class="num" style="color:${c};font-weight:600">${(x.desvio>=0?'+':'')+BRL.format(x.desvio)}</td>`
      + `<td class="num" style="color:${c}">${x.desvio_pct==null?'—':(x.desvio>=0?'+':'')+x.desvio_pct.toLocaleString('pt-BR',{maximumFractionDigits:1})+'%'}</td>`;
  };
  document.getElementById('orc-cascata').innerHTML=
    `<table><thead><tr><th>Linha</th><th class="num">Orçado</th><th class="num">Realizado</th><th class="num">Desvio</th><th class="num">%</th></tr></thead><tbody>`
    + L.map(x=>`<tr><td style="font-weight:600">${esc(x.linha)}</td>`
        +`<td class="num">${BRL.format(x.orcado)}</td>`
        +`<td class="num" style="font-weight:600">${BRL.format(x.realizado)}</td>`+cel(x)+`</tr>`).join('')
    + `</tbody></table>`;
  document.getElementById('hintOrcCasc').textContent =
    'acumulado até o mês '+d.ate_mes+' · '+L.length+' linhas da cascata';
  const top=(d.contas||[]).slice(0,15);
  document.getElementById('orc-desvios').innerHTML=
    `<table><thead><tr><th>Conta</th><th>Linha</th><th class="num">Orçado</th><th class="num">Realizado</th><th class="num">Desvio</th></tr></thead><tbody>`
    + (top.map(c=>`<tr><td style="font-family:var(--mono)">${esc(c.conta)}</td><td>${esc(c.linha)}</td>`
        +`<td class="num">${BRL.format(c.orcado)}</td><td class="num">${BRL.format(c.realizado)}</td>`
        +`<td class="num" style="color:${c.favoravel?'var(--green)':'var(--red)'};font-weight:700">${(c.desvio>=0?'+':'')+BRL.format(c.desvio)}</td></tr>`).join('')
       || '<tr><td colspan="5" style="color:var(--n500)">sem contas no período</td></tr>')
    + `</tbody></table>`;
  document.getElementById('hintOrcDesv').textContent = top.length+' de '+(d.contas||[]).length+' contas · maior desvio primeiro';
  chartOrcRender(d.mensal||[]);
  if((d.sem_linha||[]).length){
    document.getElementById('orc-cascata').insertAdjacentHTML('afterbegin',
      `<div class="banner-inline" style="display:block;margin:10px 16px">`
      +`<b>${d.sem_linha.length} conta(s) sem agrupador</b> ficaram fora do orçamento — `
      +`elas não somam em linha nenhuma da DRE. Classifique em <a href="#cont">Contabilidade</a>.</div>`);
  }
}
function chartOrcRender(mensal){
  const svg=document.getElementById('chartOrc');
  if(!mensal.length){ svg.innerHTML='<text x="480" y="120" text-anchor="middle" fill="#6E7883" font-size="14">sem dados</text>'; return; }
  const W=960,H=250,mL=64,mR=16,mT=28,mB=34, iw=W-mL-mR, ih=H-mT-mB;
  const n=mensal.length, bandW=iw/n;
  const vals=mensal.flatMap(r=>[Math.abs(r.orcado||0), Math.abs(r.realizado||0)]);
  const tks=niceTicks(0,Math.max(1,...vals),4), top=tks[tks.length-1], u=unitOf(top);
  const y=v=>mT+ih-(Math.abs(v)/top)*ih, y0=y(0);
  const px=i=>mL+bandW*i+bandW/2;
  const bw=Math.min(16,bandW*0.3);
  let s='';
  s+=`<text x="${mL}" y="${mT-12}" font-size="11" fill="#6E7883" font-weight="600" letter-spacing="1.5">${u.t}</text>`;
  tks.forEach(v=>{ const yy=y(v);
    s+=`<line x1="${mL}" y1="${yy}" x2="${W-mR}" y2="${yy}" stroke="${v===0?'#C2C8D0':'#ECEEF1'}" stroke-width="1"/>`;
    s+=`<text x="${mL-8}" y="${yy+4}" text-anchor="end" font-size="11" fill="#6E7883" font-family="IBM Plex Mono,monospace">${NMI.format(v/u.d)}</text>`; });
  mensal.forEach((r,i)=>{
    s+=colPath(px(i)-bw-1,bw,y(r.orcado||0),y0,3,CC.navy400);
    // mês não fechado NÃO desenha realizado: barra zerada leria como queda
    if(r.fechado && r.realizado!=null) s+=colPath(px(i)+1,bw,y(r.realizado),y0,3,CC.navy700);
  });
  mensal.forEach((r,i)=>{ s+=`<text x="${px(i)}" y="${H-mB+18}" text-anchor="middle" font-size="10.5" fill="${r.fechado?'#4F5860':'#AEB6BF'}">${r.mes}</text>`; });
  svg.innerHTML=s;
}
```

- [ ] **Step 5: Ligar o loader ao roteamento**

Há **dois** mapas de loader no arquivo (por volta das linhas 2838 e 3818). Acrescentar
`orc:loadOrc,` em **ambos**, logo após `cont:loadCont,`:

```javascript
cont:loadCont,orc:loadOrc,gestao:loadGestao,
```

Confirmar que os dois foram alterados:

```bash
grep -c 'orc:loadOrc' api/static/index.html   # tem de devolver 2
```

- [ ] **Step 6: Popular os selects de versão e mês**

Acrescentar em `loadOrc()`, antes do `fetch` do comparativo:

```javascript
  // popula os selects uma única vez
  const selA=document.getElementById('fOrcAte');
  if(selA && !selA.dataset.pronto){
    const MES=['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
    selA.innerHTML='<option value="">Até o último mês fechado</option>'
      + MES.map((m,i)=>`<option value="${i+1}">Até ${m}</option>`).join('');
    selA.dataset.pronto='1';
  }
  const selV=document.getElementById('fOrcVersao');
  if(selV && !selV.dataset.pronto){
    try{
      const rv=await fetch('/api/controladoria/orcamento/versoes',{cache:'no-store'});
      const dv=await rv.json();
      selV.innerHTML=(dv.versoes||[]).map(x=>
        `<option value="${x.id}">${esc(x.rotulo)} (${x.ano})</option>`).join('')
        || '<option value="">nenhuma versão</option>';
      selV.dataset.pronto='1';
    }catch(e){ /* segue sem versão: a API escolhe a mais recente */ }
  }
```

- [ ] **Step 7: Validar**

```bash
node -e "
const fs=require('fs'),h=fs.readFileSync('api/static/index.html','utf8');
[...h.matchAll(/<script>([\s\S]*?)<\/script>/g)].forEach((x,i)=>{try{new Function(x[1])}catch(e){console.log('ERRO',i,e.message);process.exit(1)}});
console.log('JS OK');"
```

Depois reiniciar o servidor de teste, abrir `#orc` com Playwright e conferir: sem erro de console, KPIs renderizados, cascata com as linhas do `DRE_MODELO`.

- [ ] **Step 8: Commit**

```bash
git add api/static/index.html
git commit -m "Orçamento: tela de acompanhamento (orçado × realizado)

Cascata da DRE com orçado, realizado e desvio; a cor do desvio segue o efeito no
resultado, então custo abaixo do orçado sai verde e receita abaixo sai vermelho.
Mês não fechado não desenha barra de realizado no gráfico — o mesmo defeito que o
painel de TV tinha. Contas sem agrupador aparecem em banner com link para a
Contabilidade, em vez de sumirem de um total que não fecharia."
```

---

### Task 7: Tela — aba Montagem

**Files:**
- Modify: `api/static/index.html`

**Interfaces:**
- Consumes: `POST /api/controladoria/orcamento/gerar`, `POST /api/controladoria/orcamento/ajustar` (Task 5), `DATAORC` (Task 6).
- Produces: `renderOrcMontagem()`, `orcGerar()`, `orcSalvarCelula(input)`.

- [ ] **Step 1: Implementar a aba**

Acrescentar após `chartOrcRender`:

```javascript
function renderOrcMontagem(){
  const d=DATAORC||{};
  const alvo=document.getElementById('orc-mont');
  const anoSug=new Date().getFullYear();
  const contas=(d.contas||[]);
  const linhas=[...new Set(contas.map(c=>c.linha))].sort();
  alvo.innerHTML=`
    <div class="card"><div class="head"><h2>Gerar baseline</h2>
      <span class="hint">mês espelho dos 12 meses fechados + fator de tendência</span></div>
      <div class="cardfilters">
        <input type="number" id="fOrcAno" value="${anoSug}" min="2020" max="2100" aria-label="Ano do orçamento" style="width:100px">
        <input type="number" id="fOrcFator" value="0" step="1" aria-label="Fator de tendência em %" style="width:110px" title="Percentual aplicado sobre o mês espelho. Ex.: -5 orça 5% abaixo do ano anterior.">
        <span style="color:var(--n500)">% de tendência</span>
        <button class="btn" onclick="orcGerar()">Gerar</button>
        <span class="hint" id="orcGerarMsg"></span>
      </div>
      <div class="banner-inline" style="display:block;margin:0 16px 14px">
        O baseline parte do <b>mesmo mês</b> do ano anterior, o que preserva a queda de
        dezembro. Conta com menos de 9 dos 12 meses de movimento sai pela mediana e
        aparece marcada como <b>base fraca</b>. Regerar <b>não apaga</b> ajuste manual.
      </div></div>
    <div class="card"><div class="head"><h2>Grade de ajuste</h2>
      <span class="hint" id="hintOrcGrade"></span></div>
      <div class="cardfilters">
        <select id="fOrcLinha" aria-label="Filtrar por linha da DRE" onchange="renderOrcGrade()">
          <option value="">Todas as linhas</option>
          ${linhas.map(l=>`<option value="${esc(l)}">${esc(l)}</option>`).join('')}
        </select>
      </div>
      <div class="tablewrap tabroll" id="orc-grade"></div></div>`;
  renderOrcGrade();
}
function renderOrcGrade(){
  const d=DATAORC||{}; const vid=(d.versao||{}).id;
  const filtro=(document.getElementById('fOrcLinha')||{}).value||'';
  const contas=(d.contas||[]).filter(c=>!filtro||c.linha===filtro);
  const MES=['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
  const el=document.getElementById('orc-grade');
  if(!vid){ el.innerHTML='<div style="padding:20px;color:var(--n500)">Gere um baseline primeiro.</div>'; return; }
  el.innerHTML=`<table><thead><tr><th>Conta</th><th>Linha</th>`
    + MES.map(m=>`<th class="num">${m}</th>`).join('') + `</tr></thead><tbody>`
    + contas.map(c=>{
        const fraca = c.origem && c.origem!=='espelho';
        return `<tr><td style="font-family:var(--mono)">${esc(c.conta)}`
          + (fraca?` <span class="badge b-warn" title="Menos de 9 dos 12 meses com movimento: o valor saiu por mediana, não por mês espelho. Revise.">base fraca</span>`:'')
          + `</td><td style="color:var(--n500)">${esc(c.linha||'—')}</td>`
          + MES.map((_,i)=>`<td class="num"><input type="number" step="0.01" class="ocel"
               data-conta="${esc(c.conta)}" data-mes="${i+1}" data-versao="${vid}"
               onchange="orcSalvarCelula(this)" style="width:92px;text-align:right"></td>`).join('')
          + `</tr>`;
      }).join('')
    + `</tbody></table>`;
  document.getElementById('hintOrcGrade').textContent =
    contas.length+' contas'+(filtro?' em '+filtro:'')+' · o valor em branco segue o baseline';
}
async function orcGerar(){
  const ano=parseInt(document.getElementById('fOrcAno').value,10);
  const pct=parseFloat(document.getElementById('fOrcFator').value||'0');
  const msg=document.getElementById('orcGerarMsg');
  msg.textContent='gerando…';
  try{
    const r=await fetch('/api/controladoria/orcamento/gerar',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({ano:ano, fator:pct/100, rotulo:'Orçamento '+ano})});
    const d=await r.json();
    if(!r.ok){ msg.textContent=''; showBanner(d.mensagem||'Erro ao gerar.'); return; }
    msg.textContent=`versão ${d.versao_id} criada · ${d.linhas} linhas`
      + (d.contas_sem_agrupador.length?` · ${d.contas_sem_agrupador.length} conta(s) sem agrupador ficaram de fora`:'');
    await loadOrc();
  }catch(e){ msg.textContent=''; showBanner('Não foi possível falar com a API.', e.message); }
}
async function orcSalvarCelula(inp){
  const bruto=inp.value.trim();
  const valor = bruto==='' ? null : parseFloat(bruto);
  const antes = inp.dataset.antes||'';
  inp.disabled=true;
  try{
    const r=await fetch('/api/controladoria/orcamento/ajustar',{method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({versao_id:parseInt(inp.dataset.versao,10),
        conta:inp.dataset.conta, mes:parseInt(inp.dataset.mes,10), valor:valor})});
    const d=await r.json();
    if(!r.ok){ inp.value=antes; showBanner(d.mensagem||'Não foi possível salvar o ajuste.'); return; }
    inp.dataset.antes=bruto;
    inp.style.background = bruto==='' ? '' : 'var(--yellow-100)';
  }catch(e){ inp.value=antes; showBanner('Não foi possível falar com a API.', e.message); }
  finally{ inp.disabled=false; }
}
```

- [ ] **Step 2: Validar sintaxe**

```bash
node -e "
const fs=require('fs'),h=fs.readFileSync('api/static/index.html','utf8');
[...h.matchAll(/<script>([\s\S]*?)<\/script>/g)].forEach((x,i)=>{try{new Function(x[1])}catch(e){console.log('ERRO',i,e.message);process.exit(1)}});
console.log('JS OK');"
```

- [ ] **Step 3: Testar o ciclo completo no navegador**

Com o servidor de teste no ar: abrir `#orc` → aba Montagem → gerar 2026 com fator −5 → voltar para Acompanhamento e conferir a cascata → voltar à Montagem, alterar uma célula, regerar e confirmar que o valor ajustado permaneceu.

O mesmo ciclo, verificável sem navegador (o critério de aceite nº 3):

```bash
uv run python - <<'EOF'
import sys; sys.path.insert(0,'.')
from api.orcamento import armazenamento as arm
p = arm.DB_PATH
v = arm.listar_versoes(p)[0]["id"]
antes = [l for l in arm.ler_linhas(p, v) if l["mes"] == 3][0]
arm.ajustar(p, v, antes["conta"], 3, 12345.0, "teste-ciclo")
arm.gravar_baseline(p, v, [{"conta": antes["conta"], "mes": 3,
    "valor_baseline": 999.0, "origem": "espelho", "meses_com_dado": 12}])
dep = [l for l in arm.ler_linhas(p, v) if l["mes"] == 3 and l["conta"] == antes["conta"]][0]
assert dep["valor_baseline"] == 999.0, "baseline nao atualizou"
assert dep["valor_efetivo"] == 12345.0, "AJUSTE FOI PERDIDO ao regerar"
arm.ajustar(p, v, antes["conta"], 3, None, "teste-ciclo")   # limpa o que o teste sujou
print("ok: regerar preservou o ajuste")
EOF
```

Expected: `ok: regerar preservou o ajuste`.

- [ ] **Step 4: Commit**

```bash
git add api/static/index.html
git commit -m "Orçamento: aba de montagem (gerar baseline e ajustar)

Geração com ano e fator de tendência em %, e grade de ajuste filtrada por linha
da DRE — 355 contas de uma vez não se lê. Conta derivada por mediana aparece
marcada como base fraca. Salvamento por célula é otimista com rollback visual se
a API falhar."
```

---

### Task 8: Validação final e publicação

**Files:**
- Modify: `CLAUDE.md` (§5, padrões aprendidos)
- Modify: `scratchpad/estrutura.py` (incluir `orc` na lista de vistas)

- [ ] **Step 1: Rodar a suíte completa**

Run: `uv run --with pytest python -m pytest -q`
Expected: PASS (78 anteriores + 37 novos = 115).

- [ ] **Step 2: Rodar o smoke e o validador estrutural**

```bash
cd /private/tmp/claude-501/*/scratchpad
uv run --with playwright python smoke.py
python - <<'PY'
p='estrutura.py'; s=open(p,encoding='utf-8').read()
assert '"srv"' in s or "'srv'" in s
s=s.replace('"gestao", "srv"', '"gestao", "srv", "orc"')
open(p,'w',encoding='utf-8').write(s); print('orc incluído')
PY
uv run --with playwright python estrutura.py
```

Expected: smoke sem erros de console; validador com **0 telas com problema estrutural**.

- [ ] **Step 3: Registrar os padrões no CLAUDE.md**

Acrescentar na §5, antes da seção "Telas de consulta":

```markdown
**Orçamento (módulo novo, 2026-07-26):**
- **Escrita fica em SQLite local** (`data/orcamento.db`), porque o AVA é réplica
  somente-leitura. Padrão do `auth.db`: conexão curta, WAL, commit automático.
- **`valor_efetivo = coalesce(valor_ajustado, valor_baseline)`** — regerar o baseline
  nunca apaga ajuste manual. Mesmo princípio do `ajustes_contabeis.json`.
- **Derivação por mês espelho, não média.** Dezembro cai ~40% na Sulista e há queda
  estrutural de 18% a/a: média achata a sazonalidade e ignora a tendência.
- **Corte de recorrência em 75% dos meses da base.** 41 das 355 contas aparecem em 1 ou
  2 meses; espelhar isso é ruído com cara de número. Abaixo do corte → mediana + marca
  "base fraca".
- **Desvio orçamentário tem cor invertida em custo.** Custo abaixo do orçado é
  FAVORÁVEL (verde), receita abaixo é desfavorável (vermelho). A flag `favoravel` vem do
  efeito no resultado, nunca do sinal.
- Conta sem agrupador fica **fora** do orçamento e volta como pendência com link para a
  Contabilidade — orçar o que não soma em linha nenhuma faria o total não fechar.
```

- [ ] **Step 4: Commit e publicação**

```bash
git add CLAUDE.md
git commit -m "Orçamento: registra os padrões do módulo no CLAUDE.md"
git push origin main
```

- [ ] **Step 5: Confirmar o deploy em produção**

```bash
for i in 1 2 3 4 5; do
  r=$(ssh -o ClearAllForwardings=yes -o ConnectTimeout=20 cortex-ava-tunnel \
      "type C:\\Users\\inteligencia\\Documents\\cortex-sulista\\logs\\deployed.txt" \
      2>/dev/null | LC_ALL=C tr -d '\r')
  echo "tentativa $i: $r"
  case "$r" in $(git rev-parse --short HEAD)*) echo "DEPLOY OK"; break;; esac
  sleep 55
done
```

Expected: `DEPLOY OK` com o SHA do último commit.

---

## Critérios de aceite (conferir ao final)

1. Gerar baseline de 2026 e ver a cascata da DRE preenchida na coluna Orçado.
2. Total orçado de uma linha = soma das contas dessa linha na aba de desvios.
3. Ajustar uma célula, regerar o baseline e o ajuste continuar lá.
4. Custo abaixo do orçado aparece em verde; receita abaixo, em vermelho.
5. Mês em curso não exibe barra de realizado no gráfico de evolução.
6. As contas sem agrupador aparecem no banner de pendências, não no orçamento.
7. `pytest`, smoke e validador estrutural passam.
