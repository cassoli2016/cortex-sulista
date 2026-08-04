# Previsão de Fechamento do Mês — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Módulo `api/previsao/` que prevê o fechamento da DRE gerencial do mês corrente (M) e estima a consolidação do mês em fechamento (M-1), com motor híbrido por linha, cenários calibrados por backtest, ajustes manuais em SQLite e tela `fech` na Controladoria.

**Architecture:** Subpacote no padrão `api/orcamento/` — SQL sobre a réplica AVA em `sql.py`, cálculo 100% puro em `completude.py`/`motor.py`, orquestração com fetch paralelo em `servico.py`, escrita local em SQLite (`armazenamento.py`). Rollup conta→agrupador→linha REUSA `DRE_MODELO`/`_dre_aloca`/`ler_ajustes` de `api/queries.py` e `indices_sazonais` de `api/orcamento/derivacao.py` para bater ao centavo com a DRE Gerencial e o Orçamento.

**Tech Stack:** Python 3 (FastAPI, psycopg3, sqlite3, pytest via `uv run pytest`), SPA vanilla JS em `api/static/index.html`, PostgreSQL 9.3 read-only via túnel SSH (127.0.0.1:15432).

**Spec:** `docs/superpowers/specs/2026-08-02-previsao-fechamento-design.md` (aprovada, commit `e78cc8b`).

## Global Constraints

- **Banco AVA é réplica READ-ONLY, PostgreSQL 9.3.25**: SQL só SELECT; sem `FILTER (WHERE ...)`, sem `LATERAL`; strings SQL só com caracteres **LATIN-1** (nunca `—`, `→`, `≥` dentro de SQL; usar `-`, `>=`); `%` de LIKE vira `%%`. Agregar no banco, derivar em Python (túnel tem RTT ~284ms).
- **NUNCA ler/imprimir/copiar `.env`, senhas ou connection strings** (Política Gobrax, Cláusula 5.1). `scripts/db.sh` lê credenciais por nome de variável — use-o para validar SQL: `scripts/db.sh psql -c "SELECT 1"` (a partir da raiz do repo).
- **Convenção de sinal da DRE**: `valor = coalesce(valorcredito,0) - coalesce(valordebito,0)` → receita positiva, custo/despesa **negativos**. Fórmulas do `DRE_MODELO` são SOMA simples. Excluir sempre `coalesce(l.historico,0) <> 18`.
- **Não editar `api/queries.py`** (só importar dele). Edições permitidas: `api/main.py`, `api/auth.py`, `api/alertas.py`, `api/static/index.html`.
- **`ast.parse` antes de gravar qualquer `.py` editado por substituição**; edições no `index.html` por substituição literal de trecho conhecido (nunca regex ampla, nunca correção de aspas em massa). Após mexer no HTML: `uv run python scratchpad/estrutura.py` + smoke.
- **Após mexer em imports**: `uv run python -c "from api import main"` (import quebrado derruba o painel em produção com --reload).
- **RBAC**: rota `/api/*` nova sem entrada em `ROTA_TELAS` é **fail-closed** (403). Seed de perfis atual = `perfis_modelo_v19`; este módulo usa **v20**.
- **Testes**: `uv run pytest tests/previsao/ -q` por task; suíte completa verde antes do commit final. Commits em português no padrão do repo (`feat: ...`), um por task.
- Datas de competência: `'YYYY-MM'`; intervalos `[de, ate)` via `_comp_bounds` de `api/queries.py`.
- Campo de valor no front: `type="text"` + `inputmode="decimal"` + `numBR()` — **nunca** `type="number"`.

## File Structure

```
api/previsao/
  __init__.py         # fachada get_previsao_fechamento (com @cached de api.queries)
  armazenamento.py    # SQLite data/previsao.db: prev_ajuste, prev_snapshot, prev_log
  completude.py       # PURO: curva de escrituração (dtinc) por agrupador/linha
  motor.py            # PURO: estratégias, cascata, cenários, ajustes, M-1
  sql.py              # SQL novos (completude, atingimento hist, vfc, ctaplus, cap)
  servico.py          # orquestração: fetch paralelo -> motor -> comparáveis -> snapshot
scripts/backtest_previsao.py   # as-of via dtinc; gera data/previsao_calibracao.json + relatório
tests/previsao/
  __init__.py
  test_armazenamento.py
  test_completude.py
  test_motor_estrategias.py
  test_motor_cascata.py
  test_sql.py
  test_servico.py
  test_auth_fech.py
  test_alertas_previsao.py
api/main.py           # + GET /api/controladoria/previsao, POST .../previsao/ajuste
api/auth.py           # + tela 'fech', ROTA_TELAS, _PERFIS_MODELO, seed v20
api/alertas.py        # + _alertas_previsao() em build_alertas
api/static/index.html # + vista fech (sidebar, gaveta, section, loaders, POST)
```

---

### Task 1: Armazenamento SQLite (`api/previsao/armazenamento.py`)

**Files:**
- Create: `api/previsao/__init__.py` (vazio por enquanto — a fachada entra na Task 6)
- Create: `api/previsao/armazenamento.py`
- Create: `tests/previsao/__init__.py` (vazio)
- Test: `tests/previsao/test_armazenamento.py`

**Interfaces:**
- Consumes: nada do projeto (só stdlib).
- Produces (Tasks 6/7 dependem): `DB_PATH: Path`; `init_db(path: Path = DB_PATH) -> None`; `ler_ajustes_prev(path: Path, mes: str) -> dict[str, dict]` (chave = rótulo da linha; valor = `{"tipo","valor","motivo","autor","criado_em"}`); `salvar_ajuste_prev(path, mes: str, linha: str, tipo: str, valor: float, motivo: str, autor: str) -> None` (ValueError se tipo inválido ou motivo vazio); `remover_ajuste_prev(path, mes, linha) -> bool`; `gravar_snapshot(path, data_foto: str, mes: str, linhas: list[dict]) -> None` (upsert por (data,mes,linha); cada dict tem `linha, previsto_base, previsto_otim, previsto_pess, realizado_contabil, estrategia`); `ler_snapshots(path, mes: str) -> list[dict]` (ordenado por data, linha); `registrar_log(path, autor, acao, detalhe) -> None`.

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/previsao/test_armazenamento.py
"""Persistência de ajustes manuais e snapshots — SQLite isolado em tmp_path."""
from __future__ import annotations

import pytest

from api.previsao import armazenamento as arm


def test_ajuste_crud(tmp_path):
    db = tmp_path / "previsao.db"
    arm.init_db(db)
    arm.salvar_ajuste_prev(db, "2026-08", "CUSTO VARIAVEL", "delta", -120000.0,
                           "rescisao prevista", "cristian")
    aj = arm.ler_ajustes_prev(db, "2026-08")
    assert aj["CUSTO VARIAVEL"]["tipo"] == "delta"
    assert aj["CUSTO VARIAVEL"]["valor"] == -120000.0
    assert aj["CUSTO VARIAVEL"]["motivo"] == "rescisao prevista"
    # sobrescrever a mesma (mes, linha) substitui, nao duplica
    arm.salvar_ajuste_prev(db, "2026-08", "CUSTO VARIAVEL", "valor", -900000.0,
                           "valor fechado com o RH", "cristian")
    aj = arm.ler_ajustes_prev(db, "2026-08")
    assert len(aj) == 1 and aj["CUSTO VARIAVEL"]["tipo"] == "valor"
    assert arm.remover_ajuste_prev(db, "2026-08", "CUSTO VARIAVEL") is True
    assert arm.ler_ajustes_prev(db, "2026-08") == {}
    assert arm.remover_ajuste_prev(db, "2026-08", "CUSTO VARIAVEL") is False


def test_ajuste_valida_tipo_e_motivo(tmp_path):
    db = tmp_path / "previsao.db"
    arm.init_db(db)
    with pytest.raises(ValueError):
        arm.salvar_ajuste_prev(db, "2026-08", "RECEITA BRUTA", "percentual", 1.0, "x", "a")
    with pytest.raises(ValueError):
        arm.salvar_ajuste_prev(db, "2026-08", "RECEITA BRUTA", "delta", 1.0, "  ", "a")


def test_snapshot_upsert_e_leitura(tmp_path):
    db = tmp_path / "previsao.db"
    arm.init_db(db)
    linhas = [{"linha": "RESULTADO DO EXERCICIO", "previsto_base": 100.0,
               "previsto_otim": 150.0, "previsto_pess": 50.0,
               "realizado_contabil": 40.0, "estrategia": "cascata"}]
    arm.gravar_snapshot(db, "2026-08-02", "2026-08", linhas)
    # regravar o MESMO dia substitui (idempotente por dia)
    linhas[0]["previsto_base"] = 110.0
    arm.gravar_snapshot(db, "2026-08-02", "2026-08", linhas)
    snaps = arm.ler_snapshots(db, "2026-08")
    assert len(snaps) == 1
    assert snaps[0]["previsto_base"] == 110.0
    assert snaps[0]["data"] == "2026-08-02"


def test_init_db_idempotente(tmp_path):
    db = tmp_path / "previsao.db"
    arm.init_db(db)
    arm.init_db(db)  # nao explode nem apaga
    arm.registrar_log(db, "cristian", "teste", "detalhe")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/previsao/test_armazenamento.py -q`
Expected: FAIL (`ModuleNotFoundError: api.previsao`)

- [ ] **Step 3: Implementar**

```python
# api/previsao/armazenamento.py
"""Persistência local da previsão de fechamento (SQLite).

O AVA é réplica somente-leitura; ajuste manual e snapshot diário são dado
nosso. Padrão de api/orcamento/armazenamento.py: conexão curta com commit
automático e WAL.

Regra central (herdada do orçamento): recalcular a previsão NUNCA apaga o
ajuste manual — o efetivo é previsto_calculado + delta (ou o valor absoluto),
resolvido no motor (motor.aplicar_ajustes), não aqui.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "previsao.db"

TIPOS_AJUSTE = ("delta", "valor")


@contextmanager
def _conn(path: Path):
    Path(path).parent.mkdir(exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        with c:
            yield c
    finally:
        c.close()


def init_db(path: Path = DB_PATH) -> None:
    with _conn(path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS prev_ajuste(
            mes       TEXT NOT NULL,
            linha     TEXT NOT NULL,
            tipo      TEXT NOT NULL CHECK (tipo IN ('delta','valor')),
            valor     REAL NOT NULL,
            motivo    TEXT NOT NULL,
            autor     TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (mes, linha)
        );
        CREATE TABLE IF NOT EXISTS prev_snapshot(
            data               TEXT NOT NULL,
            mes                TEXT NOT NULL,
            linha              TEXT NOT NULL,
            previsto_base      REAL NOT NULL,
            previsto_otim      REAL,
            previsto_pess      REAL,
            realizado_contabil REAL,
            estrategia         TEXT,
            PRIMARY KEY (data, mes, linha)
        );
        CREATE TABLE IF NOT EXISTS prev_log(
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            quando  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            autor   TEXT,
            acao    TEXT NOT NULL,
            detalhe TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_prev_snap_mes ON prev_snapshot(mes, data);
        """)


def ler_ajustes_prev(path: Path, mes: str) -> dict[str, dict]:
    with _conn(path) as c:
        rows = c.execute(
            "SELECT linha, tipo, valor, motivo, autor, criado_em "
            "FROM prev_ajuste WHERE mes=?", (mes,)).fetchall()
        return {r["linha"]: {k: r[k] for k in
                             ("tipo", "valor", "motivo", "autor", "criado_em")}
                for r in rows}


def salvar_ajuste_prev(path: Path, mes: str, linha: str, tipo: str,
                       valor: float, motivo: str, autor: str) -> None:
    if tipo not in TIPOS_AJUSTE:
        raise ValueError(f"tipo deve ser um de {TIPOS_AJUSTE}")
    if not (motivo or "").strip():
        raise ValueError("motivo é obrigatório")
    with _conn(path) as c:
        c.execute(
            "INSERT OR REPLACE INTO prev_ajuste(mes, linha, tipo, valor, motivo, autor) "
            "VALUES(?,?,?,?,?,?)", (mes, linha, tipo, float(valor), motivo.strip(), autor))
        c.execute("INSERT INTO prev_log(autor, acao, detalhe) VALUES(?,?,?)",
                  (autor, "ajuste", f"{mes} {linha} {tipo}={valor} ({motivo.strip()})"))


def remover_ajuste_prev(path: Path, mes: str, linha: str) -> bool:
    with _conn(path) as c:
        cur = c.execute("DELETE FROM prev_ajuste WHERE mes=? AND linha=?", (mes, linha))
        if cur.rowcount:
            c.execute("INSERT INTO prev_log(autor, acao, detalhe) VALUES(?,?,?)",
                      (None, "ajuste_removido", f"{mes} {linha}"))
        return bool(cur.rowcount)


def gravar_snapshot(path: Path, data_foto: str, mes: str, linhas: list[dict]) -> None:
    with _conn(path) as c:
        c.executemany(
            "INSERT OR REPLACE INTO prev_snapshot"
            "(data, mes, linha, previsto_base, previsto_otim, previsto_pess,"
            " realizado_contabil, estrategia) VALUES(?,?,?,?,?,?,?,?)",
            [(data_foto, mes, ln["linha"], ln["previsto_base"], ln.get("previsto_otim"),
              ln.get("previsto_pess"), ln.get("realizado_contabil"), ln.get("estrategia"))
             for ln in linhas])


def ler_snapshots(path: Path, mes: str) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute(
            "SELECT data, mes, linha, previsto_base, previsto_otim, previsto_pess,"
            "       realizado_contabil, estrategia "
            "FROM prev_snapshot WHERE mes=? ORDER BY data, linha", (mes,)).fetchall()
        return [dict(r) for r in rows]


def registrar_log(path: Path, autor: str | None, acao: str, detalhe: str) -> None:
    with _conn(path) as c:
        c.execute("INSERT INTO prev_log(autor, acao, detalhe) VALUES(?,?,?)",
                  (autor, acao, detalhe))
```

Criar também `api/previsao/__init__.py` e `tests/previsao/__init__.py` **vazios**.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/previsao/test_armazenamento.py -q`
Expected: 4 passed

- [ ] **Step 5: Verificar import e commitar**

```bash
uv run python -c "from api.previsao import armazenamento"
git add api/previsao/ tests/previsao/
git commit -m "feat(previsao): armazenamento SQLite de ajustes e snapshots"
```

---

### Task 2: Curva de completude (`api/previsao/completude.py`)

Mede, por agrupador e por linha, **que fração do |movimento| final do mês costuma estar escriturada no dia D** (D = dias desde o 1º dia do mês de competência; D=31~fim do mês, D>31 = depois do fim). Fatos medidos (spec §2): folha 10-24% no fim do mês, terceiros 60%, combustível 80%; tudo ~100% em D+40.

**Files:**
- Create: `api/previsao/completude.py`
- Test: `tests/previsao/test_completude.py`

**Interfaces:**
- Consumes: nada do projeto (puro).
- Produces (Tasks 4/6/8 dependem): `DIA_MAX = 45`; `PISO_COMPLETUDE = 0.30`; `montar_curva(rows: list[dict], mapa_ag_linha: dict[str, str | None]) -> dict` — `rows` = `[{"mes","agrupador","dia_rel","valor_abs"}]` de meses FECHADOS; retorna `{"ag": {agrupador: {dia: frac}}, "linha": {rotulo: {dia: frac}}, "global": {dia: frac}}` com frac acumulada crescente em [0,1] para dia 0..DIA_MAX (média das frações mensais); `completude_em(curva: dict, agrupador: str | None, linha: str | None, dia_rel: int) -> float` — cascata ag→linha→global, clamp em [0.0, 1.0], `1.0` se não houver curva nenhuma.

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/previsao/test_completude.py
"""Curva de escrituração: fração acumulada do movimento por dia relativo."""
from __future__ import annotations

from api.previsao.completude import (DIA_MAX, PISO_COMPLETUDE, completude_em,
                                     montar_curva)


def _rows_sinteticas():
    # agrupador FOLHA: 20% no dia 30 (fim do mes), 80% no dia 35 (D+4) — 2 meses iguais
    rows = []
    for mes in ("2026-05", "2026-06"):
        rows.append({"mes": mes, "agrupador": "CF - FOLHA MOT", "dia_rel": 30, "valor_abs": 20.0})
        rows.append({"mes": mes, "agrupador": "CF - FOLHA MOT", "dia_rel": 35, "valor_abs": 80.0})
        # agrupador COMBUSTIVEL: linear, 50% no dia 15, 100% no dia 30
        rows.append({"mes": mes, "agrupador": "CV - COMBUSTIVEL", "dia_rel": 15, "valor_abs": 50.0})
        rows.append({"mes": mes, "agrupador": "CV - COMBUSTIVEL", "dia_rel": 30, "valor_abs": 50.0})
    return rows


MAPA = {"CF - FOLHA MOT": "CUSTO FIXO", "CV - COMBUSTIVEL": "CUSTO VARIAVEL"}


def test_frac_acumulada_por_agrupador():
    curva = montar_curva(_rows_sinteticas(), MAPA)
    assert abs(completude_em(curva, "CF - FOLHA MOT", "CUSTO FIXO", 30) - 0.20) < 1e-9
    assert abs(completude_em(curva, "CF - FOLHA MOT", "CUSTO FIXO", 34) - 0.20) < 1e-9
    assert abs(completude_em(curva, "CF - FOLHA MOT", "CUSTO FIXO", 35) - 1.00) < 1e-9
    assert abs(completude_em(curva, "CV - COMBUSTIVEL", "CUSTO VARIAVEL", 15) - 0.50) < 1e-9


def test_monotonicidade_e_clamp():
    curva = montar_curva(_rows_sinteticas(), MAPA)
    serie = [completude_em(curva, "CV - COMBUSTIVEL", None, d) for d in range(DIA_MAX + 1)]
    assert all(b >= a for a, b in zip(serie, serie[1:]))
    assert serie[-1] == 1.0
    assert completude_em(curva, "CV - COMBUSTIVEL", None, 999) == 1.0


def test_cascata_ag_linha_global():
    curva = montar_curva(_rows_sinteticas(), MAPA)
    # agrupador desconhecido cai na LINHA; linha desconhecida cai na GLOBAL
    v_linha = completude_em(curva, "CF - PESSOAL OPERACIONAL", "CUSTO FIXO", 30)
    assert abs(v_linha - 0.20) < 1e-9          # linha CUSTO FIXO = so a folha sintetica
    v_global = completude_em(curva, "ZZZ", "LINHA INEXISTENTE", 30)
    assert 0.0 < v_global <= 1.0               # global = mistura dos dois agrupadores
    assert completude_em({}, "ZZZ", None, 10) == 1.0  # sem curva nenhuma -> neutro


def test_piso_exportado():
    assert 0.0 < PISO_COMPLETUDE < 1.0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/previsao/test_completude.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implementar**

```python
# api/previsao/completude.py
"""Curva de escrituração do razão — PURO (sem banco).

dia_rel = dias desde o 1º dia do mês de COMPETÊNCIA em que o lançamento foi
INCLUÍDO (lancamento.dtinc). Medido nos meses fechados: a fração acumulada do
|movimento| final visível em cada dia. É o divisor da estratégia
razao_completude (mês corrente) e do estimador do mês em fechamento (M-1).

Usa |valor| (movimento absoluto), não o líquido: sinal alternado faria a
fração oscilar e até passar de 1.
"""
from __future__ import annotations

DIA_MAX = 45          # depois disso consideramos o mês 100% escriturado
PISO_COMPLETUDE = 0.30  # abaixo disso NUNCA dividir — usar estratégia de nível


def _frac_media(por_mes: dict[str, dict[int, float]]) -> dict[int, float]:
    """De {mes: {dia: valor_abs}} para {dia: frac acumulada media entre meses}."""
    fracs_por_dia: dict[int, list[float]] = {d: [] for d in range(DIA_MAX + 1)}
    for _mes, dias in por_mes.items():
        total = sum(dias.values())
        if total <= 0:
            continue
        acum = 0.0
        serie: dict[int, float] = {}
        for d in range(DIA_MAX + 1):
            acum += dias.get(d, 0.0)
            serie[d] = acum / total
        for d, f in serie.items():
            fracs_por_dia[d].append(f)
    return {d: (sum(fs) / len(fs)) if fs else 0.0 for d, fs in fracs_por_dia.items()}


def montar_curva(rows: list[dict],
                 mapa_ag_linha: dict[str, str | None]) -> dict:
    ag_mes: dict[str, dict[str, dict[int, float]]] = {}
    linha_mes: dict[str, dict[str, dict[int, float]]] = {}
    glob_mes: dict[str, dict[int, float]] = {}
    for r in rows:
        dia = max(0, min(DIA_MAX, int(r["dia_rel"])))
        v = abs(float(r["valor_abs"]))
        ag = r["agrupador"]
        mes = r["mes"]
        d1 = ag_mes.setdefault(ag, {}).setdefault(mes, {})
        d1[dia] = d1.get(dia, 0.0) + v
        rot = mapa_ag_linha.get(ag)
        if rot:
            d2 = linha_mes.setdefault(rot, {}).setdefault(mes, {})
            d2[dia] = d2.get(dia, 0.0) + v
        d3 = glob_mes.setdefault(mes, {})
        d3[dia] = d3.get(dia, 0.0) + v
    return {
        "ag": {ag: _frac_media(m) for ag, m in ag_mes.items()},
        "linha": {rot: _frac_media(m) for rot, m in linha_mes.items()},
        "global": _frac_media(glob_mes),
    }


def completude_em(curva: dict, agrupador: str | None, linha: str | None,
                  dia_rel: int) -> float:
    dia = max(0, min(DIA_MAX, int(dia_rel)))
    for serie in (
        curva.get("ag", {}).get(agrupador) if agrupador else None,
        curva.get("linha", {}).get(linha) if linha else None,
        curva.get("global") or None,
    ):
        if serie:
            return max(0.0, min(1.0, serie.get(dia, 1.0 if dia >= DIA_MAX else 0.0)))
    return 1.0
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/previsao/test_completude.py -q`
Expected: 4 passed

- [ ] **Step 5: Commitar**

```bash
git add api/previsao/completude.py tests/previsao/test_completude.py
git commit -m "feat(previsao): curva de completude de escrituracao por agrupador/linha"
```

---

### Task 3: Estratégias do motor (`api/previsao/motor.py`, parte 1)

Funções PURAS, uma por estratégia. Todas devolvem `{"previsto": float, "estrategia": str, "premissas": list[str]}`. Convenção de sinal: custo/despesa **negativos** (como no razão).

**Files:**
- Create: `api/previsao/motor.py`
- Test: `tests/previsao/test_motor_estrategias.py`

**Interfaces:**
- Consumes: `PISO_COMPLETUDE` de `api/previsao/completude.py`.
- Produces (Tasks 4/6/8 dependem):
  - `prever_receita(real_acum: float, meta_acum: float, meta_mes: float, ating_hist: float | None, dias_meta_decorridos: int) -> dict`
  - `prever_pct_receita(receita_prev: float, pct: float, nome_pct: str) -> dict` (pct JÁ com sinal: ex. -0.0778)
  - `prever_nivel(hist: list[float], rotulo_fonte: str) -> dict` (mediana; lista vazia -> previsto 0.0 com premissa "sem historico")
  - `prever_razao_completude(razao_mtd: float, frac: float, fallback: dict) -> dict` (se `frac < PISO_COMPLETUDE` devolve o fallback com premissa adicional)
  - `prever_frete_compra(razao_mtd: float, vfc_mtd: float, receita_prev: float, receita_mtd: float, razao_custo_receita: float) -> dict`
  - `prever_sazonal(vals6: list[float], indices6: list[float], indice_alvo: float) -> dict`
  - `mediana(vals: list[float]) -> float`

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/previsao/test_motor_estrategias.py
"""Cada estratégia recomputável à mão. Sinal: custo NEGATIVO."""
from __future__ import annotations

from api.previsao.motor import (mediana, prever_frete_compra, prever_nivel,
                                prever_pct_receita, prever_razao_completude,
                                prever_receita, prever_sazonal)


def test_receita_ritmo_puro_apos_3_dias_uteis():
    # meta 100, acumulada 40; realizado 36 -> ritmo 0,90; restante 60*0,90=54
    r = prever_receita(real_acum=36.0, meta_acum=40.0, meta_mes=100.0,
                       ating_hist=0.85, dias_meta_decorridos=3)
    assert abs(r["previsto"] - (36.0 + 60.0 * 0.90)) < 1e-9
    assert r["estrategia"] == "driver_fiscal"
    assert any("ritmo" in p for p in r["premissas"])


def test_receita_blend_no_primeiro_dia_util():
    # w = 1/3: ritmo = (1/3)*0,90 + (2/3)*0,85 = 0,8667
    r = prever_receita(36.0, 40.0, 100.0, 0.85, dias_meta_decorridos=1)
    ritmo = (1 / 3) * 0.90 + (2 / 3) * 0.85
    assert abs(r["previsto"] - (36.0 + 60.0 * ritmo)) < 1e-9


def test_receita_sem_meta_cai_no_historico():
    r = prever_receita(0.0, 0.0, 100.0, 0.85, 0)
    assert abs(r["previsto"] - 85.0) < 1e-9  # meta_mes * ating_hist


def test_pct_receita_sinal_negativo():
    r = prever_pct_receita(receita_prev=1000.0, pct=-0.0778, nome_pct="federais 6m")
    assert abs(r["previsto"] - (-77.8)) < 1e-9
    assert r["estrategia"] == "pct_receita"


def test_nivel_mediana():
    assert mediana([1.0, 5.0, 3.0]) == 3.0
    assert mediana([1.0, 2.0, 3.0, 4.0]) == 2.5
    r = prever_nivel([-700.0, -760.0, -720.0], "folha 3m")
    assert r["previsto"] == -720.0 and r["estrategia"] == "nivel"
    assert prever_nivel([], "x")["previsto"] == 0.0


def test_razao_completude_e_guarda_de_divisor():
    fb = prever_nivel([-400.0, -420.0, -410.0], "fallback")
    ok = prever_razao_completude(razao_mtd=-200.0, frac=0.5, fallback=fb)
    assert abs(ok["previsto"] - (-400.0)) < 1e-9
    assert ok["estrategia"] == "razao_completude"
    guard = prever_razao_completude(razao_mtd=-10.0, frac=0.1, fallback=fb)
    assert guard["previsto"] == fb["previsto"]          # nunca divide por quase-zero
    assert any("completude" in p for p in guard["premissas"])


def test_frete_compra_conhecido_mais_projecao():
    # razao mostra -100, viagens mostram -180 (mais informacao) -> conhecido=-180
    # receita prevista 1000, ja realizada 300 -> restante 700 * razao -0,5 = -350
    r = prever_frete_compra(razao_mtd=-100.0, vfc_mtd=180.0, receita_prev=1000.0,
                            receita_mtd=300.0, razao_custo_receita=-0.5)
    assert abs(r["previsto"] - (-180.0 + -350.0)) < 1e-9
    assert r["estrategia"] == "frete_compra"


def test_sazonal_nivel_x_indice():
    # 6 meses de -100 com indices 1.0 -> nivel -100; indice alvo 0,8 -> -80
    r = prever_sazonal([-100.0] * 6, [1.0] * 6, indice_alvo=0.8)
    assert abs(r["previsto"] - (-80.0)) < 1e-9
    assert r["estrategia"] == "sazonal"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/previsao/test_motor_estrategias.py -q`
Expected: FAIL

- [ ] **Step 3: Implementar**

```python
# api/previsao/motor.py
"""Motor da previsão de fechamento — 100% PURO (sem banco, sem datas de hoje).

Convenção de sinal = razão da DRE: receita POSITIVA, custo/despesa NEGATIVOS
(valor = credito - debito). Toda fórmula soma; nunca subtrai por natureza.
Cada estratégia devolve {"previsto", "estrategia", "premissas": [str]}.
"""
from __future__ import annotations

from api.previsao.completude import PISO_COMPLETUDE

PESO_DIAS_PLENO = 3  # dias com meta decorridos para o ritmo observado valer 100%


def _res(previsto: float, estrategia: str, premissas: list[str]) -> dict:
    return {"previsto": float(previsto), "estrategia": estrategia,
            "premissas": premissas}


def mediana(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    meio = n // 2
    return s[meio] if n % 2 else (s[meio - 1] + s[meio]) / 2.0


def prever_receita(real_acum: float, meta_acum: float, meta_mes: float,
                   ating_hist: float | None, dias_meta_decorridos: int) -> dict:
    base_hist = ating_hist if ating_hist is not None else 1.0
    ritmo_obs = (real_acum / meta_acum) if meta_acum else None
    w = min(1.0, max(0, dias_meta_decorridos) / PESO_DIAS_PLENO)
    ritmo = (w * ritmo_obs + (1 - w) * base_hist) if ritmo_obs is not None else base_hist
    meta_rest = max(0.0, meta_mes - meta_acum)
    previsto = real_acum + meta_rest * ritmo
    return _res(previsto, "driver_fiscal", [
        f"realizado fiscal MTD R$ {real_acum:,.0f} sobre meta acumulada R$ {meta_acum:,.0f}",
        f"ritmo aplicado ao restante da meta: {ritmo:.1%} "
        f"(observado peso {w:.0%}, historico 3m {base_hist:.1%})",
        f"meta restante do mes: R$ {meta_rest:,.0f}",
    ])


def prever_pct_receita(receita_prev: float, pct: float, nome_pct: str) -> dict:
    return _res(receita_prev * pct, "pct_receita",
                [f"{pct:.2%} da receita prevista ({nome_pct})"])


def prever_nivel(hist: list[float], rotulo_fonte: str) -> dict:
    if not hist:
        return _res(0.0, "nivel", [f"sem historico ({rotulo_fonte})"])
    m = mediana(hist)
    return _res(m, "nivel",
                [f"mediana de {len(hist)} meses fechados ({rotulo_fonte})"])


def prever_razao_completude(razao_mtd: float, frac: float, fallback: dict) -> dict:
    if frac < PISO_COMPLETUDE:
        return _res(fallback["previsto"], fallback["estrategia"],
                    fallback["premissas"] + [
                        f"completude esperada {frac:.0%} abaixo do piso "
                        f"{PISO_COMPLETUDE:.0%} - usando fallback"])
    return _res(razao_mtd / frac, "razao_completude", [
        f"razao MTD R$ {razao_mtd:,.0f} dividido pela completude esperada {frac:.0%}"])


def prever_frete_compra(razao_mtd: float, vfc_mtd: float, receita_prev: float,
                        receita_mtd: float, razao_custo_receita: float) -> dict:
    conhecido = min(razao_mtd, -abs(vfc_mtd))  # mais negativo = mais custo conhecido
    receita_rest = max(0.0, receita_prev - receita_mtd)
    projetado = receita_rest * razao_custo_receita
    return _res(conhecido + projetado, "frete_compra", [
        f"conhecido: max(|razao| R$ {abs(razao_mtd):,.0f}, |frete compra viagens| "
        f"R$ {abs(vfc_mtd):,.0f})",
        f"projecao: {abs(razao_custo_receita):.1%} da receita restante prevista "
        f"(razao custo/receita 6m)"])


def prever_sazonal(vals6: list[float], indices6: list[float],
                   indice_alvo: float) -> dict:
    if not vals6:
        return _res(0.0, "sazonal", ["sem historico"])
    dessaz = [v / i for v, i in zip(vals6, indices6) if i]
    nivel = sum(dessaz) / len(dessaz) if dessaz else 0.0
    return _res(nivel * indice_alvo, "sazonal", [
        f"nivel 6m dessazonalizado R$ {nivel:,.0f} x indice do mes {indice_alvo:.2f}"])
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/previsao/test_motor_estrategias.py -q`
Expected: 8 passed

- [ ] **Step 5: Commitar**

```bash
git add api/previsao/motor.py tests/previsao/test_motor_estrategias.py
git commit -m "feat(previsao): estrategias puras do motor de previsao"
```

---

### Task 4: Cascata, cenários, ajustes e M-1 (`api/previsao/motor.py`, parte 2)

**Files:**
- Modify: `api/previsao/motor.py` (acrescentar no fim)
- Test: `tests/previsao/test_motor_cascata.py`

**Interfaces:**
- Consumes: `DRE_MODELO` de `api/queries.py` (import direto — leitura, não edição); `completude_em`/`PISO_COMPLETUDE` da Task 2; estratégias da Task 3.
- Produces (Tasks 6/8 dependem):
  - `estrategia_do_agrupador(ag: str) -> str` — decide por prefixo normalizado: `'CV - FRETE AGREGADOS'|'CV - FRETE TERCEIROS'` → `"frete_compra"`; demais `'CV - '` → `"razao_completude"`; `'CF - FOLHA'|'CF - PESSOAL'|'OVERHEAD - FOLHA'` → `"nivel"`; `'CR - '` → `"nivel"`; demais `'CF - '|'OVERHEAD - '` → `"razao_completude"`; `'FINANC - '|'INDENIZA'|'OUTRAS '|'(1, '|'DESPESAS N'|'RECEITA - VENDA'|'ANULA'|'DESCONTOS'` → `"sazonal"`; `'CLASSIFICAR'` e desconhecidos → `"runrate"` (nível 3m).
  - `norm(s: str) -> str` — normalização NFKD/upper idêntica à do `get_dre`.
  - `linha_do_agrupador(ag: str) -> str | None` — wrapper de `_dre_aloca` com `norm` (reimplementa o matching localmente para não depender de função interna do get_dre).
  - `montar_cascata(direta: dict[str, float]) -> dict[str, float]` — preenche TODAS as linhas do `DRE_MODELO` (2 passadas: diretas, depois fórmulas em ordem de declaração).
  - `banda_fallback(base: float, hist6: list[float], frac_restante: float) -> tuple[float, float]` — (pess, otim) = base ∓ pstdev(hist6) × frac_restante.
  - `banda_calibrada(base: float, calib_linha: dict | None, dia_util: int) -> tuple[float, float] | None` — interpola linearmente p20/p80 entre os dias calibrados (`{"5": {"p20": ..., "p80": ...}, ...}` com erro RELATIVO); None se não houver calibração da linha.
  - `aplicar_ajuste(previsto: float, ajuste: dict | None) -> tuple[float, float]` — retorna (efetivo, shift): tipo `delta` → (previsto+valor, valor); `valor` → (valor, valor−previsto); None → (previsto, 0.0).
  - `estimar_m1(razao_ag: dict[str, float], curva: dict, dia_rel: int, fallback_por_ag: dict[str, dict]) -> dict[str, dict]` — por agrupador: `frac >= 0.97` → `{"previsto": razao, "estrategia": "consolidado"}`; `frac < PISO_COMPLETUDE` → fallback da Task 3; senão razão/frac com estratégia `"razao_completude"`.

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/previsao/test_motor_cascata.py
from __future__ import annotations

from api.previsao.motor import (aplicar_ajuste, banda_calibrada, banda_fallback,
                                estimar_m1, estrategia_do_agrupador,
                                linha_do_agrupador, montar_cascata, norm)


def test_estrategia_por_prefixo():
    assert estrategia_do_agrupador("CV - FRETE AGREGADOS") == "frete_compra"
    assert estrategia_do_agrupador("CV - FRETE TERCEIROS") == "frete_compra"
    assert estrategia_do_agrupador("CV - COMBUSTIVEL") == "razao_completude"
    assert estrategia_do_agrupador("CF - FOLHA MOT") == "nivel"
    assert estrategia_do_agrupador("OVERHEAD - FOLHA ADM") == "nivel"
    assert estrategia_do_agrupador("CF - DESPESAS ADM") == "razao_completude"
    assert estrategia_do_agrupador("FINANC - BANCOS") == "sazonal"
    assert estrategia_do_agrupador("CLASSIFICAR") == "runrate"
    # acento nao muda a decisao (normalizacao NFKD como no get_dre)
    assert estrategia_do_agrupador("CV - COMBUSTÍVEL") == "razao_completude"


def test_linha_do_agrupador_casa_com_dre_modelo():
    assert linha_do_agrupador("CV - COMBUSTIVEL") == "CUSTO VARIAVEL"
    assert linha_do_agrupador("CF - FOLHA MOT") == "CUSTO FIXO"
    assert linha_do_agrupador("RECEITA OPERACIONAL BRUTA AGREGADO") == "RECEITA BRUTA"
    assert linha_do_agrupador("FINANC - BANCOS") == "RESULTADO FINANCEIRO"
    assert linha_do_agrupador("XPTO SEM LINHA") is None


def test_cascata_fecha_o_resultado():
    direta = {"RECEITA BRUTA": 1000.0, "IMPOSTOS FEDERAIS": -78.0,
              "IMPOSTOS ESTADUAIS": -98.0, "IMPOSTOS MUNICIPAIS": -1.0,
              "CONTRIBUICAO PREVIDENCIARIA": -9.0, "ANULACOES": -5.0,
              "DESCONTOS": -2.0, "CUSTO FIXO": -200.0, "CUSTO VARIAVEL": -400.0,
              "CREDITOS TRIBUTARIOS": 50.0, "OVERHEAD": -100.0,
              "INDENIZACOES": -10.0, "OUTRAS DESPESAS/RECEITAS OPERACIONAIS": 5.0,
              "RESULTADO FINANCEIRO": -40.0, "RESULTADO NAO OPERACIONAL": 3.0}
    c = montar_cascata(direta)
    assert abs(c["DEDUCOES DA RECEITA"] - (-193.0)) < 1e-9
    assert abs(c["RECEITA LIQUIDA"] - 807.0) < 1e-9
    assert abs(c["CSP"] - (-550.0)) < 1e-9
    assert abs(c["LUCRO BRUTO"] - 257.0) < 1e-9
    assert abs(c["DESPESAS"] - (-105.0)) < 1e-9
    assert abs(c["RESULTADO OPERACIONAL (LOP 1)"] - 152.0) < 1e-9
    assert abs(c["RESULTADO DO EXERCICIO"] - 115.0) < 1e-9


def test_bandas():
    pess, otim = banda_fallback(100.0, [10.0, 10.0, 10.0, 10.0, 10.0, 10.0], 0.5)
    assert pess == otim == 100.0  # pstdev 0
    pess, otim = banda_fallback(100.0, [0.0, 20.0], 1.0)  # pstdev 10
    assert (pess, otim) == (90.0, 110.0)
    calib = {"5": {"p20": -0.10, "p80": 0.06}, "10": {"p20": -0.04, "p80": 0.02}}
    b = banda_calibrada(-1000.0, calib, 5)
    # erro relativo aplicado sobre |base|; p20 e o lado pessimista p/ resultado
    assert b is not None
    pess, otim = b
    assert abs(pess - (-1100.0)) < 1e-9 and abs(otim - (-940.0)) < 1e-9
    meio = banda_calibrada(-1000.0, calib, 7)  # interpolacao 5..10 (40%)
    assert abs(meio[0] - (-1000.0 - 1000.0 * 0.076)) < 1e-6
    assert banda_calibrada(1.0, None, 5) is None


def test_aplicar_ajuste():
    assert aplicar_ajuste(100.0, None) == (100.0, 0.0)
    assert aplicar_ajuste(100.0, {"tipo": "delta", "valor": -30.0}) == (70.0, -30.0)
    ef, shift = aplicar_ajuste(100.0, {"tipo": "valor", "valor": 250.0})
    assert (ef, shift) == (250.0, 150.0)


def test_estimar_m1_consolida_estima_e_faz_fallback():
    curva = {"ag": {"A": {d: (1.0 if d >= 40 else 0.5) for d in range(46)},
                    "B": {d: 0.1 for d in range(46)}},
             "linha": {}, "global": {d: 0.5 for d in range(46)}}
    fb = {"B": {"previsto": -700.0, "estrategia": "nivel", "premissas": ["fb"]}}
    r = estimar_m1({"A": -50.0, "B": -70.0}, curva, dia_rel=41, fallback_por_ag=fb)
    assert r["A"]["estrategia"] == "consolidado" and r["A"]["previsto"] == -50.0
    assert r["B"]["previsto"] == -700.0            # frac 0,1 < piso -> fallback
    r2 = estimar_m1({"A": -25.0}, curva, dia_rel=35, fallback_por_ag={})
    assert abs(r2["A"]["previsto"] - (-50.0)) < 1e-9   # -25 / 0,5
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/previsao/test_motor_cascata.py -q`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implementar (acrescentar ao fim de `api/previsao/motor.py`)**

```python
import unicodedata

from api.queries import DRE_MODELO
from api.previsao.completude import completude_em

CONSOLIDADO_EM = 0.97  # completude esperada a partir da qual o razao e a verdade


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s.upper()).encode("ascii", "ignore").decode()


def linha_do_agrupador(ag: str) -> str | None:
    na = norm(ag)
    for rotulo, _nivel, tipo, sel in DRE_MODELO:
        if tipo == "formula":
            continue
        for s in sel:
            ns = norm(s)
            if (tipo == "nome" and na == ns) or (tipo == "pref" and na.startswith(ns)):
                return rotulo
    return None


_ESTRATEGIA_PREFIXOS = [
    ("CV - FRETE AGREGADOS", "frete_compra"),
    ("CV - FRETE TERCEIROS", "frete_compra"),
    ("CF - FOLHA", "nivel"),
    ("CF - PESSOAL", "nivel"),
    ("OVERHEAD - FOLHA", "nivel"),
    ("CR - ", "nivel"),
    ("CV - ", "razao_completude"),
    ("CF - ", "razao_completude"),
    ("OVERHEAD - ", "razao_completude"),
    ("FINANC - ", "sazonal"),
    ("INDENIZA", "sazonal"),
    ("OUTRAS ", "sazonal"),
    ("(1, ", "sazonal"),
    ("DESPESAS N", "sazonal"),
    ("RECEITA - VENDA", "sazonal"),
    ("ANULA", "sazonal"),
    ("DESCONTOS", "sazonal"),
]


def estrategia_do_agrupador(ag: str) -> str:
    na = norm(ag)
    for pref, estrat in _ESTRATEGIA_PREFIXOS:
        if na.startswith(norm(pref)):
            return estrat
    return "runrate"


def montar_cascata(direta: dict[str, float]) -> dict[str, float]:
    """Preenche todas as linhas do DRE_MODELO: diretas primeiro, fórmulas em
    ordem de declaração (mesma 2-passada do get_dre)."""
    out: dict[str, float] = {}
    for rotulo, _nivel, tipo, _sel in DRE_MODELO:
        if tipo != "formula":
            out[rotulo] = float(direta.get(rotulo, 0.0))
    for rotulo, _nivel, tipo, sel in DRE_MODELO:
        if tipo == "formula":
            out[rotulo] = sum(out.get(r, 0.0) for r in sel)
    return out


def banda_fallback(base: float, hist6: list[float],
                   frac_restante: float) -> tuple[float, float]:
    if len(hist6) < 2:
        return base, base
    media = sum(hist6) / len(hist6)
    var = sum((v - media) ** 2 for v in hist6) / len(hist6)
    meio = (var ** 0.5) * max(0.0, min(1.0, frac_restante))
    return base - meio, base + meio


def banda_calibrada(base: float, calib_linha: dict | None,
                    dia_util: int) -> tuple[float, float] | None:
    if not calib_linha:
        return None
    dias = sorted(int(d) for d in calib_linha)
    if not dias:
        return None
    d = max(dias[0], min(dias[-1], dia_util))
    lo = max(x for x in dias if x <= d)
    hi = min(x for x in dias if x >= d)
    w = 0.0 if hi == lo else (d - lo) / (hi - lo)
    def _mix(campo: str) -> float:
        a = calib_linha[str(lo)][campo]
        b = calib_linha[str(hi)][campo]
        return a + (b - a) * w
    esc = abs(base)
    return base + _mix("p20") * esc, base + _mix("p80") * esc


def aplicar_ajuste(previsto: float, ajuste: dict | None) -> tuple[float, float]:
    if not ajuste:
        return previsto, 0.0
    if ajuste["tipo"] == "delta":
        return previsto + ajuste["valor"], ajuste["valor"]
    return ajuste["valor"], ajuste["valor"] - previsto


def estimar_m1(razao_ag: dict[str, float], curva: dict, dia_rel: int,
               fallback_por_ag: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ag, valor in razao_ag.items():
        rot = linha_do_agrupador(ag)
        frac = completude_em(curva, ag, rot, dia_rel)
        if frac >= CONSOLIDADO_EM:
            out[ag] = _res(valor, "consolidado",
                           [f"razao {frac:.0%} escriturado - consolidado"])
        elif frac < PISO_COMPLETUDE:
            fb = fallback_por_ag.get(ag) or _res(valor, "razao_parcial",
                                                 ["sem fallback disponivel"])
            out[ag] = _res(fb["previsto"], fb["estrategia"], fb["premissas"] + [
                f"completude esperada {frac:.0%} abaixo do piso - fallback"])
        else:
            out[ag] = _res(valor / frac, "razao_completude", [
                f"razao parcial R$ {valor:,.0f} / completude esperada {frac:.0%}"])
    return out
```

- [ ] **Step 4: Rodar e ver passar (novos + regressão das estratégias)**

Run: `uv run pytest tests/previsao/ -q`
Expected: todos passed

- [ ] **Step 5: Commitar**

```bash
git add api/previsao/motor.py tests/previsao/test_motor_cascata.py
git commit -m "feat(previsao): cascata DRE, cenarios, ajustes e estimador do mes em fechamento"
```

---

### Task 5: SQL do módulo (`api/previsao/sql.py`) — validado ao vivo

**Files:**
- Create: `api/previsao/sql.py`
- Test: `tests/previsao/test_sql.py`

**Interfaces:**
- Consumes: `DRE_AG_SQL`, `DRE_AJUSTADAS_SQL`, `VG_DIARIO_SQL`, `BREAKEVEN_SQL` são importados de `api.queries` pelo `servico` (Task 6) — este arquivo NÃO os duplica.
- Produces (Tasks 6/8 dependem): constantes `COMPLETUDE_SQL`, `ATING_HIST_SQL`, `VFC_MTD_SQL`, `CTAPLUS_MTD_SQL`, `CAP_MES_SQL`, `RAZAO_ASOF_SQL` (todas com params nomeados `%(de)s`/`%(ate)s`, e `%(asof)s` na as-of); função `meses_fechados_prev(hoje: date, n: int) -> list[str]` (delega para `api.orcamento.sql.meses_fechados` — reexport para o backtest não importar dois lugares).

- [ ] **Step 1: Escrever o arquivo**

```python
# api/previsao/sql.py
"""SQL novos da previsão — PostgreSQL 9.3, LATIN-1, somente leitura.

O razão por agrupador (mês corrente e histórico) REUSA queries.DRE_AG_SQL /
DRE_AJUSTADAS_SQL (mesma pergunta, janelas diferentes). Aqui ficam só as
perguntas que a base ainda não fazia.
"""
from __future__ import annotations

from datetime import date

from api.orcamento.sql import meses_fechados as meses_fechados_prev  # noqa: F401

# Curva de completude: |movimento| por (mes de competencia, agrupador,
# dias desde o 1o dia do mes em que o lancamento foi INCLUIDO - dtinc).
COMPLETUDE_SQL = """
SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes,
       coalesce(ag.descricao, 'CLASSIFICAR') AS agrupador,
       greatest(0, least(45,
         (l.dtinc - date_trunc('month', l.dtlancamento)::date)))::int AS dia_rel,
       sum(abs(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0)))::float8 AS valor_abs
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  AND p.ativoinativo = 1
LEFT JOIN sulista.agrupadorgerencial ag ON ag.reduzido = l.reduzido
  AND ag.grupo = l.grupo
WHERE l.dtlancamento >= %(de)s::date AND l.dtlancamento < %(ate)s::date
  AND coalesce(l.historico, 0) <> 18
  AND (ag.descricao IS NOT NULL OR p.estrutural ~ '^[34]')
GROUP BY 1, 2, 3
"""

# Razao por agrupador COMO ERA VISIVEL em uma data passada (backtest as-of).
RAZAO_ASOF_SQL = """
SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes,
       coalesce(ag.descricao, 'CLASSIFICAR') AS agrupador,
       sum(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0))::float8 AS valor
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  AND p.ativoinativo = 1
LEFT JOIN sulista.agrupadorgerencial ag ON ag.reduzido = l.reduzido
  AND ag.grupo = l.grupo
WHERE l.dtlancamento >= %(de)s::date AND l.dtlancamento < %(ate)s::date
  AND l.dtinc <= %(asof)s::date
  AND coalesce(l.historico, 0) <> 18
  AND (ag.descricao IS NOT NULL OR p.estrutural ~ '^[34]')
GROUP BY 1, 2
"""

# Atingimento realizado/meta por mes (3 fontes oficiais x meta diaria tipo=1).
# Mesmos filtros fiscais do VG_DIARIO_SQL, agregados por mes para a janela pedida.
ATING_HIST_SQL = """
SELECT mes, sum(realizado)::float8 AS realizado, sum(meta)::float8 AS meta FROM (
  SELECT to_char(dtemissao,'YYYY-MM') AS mes,
         coalesce(valortotalprestacao,0) AS realizado, 0::numeric AS meta
  FROM conhecimento
  WHERE dtemissao >= %(de)s::date AND dtemissao < %(ate)s::date
    AND grupo = 1 AND empresa = 1 AND unidade = 1 AND numero < 1000000
    AND dtcancelamento IS NULL AND situacaocte = 3 AND tipo IN (1,4)
  UNION ALL
  SELECT to_char(dtemissao,'YYYY-MM'), coalesce(valor_cte,0), 0
  FROM sulista.faturamentokmm
  WHERE dtemissao >= %(de)s::date AND dtemissao < %(ate)s::date
  UNION ALL
  SELECT to_char(dtemissao,'YYYY-MM'), coalesce(valortotalbruto,0), 0
  FROM notafiscalservico
  WHERE dtemissao >= %(de)s::date AND dtemissao < %(ate)s::date
    AND grupo = 1 AND empresa = 1 AND numero < 1000000
    AND dtcancelamento IS NULL
    AND (emissaoeletronica = 2 OR (emissaoeletronica = 1 AND situacaonfse = 3))
  UNION ALL
  SELECT to_char(dt,'YYYY-MM'), 0, coalesce(valor,0)
  FROM sulista.metafaturamento_agrupamentoclientedia
  WHERE dt >= %(de)s::date AND dt < %(ate)s::date AND tipo = 1
) t GROUP BY 1 ORDER BY 1
"""

# Frete de compra das viagens no periodo (proxy antecipada do custo de
# agregados+terceiros JUNTOS; o acerto contabil chega ~6 dias depois).
# Sem join com veiculo de proposito: o split agregado x terceiro e feito pela
# participacao historica das duas linhas no razao (premissa declarada no motor).
VFC_MTD_SQL = """
SELECT count(*)::int AS viagens,
       sum(coalesce(valorfrete,0))::float8 AS receita_viagens,
       sum(coalesce(valorfretecompra,0))::float8 AS frete_compra
FROM programacaoembarque
WHERE dtcancelamento IS NULL AND semaforo = 1
  AND dtsaida >= %(de)s::date AND dtsaida < %(ate)s::date
"""

# Combustivel dos abastecimentos (validacao cruzada do CV - COMBUSTIVEL).
# Filtra veiculos de agregado/terceiro (custo deles e repassado no acerto,
# nao e a linha de combustivel do razao).
CTAPLUS_MTD_SQL = """
SELECT sum(coalesce(c.custo,0))::float8 AS custo,
       count(*)::int AS abastecimentos
FROM sulista.ctaplus_abastecimentos c
LEFT JOIN veiculo v ON v.placa = c.veiculo_placa
WHERE c.data_inicio_abastecimento >= %(de)s::date
  AND c.data_inicio_abastecimento < %(ate)s::date
  AND coalesce(v.utilizacaoveiculo, 'TRA') NOT IN ('AGR', 'TER')
"""

# Contas a pagar com vencimento no mes (contexto de caixa, so KPI informativo).
CAP_MES_SQL = """
SELECT count(*)::int AS titulos,
       sum(coalesce(valorpendente,0))::float8 AS valor
FROM contaapagar
WHERE valorpendente > 0
  AND dtvencimento >= %(de)s::date AND dtvencimento < %(ate)s::date
"""
```

- [ ] **Step 2: Validar CADA query ao vivo na réplica (túnel de pé)**

A partir da raiz do repo (`cortex-sulista/`), uma por vez, com janelas reais:

```bash
scripts/db.sh psql -c "SELECT 1"   # tunel ok?
scripts/db.sh psql -c "SELECT count(*) FROM (SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes, coalesce(ag.descricao,'CLASSIFICAR') AS agrupador, greatest(0, least(45, (l.dtinc - date_trunc('month', l.dtlancamento)::date)))::int AS dia_rel, sum(abs(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0)))::float8 AS valor_abs FROM lancamento l JOIN planoconta p ON p.reduzido=l.reduzido AND p.grupo=l.grupo AND p.ativoinativo=1 LEFT JOIN sulista.agrupadorgerencial ag ON ag.reduzido=l.reduzido AND ag.grupo=l.grupo WHERE l.dtlancamento >= '2026-02-01'::date AND l.dtlancamento < '2026-08-01'::date AND coalesce(l.historico,0) <> 18 AND (ag.descricao IS NOT NULL OR p.estrutural ~ '^[34]') GROUP BY 1,2,3) t"
```

Repetir o padrão para `ATING_HIST_SQL` (de=2026-05-01, ate=2026-08-01 — deve devolver 3 linhas com atingimento ~85% em jul), `VFC_MTD_SQL` (de=2026-07-01, ate=2026-08-01 — esperado ~R$ 5,98 mi de frete_compra, ~4.700 viagens), `CTAPLUS_MTD_SQL` e `CAP_MES_SQL` (de=2026-08-01, ate=2026-09-01 — esperado ~R$ 6,29 mi / ~986 títulos). **Se uma coluna divergir** (ex.: o vínculo `veiculo.utilizacaoveiculo`/`veiculo.placa` no join do ctaplus), conferir o join canônico usado pelas queries vizinhas (`grep -n "utilizacaoveiculo" api/queries.py`) e corrigir AQUI e no teste antes de seguir — a validação ao vivo é o gate desta task.

- [ ] **Step 3: Escrever os testes (puros, estilo `tests/orcamento/test_sql.py`)**

```python
# tests/previsao/test_sql.py
"""Guardas de compatibilidade do SQL (PG 9.3 / LATIN-1 / convencoes da DRE)."""
from __future__ import annotations

from datetime import date

from api.previsao.sql import (ATING_HIST_SQL, CAP_MES_SQL, COMPLETUDE_SQL,
                              CTAPLUS_MTD_SQL, RAZAO_ASOF_SQL, VFC_MTD_SQL,
                              meses_fechados_prev)

TODAS = (COMPLETUDE_SQL, RAZAO_ASOF_SQL, ATING_HIST_SQL, VFC_MTD_SQL,
         CTAPLUS_MTD_SQL, CAP_MES_SQL)


def test_sem_recursos_ausentes_no_pg93():
    for sql in TODAS:
        assert "FILTER (WHERE" not in sql.upper()
        assert "LATERAL" not in sql.upper()


def test_somente_latin1():
    for sql in TODAS:
        sql.encode("latin-1")  # explode se houver travessao/setas


def test_razao_trata_lado_nulo_e_historico_18():
    for sql in (COMPLETUDE_SQL, RAZAO_ASOF_SQL):
        assert "coalesce(l.valorcredito,0)" in sql
        assert "coalesce(l.valordebito,0)" in sql
        assert "coalesce(l.historico, 0) <> 18" in sql


def test_asof_filtra_por_dtinc():
    assert "l.dtinc <= %(asof)s::date" in RAZAO_ASOF_SQL


def test_filtros_fiscais_canonicos_no_atingimento():
    assert "situacaocte = 3" in ATING_HIST_SQL
    assert "tipo IN (1,4)" in ATING_HIST_SQL
    assert "numero < 1000000" in ATING_HIST_SQL
    assert "tipo = 1" in ATING_HIST_SQL  # meta


def test_viagens_com_filtros_canonicos():
    assert "dtcancelamento IS NULL" in VFC_MTD_SQL
    assert "semaforo = 1" in VFC_MTD_SQL


def test_meses_fechados_reexportado():
    assert meses_fechados_prev(date(2026, 8, 2), 6)[-1] == "2026-07"
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/previsao/test_sql.py -q`
Expected: 7 passed

- [ ] **Step 5: Commitar**

```bash
git add api/previsao/sql.py tests/previsao/test_sql.py
git commit -m "feat(previsao): SQL de completude, atingimento, viagens, ctaplus e cap (validado na replica)"
```

---

### Task 6: Orquestração (`api/previsao/servico.py` + fachada em `__init__.py`)

**Files:**
- Create: `api/previsao/servico.py`
- Modify: `api/previsao/__init__.py`
- Test: `tests/previsao/test_servico.py`

**Interfaces:**
- Consumes: Tasks 1–5; de `api.queries`: `DRE_AG_SQL`, `DRE_AJUSTADAS_SQL`, `DRE_MODELO`, `VG_DIARIO_SQL`, `BREAKEVEN_SQL`, `_ponto_equilibrio`, `ler_ajustes`, `_comp_bounds`, `cached`; de `api.orcamento`: `armazenamento.versao_vigente/ler_linhas/init_db/DB_PATH`, `derivacao.indices_sazonais`, `rollup.mapa_conta_linha`, `sql.AGRUP_CONTA_SQL` (conferir os nomes das colunas em `api/orcamento/sql.py:40-52`; o comparativo em `api/orcamento/servico.py` já monta o dict conta→agrupador — copiar de lá se divergirem), `servico.meses_circulares`; `api.db.get_conn`.
- Produces:
  - `resolver_modo(mes: str, hoje: date) -> tuple[str, int]` — `("corrente", dias_desde_inicio_do_mes)` | `("fechando", dia_rel_desde_inicio_de_M1)` | `("fechado", 0)`. `fechando` = mês imediatamente anterior com `dia_rel <= 45`.
  - `montar_resposta(ctx: dict) -> dict` — **PURA**; ctx documentado no docstring (abaixo).
  - `get_previsao(mes: str | None = None, hoje: date | None = None) -> dict` — I/O + snapshot best-effort.
  - Fachada: `api.previsao.get_previsao_fechamento(mes=None)` com `@cached(ttl=300)`.

- [ ] **Step 1: Escrever os testes que falham (sobre as partes puras)**

```python
# tests/previsao/test_servico.py
from __future__ import annotations

from datetime import date

from api.previsao.servico import montar_resposta, resolver_modo


def test_resolver_modo():
    assert resolver_modo("2026-08", date(2026, 8, 2)) == ("corrente", 2)
    modo, dia_rel = resolver_modo("2026-07", date(2026, 8, 2))
    assert modo == "fechando" and dia_rel == 32          # 01/07 -> 02/08 = 32 dias
    assert resolver_modo("2026-05", date(2026, 8, 2))[0] == "fechado"
    assert resolver_modo("2026-07", date(2026, 9, 20))[0] == "fechado"  # dia_rel > 45


def _ctx_minimo():
    """Contexto sintetico: receita via driver, folha via nivel, combustivel via
    razao/completude. Numeros recomputaveis a mao."""
    meses6 = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    hist = {
        "RECEITA OPERACIONAL BRUTA AGREGADO": {m: 1000.0 for m in meses6},
        "CF - FOLHA MOT": {m: -100.0 for m in meses6},
        "CV - COMBUSTIVEL": {m: -300.0 for m in meses6},
        "IMPOSTOS FEDERAIS": {m: -80.0 for m in meses6},
    }
    return {
        "mes": "2026-08", "modo": "corrente", "dia_rel": 10,
        "hoje": "2026-08-10", "dias_meta_decorridos": 8,
        "razao_ag_mes": {"RECEITA OPERACIONAL BRUTA AGREGADO": 300.0,
                         "CF - FOLHA MOT": -5.0, "CV - COMBUSTIVEL": -100.0,
                         "IMPOSTOS FEDERAIS": -24.0},
        "hist_ag": hist, "meses_hist": meses6,
        "diario": {"real_acum": 310.0, "meta_acum": 320.0, "meta_mes": 1000.0},
        "ating_hist": 0.90,
        "curva": {"ag": {"CV - COMBUSTIVEL": {d: min(1.0, d / 30) for d in range(46)}},
                  "linha": {}, "global": {d: min(1.0, d / 30) for d in range(46)}},
        "vfc": {"frete_compra": 0.0, "receita_viagens": 0.0, "viagens": 0},
        "ctaplus": {"custo": 95.0, "abastecimentos": 10},
        "cap": {"valor": 500.0, "titulos": 3},
        "breakeven": None, "orcado_linha": {"RECEITA BRUTA": 1100.0},
        "meses_circulares": [], "calibracao": {}, "ajustes": {},
        "indices": ({}, []),  # (indices_por_linha, linhas_flat)
        "snapshots": [], "fontes": [],
    }


def test_montar_resposta_corrente():
    r = montar_resposta(_ctx_minimo())
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    # receita: 310 + (1000-320) * ritmo; ritmo = 310/320 (>=3 dias uteis)
    ritmo = 310.0 / 320.0
    assert abs(linhas["RECEITA BRUTA"]["previsto"] - (310.0 + 680.0 * ritmo)) < 1e-6
    assert linhas["RECEITA BRUTA"]["estrategia"] == "driver_fiscal"
    # folha (nivel): mediana 3m = -100
    assert abs(linhas["CUSTO FIXO"]["previsto"] - (-100.0)) < 1e-6
    # combustivel: -100 / (10/30) = -300
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"] - (-300.0)) < 1e-6
    # impostos: pct 6m = -80/1000 = -8% da receita prevista
    rec_prev = linhas["RECEITA BRUTA"]["previsto"]
    assert abs(linhas["IMPOSTOS FEDERAIS"]["previsto"] - (rec_prev * -0.08)) < 1e-6
    # cascata fecha: RESULTADO = soma das partes
    assert abs(r["kpis"]["resultado_previsto"]
               - linhas["RESULTADO DO EXERCICIO"]["previsto"]) < 1e-9
    # realizado contabil exposto por linha
    assert abs(linhas["RECEITA BRUTA"]["realizado"] - 300.0) < 1e-9


def test_ajuste_manual_aplicado_e_marcado():
    ctx = _ctx_minimo()
    ctx["ajustes"] = {"CUSTO FIXO": {"tipo": "delta", "valor": -120.0,
                                     "motivo": "rescisao", "autor": "c",
                                     "criado_em": "2026-08-01"}}
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    assert abs(linhas["CUSTO FIXO"]["previsto"] - (-220.0)) < 1e-6
    assert linhas["CUSTO FIXO"]["ajuste"]["motivo"] == "rescisao"


def test_aviso_divergencia_combustivel():
    ctx = _ctx_minimo()
    ctx["ctaplus"] = {"custo": 200.0, "abastecimentos": 10}  # razao MTD = -100
    r = montar_resposta(ctx)
    assert any("combust" in a.lower() for a in r["avisos"])


def test_modo_fechando_consolida_e_estima():
    ctx = _ctx_minimo()
    ctx.update({"mes": "2026-07", "modo": "fechando", "dia_rel": 32,
                "diario": None,
                "razao_ag_mes": {"RECEITA OPERACIONAL BRUTA AGREGADO": 1000.0,
                                 "CV - COMBUSTIVEL": -290.0,
                                 "CF - FOLHA MOT": -10.0}})
    # curva: combustivel ja ~100% em d32; folha 10% em d32 (abaixo do piso)
    ctx["curva"] = {"ag": {"CV - COMBUSTIVEL": {d: 1.0 for d in range(46)},
                           "CF - FOLHA MOT": {d: 0.10 for d in range(46)}},
                    "linha": {}, "global": {d: 1.0 for d in range(46)}}
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"] - (-290.0)) < 1e-6   # consolidado
    assert abs(linhas["CUSTO FIXO"]["previsto"] - (-100.0)) < 1e-6       # fallback nivel
    assert 0.0 < r["kpis"]["consolidacao_pct"] <= 1.0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/previsao/test_servico.py -q`
Expected: FAIL

- [ ] **Step 3: Implementar `api/previsao/servico.py`**

```python
# api/previsao/servico.py
"""Orquestração da previsão de fechamento.

I/O aqui; cálculo no motor (puro). Fetch em grupos paralelos com conexão
própria (padrão get_visao_geral — o túnel tem RTT alto). montar_resposta é
pura e recebe o contexto pronto: é ela que o backtest reexecuta "as-of".
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from api import db
from api.orcamento import armazenamento as orc_arm
from api.orcamento import rollup
from api.orcamento.derivacao import indices_sazonais
from api.orcamento.servico import meses_circulares
from api.orcamento.sql import AGRUP_CONTA_SQL
from api.previsao import armazenamento as arm
from api.previsao import motor
from api.previsao.completude import completude_em, montar_curva
from api.previsao.sql import (ATING_HIST_SQL, CAP_MES_SQL, COMPLETUDE_SQL,
                              CTAPLUS_MTD_SQL, VFC_MTD_SQL, meses_fechados_prev)
from api.queries import (BREAKEVEN_SQL, DRE_AG_SQL, DRE_AJUSTADAS_SQL,
                         DRE_MODELO, VG_DIARIO_SQL, _comp_bounds,
                         _ponto_equilibrio, ler_ajustes)

log = logging.getLogger("cortex.previsao")
ROOT = Path(__file__).resolve().parent.parent.parent
CALIB_PATH = ROOT / "data" / "previsao_calibracao.json"

# linhas cujo previsto NAO vem do loop de agrupadores (tratadas no nivel da linha)
_LINHAS_NIVEL_LINHA = {"RECEITA BRUTA", "IMPOSTOS FEDERAIS", "IMPOSTOS ESTADUAIS",
                       "IMPOSTOS MUNICIPAIS", "CONTRIBUICAO PREVIDENCIARIA",
                       "ANULACOES", "DESCONTOS"}
_LINHAS_PCT = ("IMPOSTOS FEDERAIS", "IMPOSTOS ESTADUAIS", "IMPOSTOS MUNICIPAIS",
               "CONTRIBUICAO PREVIDENCIARIA")
DIVERGENCIA_COMB = 0.10


def resolver_modo(mes: str, hoje: date) -> tuple[str, int]:
    corrente = f"{hoje.year}-{hoje.month:02d}"
    if mes == corrente:
        return "corrente", (hoje - hoje.replace(day=1)).days
    prim_corrente = hoje.replace(day=1)
    m1 = (prim_corrente - timedelta(days=1)).replace(day=1)
    if mes == f"{m1.year}-{m1.month:02d}":
        dia_rel = (hoje - m1).days
        if dia_rel <= 45:
            return "fechando", dia_rel
    return "fechado", 0


def _hist_linha(hist_ag: dict, meses: list[str]) -> dict[str, dict[str, float]]:
    por: dict[str, dict[str, float]] = {}
    for ag, serie in hist_ag.items():
        rot = motor.linha_do_agrupador(ag)
        if not rot:
            continue
        alvo = por.setdefault(rot, {})
        for m, v in serie.items():
            alvo[m] = alvo.get(m, 0.0) + v
    return por


def _ultimos(serie: dict[str, float], meses: list[str], n: int) -> list[float]:
    return [serie.get(m, 0.0) for m in meses[-n:]]


def montar_resposta(ctx: dict) -> dict:
    """ctx (tudo plain data — ver get_previsao para o preenchimento):
    mes, modo ('corrente'|'fechando'|'fechado'), dia_rel, hoje (iso),
    dias_meta_decorridos, razao_ag_mes {ag: valor}, hist_ag {ag: {mes: valor}}
    (meses FECHADOS, ajustes contábeis já migrados), meses_hist [YYYY-MM asc],
    diario {real_acum, meta_acum, meta_mes} | None, ating_hist float|None,
    curva (montar_curva), vfc {frete_compra, receita_viagens, viagens},
    ctaplus {custo, abastecimentos}, cap {valor, titulos}, breakeven dict|None,
    orcado_linha {rotulo: valor}, meses_circulares [int], calibracao {linha:
    {dia: {p20,p80}}}, ajustes (armazenamento.ler_ajustes_prev), indices =
    (indices_por_linha, linhas_flat), snapshots [], fontes []."""
    modo = ctx["modo"]
    meses = ctx["meses_hist"]
    hist_ag = ctx["hist_ag"]
    hist_linha = _hist_linha(hist_ag, meses)
    razao_ag = ctx["razao_ag_mes"]
    indices_por_linha, linhas_flat = ctx.get("indices") or ({}, [])
    avisos: list[str] = list(ctx.get("avisos_previos") or [])

    # realizado contábil por linha direta (sempre exposto)
    realizado_direta: dict[str, float] = {}
    nao_alocado_real = 0.0
    for ag, v in razao_ag.items():
        rot = motor.linha_do_agrupador(ag)
        if rot:
            realizado_direta[rot] = realizado_direta.get(rot, 0.0) + v
        else:
            nao_alocado_real += v

    previsto_direta: dict[str, dict] = {}

    def _fallback_nivel(ag: str) -> dict:
        return motor.prever_nivel(_ultimos(hist_ag.get(ag, {}), meses, 3), f"{ag} 3m")

    if modo == "fechado":
        for rot, v in realizado_direta.items():
            previsto_direta[rot] = {"previsto": v, "estrategia": "fechado",
                                    "premissas": ["mes fechado - razao"]}
        avisos.append("Mes fechado: previsto = razao. Consulte a DRE Gerencial.")
    elif modo == "fechando":
        est = motor.estimar_m1(razao_ag, ctx["curva"], ctx["dia_rel"],
                               {ag: _fallback_nivel(ag) for ag in razao_ag})
        for ag, r in est.items():
            rot = motor.linha_do_agrupador(ag)
            if not rot:
                continue
            atual = previsto_direta.setdefault(
                rot, {"previsto": 0.0, "estrategia": r["estrategia"], "premissas": []})
            atual["previsto"] += r["previsto"]
            atual["premissas"] = (atual["premissas"] + r["premissas"])[:6]
            if r["estrategia"] != "consolidado":
                atual["estrategia"] = r["estrategia"]
    else:  # corrente
        d = ctx["diario"] or {"real_acum": 0.0, "meta_acum": 0.0, "meta_mes": 0.0}
        rec = motor.prever_receita(d["real_acum"], d["meta_acum"], d["meta_mes"],
                                   ctx.get("ating_hist"), ctx["dias_meta_decorridos"])
        previsto_direta["RECEITA BRUTA"] = rec
        rb_hist = hist_linha.get("RECEITA BRUTA", {})
        rb6 = _ultimos(rb_hist, meses, 6)
        media_rb6 = (sum(rb6) / len(rb6)) if rb6 else 0.0
        for rot in _LINHAS_PCT:
            serie6 = _ultimos(hist_linha.get(rot, {}), meses, 6)
            pct = (sum(serie6) / len(serie6)) / media_rb6 if media_rb6 else 0.0
            previsto_direta[rot] = motor.prever_pct_receita(
                rec["previsto"], pct, f"media 6m ({rot.lower()})")
        for rot in ("ANULACOES", "DESCONTOS"):
            idx = indices_por_linha.get(rot) or {m: 1.0 for m in range(1, 13)}
            vals6 = _ultimos(hist_linha.get(rot, {}), meses, 6)
            i6 = [idx[int(m[5:7])] for m in meses[-6:]]
            previsto_direta[rot] = motor.prever_sazonal(
                vals6, i6, idx[int(ctx["mes"][5:7])])

        # frete de compra: agregados + terceiros JUNTOS (proxy sem join de
        # veiculo), depois split pela participacao historica das duas linhas
        ags_frete = [ag for ag in set(razao_ag) | set(hist_ag)
                     if motor.estrategia_do_agrupador(ag) == "frete_compra"]
        if ags_frete:
            razao_mtd_frete = sum(razao_ag.get(ag, 0.0) for ag in ags_frete)
            hist_frete6 = sum(sum(_ultimos(hist_ag.get(ag, {}), meses, 6))
                              for ag in ags_frete)
            razao_cr = (hist_frete6 / sum(rb6)) if sum(rb6) else 0.0
            comb = motor.prever_frete_compra(
                razao_mtd_frete, ctx["vfc"]["frete_compra"], rec["previsto"],
                d["real_acum"], razao_cr)
            total_h = {ag: abs(sum(_ultimos(hist_ag.get(ag, {}), meses, 6)))
                       for ag in ags_frete}
            soma_h = sum(total_h.values()) or 1.0
            for ag in ags_frete:
                parte = comb["previsto"] * (total_h[ag] / soma_h)
                rot = motor.linha_do_agrupador(ag) or "CUSTO VARIAVEL"
                atual = previsto_direta.setdefault(
                    rot, {"previsto": 0.0, "estrategia": "frete_compra",
                          "premissas": comb["premissas"]})
                atual["previsto"] += parte

```

Continuação do mesmo bloco `corrente` (demais agrupadores — o código segue dentro do `else:` acima):

```python
        for ag in sorted(set(razao_ag) | set(hist_ag)):
            estrat = motor.estrategia_do_agrupador(ag)
            rot = motor.linha_do_agrupador(ag)
            if estrat == "frete_compra" or (rot in _LINHAS_NIVEL_LINHA):
                continue  # ja tratados no nivel da linha / bloco do frete
            v_mtd = razao_ag.get(ag, 0.0)
            if estrat == "nivel" or estrat == "runrate":
                r = _fallback_nivel(ag)
            elif estrat == "sazonal":
                idx = (indices_por_linha.get(rot) if rot else None) \
                    or {m: 1.0 for m in range(1, 13)}
                vals6 = _ultimos(hist_ag.get(ag, {}), meses, 6)
                i6 = [idx[int(m[5:7])] for m in meses[-6:]]
                r = motor.prever_sazonal(vals6, i6, idx[int(ctx["mes"][5:7])])
            else:  # razao_completude
                frac = completude_em(ctx["curva"], ag, rot, ctx["dia_rel"])
                r = motor.prever_razao_completude(v_mtd, frac, _fallback_nivel(ag))
            alvo = rot or "NAO ALOCADO / CLASSIFICAR"
            atual = previsto_direta.setdefault(
                alvo, {"previsto": 0.0, "estrategia": r["estrategia"],
                       "premissas": []})
            atual["previsto"] += r["previsto"]
            atual["premissas"] = (atual["premissas"] + r["premissas"])[:6]

    # ---- ajustes manuais + cascata + bandas + comparaveis (todos os modos)
    nao_alocado = previsto_direta.pop("NAO ALOCADO / CLASSIFICAR",
                                      {"previsto": nao_alocado_real,
                                       "estrategia": "runrate", "premissas": []})
    ajustes = ctx.get("ajustes") or {}
    base_direta: dict[str, float] = {}
    shift_direta: dict[str, float] = {}
    for rotulo, _n, tipo, _s in DRE_MODELO:
        if tipo == "formula":
            continue
        calc = previsto_direta.get(rotulo, {"previsto": 0.0})["previsto"]
        efetivo, shift = motor.aplicar_ajuste(calc, ajustes.get(rotulo))
        base_direta[rotulo] = efetivo
        shift_direta[rotulo] = shift

    frac_rest = 0.0
    if modo == "corrente" and ctx.get("diario"):
        mm = ctx["diario"]["meta_mes"]
        frac_rest = max(0.0, 1.0 - (ctx["diario"]["meta_acum"] / mm)) if mm else 0.5
    elif modo == "fechando":
        frac_rest = 0.3

    pess_direta, otim_direta = {}, {}
    calib = ctx.get("calibracao") or {}
    dia_util = ctx.get("dias_meta_decorridos", ctx.get("dia_rel", 0))
    for rotulo, base in base_direta.items():
        b = motor.banda_calibrada(base - shift_direta[rotulo],
                                  calib.get(rotulo), dia_util)
        if b is None:
            hist6 = _ultimos(hist_linha.get(rotulo, {}), meses, 6)
            b = motor.banda_fallback(base - shift_direta[rotulo], hist6, frac_rest)
        pess_direta[rotulo] = b[0] + shift_direta[rotulo]
        otim_direta[rotulo] = b[1] + shift_direta[rotulo]

    casc_base = motor.montar_cascata(base_direta)
    casc_pess = motor.montar_cascata(pess_direta)
    casc_otim = motor.montar_cascata(otim_direta)
    casc_real = motor.montar_cascata(realizado_direta)
    orcado = ctx.get("orcado_linha") or {}
    casc_orc = motor.montar_cascata({r: orcado.get(r, 0.0) for r in orcado}) \
        if orcado else {}

    linhas = []
    for rotulo, nivel, tipo, _s in DRE_MODELO:
        prev = casc_base.get(rotulo, 0.0)
        item = {
            "linha": rotulo, "nivel": nivel, "formula": tipo == "formula",
            "realizado": casc_real.get(rotulo, 0.0),
            "previsto": prev,
            "projetado": prev - casc_real.get(rotulo, 0.0),
            "previsto_pess": min(casc_pess.get(rotulo, prev), casc_otim.get(rotulo, prev)),
            "previsto_otim": max(casc_pess.get(rotulo, prev), casc_otim.get(rotulo, prev)),
            "orcado": casc_orc.get(rotulo) if casc_orc else None,
            "estrategia": ("formula" if tipo == "formula" else
                           previsto_direta.get(rotulo, {}).get("estrategia", "runrate")),
            "premissas": previsto_direta.get(rotulo, {}).get("premissas", []),
            "ajuste": ajustes.get(rotulo),
        }
        if item["orcado"] is not None:
            item["desvio"] = item["previsto"] - item["orcado"]
        linhas.append(item)
    linhas.append({
        "linha": "NAO ALOCADO / CLASSIFICAR", "nivel": 0, "formula": False,
        "realizado": nao_alocado_real, "previsto": nao_alocado["previsto"],
        "projetado": nao_alocado["previsto"] - nao_alocado_real,
        "previsto_pess": nao_alocado["previsto"], "previsto_otim": nao_alocado["previsto"],
        "orcado": None, "estrategia": nao_alocado["estrategia"],
        "premissas": nao_alocado["premissas"], "ajuste": None,
    })

    # avisos
    if modo == "corrente" and ctx.get("ctaplus"):
        comb_prev = None
        for ag in razao_ag:
            if motor.norm(ag).startswith("CV - COMBUSTIVEL"):
                frac = completude_em(ctx["curva"], ag, "CUSTO VARIAVEL", ctx["dia_rel"])
                comb_prev = motor.prever_razao_completude(
                    razao_ag[ag], frac, _fallback_nivel(ag))["previsto"]
        custo_ctaplus = -abs(ctx["ctaplus"].get("custo") or 0.0)
        if comb_prev and custo_ctaplus and razao_ag:
            razao_comb_mtd = sum(v for a, v in razao_ag.items()
                                 if motor.norm(a).startswith("CV - COMBUSTIVEL"))
            if razao_comb_mtd and abs(custo_ctaplus - razao_comb_mtd) \
                    > DIVERGENCIA_COMB * abs(razao_comb_mtd):
                avisos.append(
                    f"Combustivel diverge: razao MTD R$ {abs(razao_comb_mtd):,.0f} x "
                    f"abastecimentos R$ {abs(custo_ctaplus):,.0f} (>10%). Conferir fontes.")
    if ctx.get("meses_circulares") and int(ctx["mes"][5:7]) in ctx["meses_circulares"]:
        avisos.append("Mes dentro da base de derivacao do orcamento vigente - "
                      "o desvio contra o orcado mede so o fator (comparacao circular).")
    for rot, aj in ajustes.items():
        if modo == "fechado":
            avisos.append(f"Ajuste manual vencido em {rot} (mes ja fechado).")

    consolidacao = None
    if modo == "fechando":
        visto = sum(abs(v) for v in razao_ag.values())
        estimado_total = sum(abs(ln["previsto"]) for ln in linhas
                             if not ln["formula"])
        consolidacao = min(1.0, visto / estimado_total) if estimado_total else None

    kpis = {
        "resultado_previsto": casc_base.get("RESULTADO DO EXERCICIO", 0.0),
        "resultado_pess": min(casc_pess.get("RESULTADO DO EXERCICIO", 0.0),
                              casc_otim.get("RESULTADO DO EXERCICIO", 0.0)),
        "resultado_otim": max(casc_pess.get("RESULTADO DO EXERCICIO", 0.0),
                              casc_otim.get("RESULTADO DO EXERCICIO", 0.0)),
        "resultado_orcado": casc_orc.get("RESULTADO DO EXERCICIO") if casc_orc else None,
        "receita_prevista": casc_base.get("RECEITA BRUTA", 0.0),
        "atingimento_mtd": ((ctx["diario"]["real_acum"] / ctx["diario"]["meta_acum"])
                            if ctx.get("diario") and ctx["diario"]["meta_acum"] else None),
        "meta_mes": ctx["diario"]["meta_mes"] if ctx.get("diario") else None,
        "breakeven": ctx.get("breakeven"),
        "cap_mes": ctx.get("cap"),
        "consolidacao_pct": consolidacao,
        "dados_ate": ctx["hoje"],
    }
    return {"mes": ctx["mes"], "modo": modo, "kpis": kpis, "linhas": linhas,
            "avisos": avisos, "linhas_flat": (ctx.get("indices") or ({}, []))[1],
            "serie_snapshots": ctx.get("snapshots") or [],
            "fontes": ctx.get("fontes") or [],
            "fonte": ("ERP AVA (razao + documentos fiscais + viagens + ctaplus) "
                      "+ orcamento local · previsao, nao numero fechado")}
```

E o I/O (`get_previsao`), no mesmo arquivo — grupos paralelos, cada um com conexão própria:

```python
def _fetch_grupo(sqls: list[tuple[str, dict | None]]) -> list[list[dict]]:
    out = []
    with db.get_conn() as conn, conn.cursor() as cur:
        for sql, params in sqls:
            cur.execute(sql, params)
            out.append(cur.fetchall())
    return out


def _curva_do_banco(hoje: date, mapa_ag_linha_fn) -> dict:
    meses6 = meses_fechados_prev(hoje, 6)
    de = f"{meses6[0]}-01"
    _, ate = _comp_bounds(meses6[-1], meses6[-1])
    rows = db.query(COMPLETUDE_SQL, {"de": de, "ate": ate})
    ags = {r["agrupador"] for r in rows}
    return montar_curva([dict(r) for r in rows],
                        {ag: mapa_ag_linha_fn(ag) for ag in ags})


def get_previsao(mes: str | None = None, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    mes = mes or f"{hoje.year}-{hoje.month:02d}"
    modo, dia_rel = resolver_modo(mes, hoje)
    de_mes, ate_mes = _comp_bounds(mes, mes)
    meses24 = meses_fechados_prev(hoje, 24)
    de24 = f"{meses24[0]}-01"
    _, ate24 = _comp_bounds(meses24[-1], meses24[-1])
    ajustes_ctb = ler_ajustes()
    fontes = []

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_razao = ex.submit(_fetch_grupo, [
            (DRE_AG_SQL, {"de": de24, "ate": ate24}),
            (DRE_AG_SQL, {"de": de_mes, "ate": ate_mes}),
        ] + ([(DRE_AJUSTADAS_SQL, {"de": de24, "ate": ate24,
                                   "chaves": list(ajustes_ctb.keys())}),
              (DRE_AJUSTADAS_SQL, {"de": de_mes, "ate": ate_mes,
                                   "chaves": list(ajustes_ctb.keys())})]
             if ajustes_ctb else []))
        f_curva = ex.submit(_curva_do_banco, hoje, motor.linha_do_agrupador)
        f_diario = ex.submit(_fetch_grupo, [
            (VG_DIARIO_SQL, None),
            (ATING_HIST_SQL, {"de": f"{meses_fechados_prev(hoje, 3)[0]}-01",
                              "ate": f"{hoje.year}-{hoje.month:02d}-01"}),
            (BREAKEVEN_SQL, {"de_be": f"{meses_fechados_prev(hoje, 12)[0]}-01",
                             "ate_be": f"{hoje.year}-{hoje.month:02d}-01"}),
        ])
        f_ops = ex.submit(_fetch_grupo, [
            (VFC_MTD_SQL, {"de": de_mes, "ate": ate_mes}),
            (CTAPLUS_MTD_SQL, {"de": de_mes, "ate": ate_mes}),
            (CAP_MES_SQL, {"de": de_mes, "ate": ate_mes}),
        ])
        razao_out = f_razao.result()
        curva = f_curva.result()
        diario_out = f_diario.result()
        ops_out = f_ops.result()
```

**ATENÇÃO:** confirmar os placeholders reais de `BREAKEVEN_SQL` em `api/queries.py:1714-1720` (o `get_visao_geral` o executa com `de_be`/`ate_be` calculados em `queries.py:1891-1892` — copiar exatamente os nomes de params de lá; se a query for f-string sem params, executá-la igual ao `get_visao_geral` faz).

```python
    # razão 24m + mês alvo, com migração dos ajustes contábeis (mesma lógica
    # de get_dre: subtrai do agrupador original, soma no novo)
    def _aplica_mudancas(val: dict, mudancas: list[dict]) -> None:
        for m in mudancas:
            novo = ajustes_ctb[m["chave"]]["agrupador"]
            if novo == m["agrupador_orig"]:
                continue
            k_orig = (m["mes"], m["agrupador_orig"])
            val[k_orig] = val.get(k_orig, 0.0) - m["valor"]
            val[(m["mes"], novo)] = val.get((m["mes"], novo), 0.0) + m["valor"]

    val24: dict = {}
    for r in razao_out[0]:
        val24[(r["mes"], r["agrupador"])] = \
            val24.get((r["mes"], r["agrupador"]), 0.0) + r["valor"]
    val_mes: dict = {}
    for r in razao_out[1]:
        val_mes[(r["mes"], r["agrupador"])] = \
            val_mes.get((r["mes"], r["agrupador"]), 0.0) + r["valor"]
    if ajustes_ctb and len(razao_out) >= 4:
        _aplica_mudancas(val24, razao_out[2])
        _aplica_mudancas(val_mes, razao_out[3])

    hist_ag: dict[str, dict[str, float]] = {}
    for (m, ag), v in val24.items():
        if m in meses24:
            hist_ag.setdefault(ag, {})[m] = v
    razao_ag_mes = {ag: v for (m, ag), v in val_mes.items() if m == mes}

    # diario do mes corrente (VG_DIARIO_SQL e fixo no mes corrente do banco)
    diario = None
    dias_meta_decorridos = 0
    if modo == "corrente":
        rows_d = diario_out[0]
        meta_mes = sum(r["meta"] for r in rows_d)
        meta_acum = sum(r["meta"] for r in rows_d if r["dia"] <= hoje.day)
        real_acum = sum(r["realizado"] for r in rows_d)
        dias_meta_decorridos = sum(1 for r in rows_d
                                   if r["meta"] and r["dia"] <= hoje.day)
        diario = {"real_acum": real_acum, "meta_acum": meta_acum,
                  "meta_mes": meta_mes}
    ath = [r for r in diario_out[1] if r["meta"]]
    ating_hist = (sum(r["realizado"] / r["meta"] for r in ath) / len(ath)) \
        if ath else None
    breakeven = None
    try:
        breakeven = _ponto_equilibrio(diario_out[2])
    except Exception:  # noqa: BLE001
        pass

    # indices sazonais por linha (24 meses) — reuso do orcamento
    serie_linha = _hist_linha(hist_ag, meses24)
    indices = indices_sazonais(serie_linha, meses24)

    # orcado do mes por linha (best-effort: nunca derruba a previsao)
    orcado_linha: dict[str, float] = {}
    circulares: list[int] = []
    try:
        orc_arm.init_db(orc_arm.DB_PATH)
        vig = orc_arm.versao_vigente(orc_arm.DB_PATH, ano=int(mes[:4]))
        if vig:
            agrup_rows = db.query(AGRUP_CONTA_SQL)
            agrup_por_conta = {r["conta"]: r["agrupador"] for r in agrup_rows}
            mapa = rollup.mapa_conta_linha(agrup_por_conta, ajustes_ctb)
            mnum = int(mes[5:7])
            for ln in orc_arm.ler_linhas(orc_arm.DB_PATH, vig["id"]):
                if ln["mes"] != mnum:
                    continue
                rot = mapa.get(ln["conta"])
                if rot:
                    orcado_linha[rot] = orcado_linha.get(rot, 0.0) + ln["valor_efetivo"]
            circulares = meses_circulares(int(mes[:4]),
                                          json.loads(vig.get("meses_base") or "[]"))
            fontes.append({"nome": f"orcamento: {vig['rotulo']}", "ok": True})
        else:
            fontes.append({"nome": "orcamento (sem versao do ano)", "ok": False})
    except Exception as exc:  # noqa: BLE001
        log.warning("previsao: orcado indisponivel: %s", exc)
        fontes.append({"nome": "orcamento", "ok": False})

    calib = {}
    try:
        calib = json.loads(CALIB_PATH.read_text())
    except Exception:  # noqa: BLE001
        pass

    arm.init_db(arm.DB_PATH)
    ctx = {"mes": mes, "modo": modo, "dia_rel": dia_rel, "hoje": hoje.isoformat(),
           "dias_meta_decorridos": dias_meta_decorridos,
           "razao_ag_mes": razao_ag_mes, "hist_ag": hist_ag, "meses_hist": meses24,
           "diario": diario, "ating_hist": ating_hist, "curva": curva,
           "vfc": dict(ops_out[0][0]) if ops_out[0] else {"frete_compra": 0.0,
                                                          "receita_viagens": 0.0,
                                                          "viagens": 0},
           "ctaplus": dict(ops_out[1][0]) if ops_out[1] else None,
           "cap": dict(ops_out[2][0]) if ops_out[2] else None,
           "breakeven": breakeven, "orcado_linha": orcado_linha,
           "meses_circulares": circulares, "calibracao": calib,
           "ajustes": arm.ler_ajustes_prev(arm.DB_PATH, mes),
           "indices": indices,
           "snapshots": arm.ler_snapshots(arm.DB_PATH, mes), "fontes": fontes}
    resp = montar_resposta(ctx)
    try:  # snapshot diario best-effort (idempotente por dia)
        arm.gravar_snapshot(arm.DB_PATH, hoje.isoformat(), mes, [
            {"linha": ln["linha"], "previsto_base": ln["previsto"],
             "previsto_otim": ln["previsto_otim"], "previsto_pess": ln["previsto_pess"],
             "realizado_contabil": ln["realizado"], "estrategia": ln["estrategia"]}
            for ln in resp["linhas"]])
    except Exception as exc:  # noqa: BLE001
        log.warning("previsao: snapshot falhou: %s", exc)
    return resp
```

E a fachada em `api/previsao/__init__.py`:

```python
"""Previsão de fechamento do mês — fachada pública."""
from api.queries import cached
from api.previsao.servico import get_previsao as _get_previsao

get_previsao_fechamento = cached(ttl=300)(_get_previsao)
```

- [ ] **Step 4: Rodar os testes puros e ver passar**

Run: `uv run pytest tests/previsao/ -q`
Expected: todos passed

- [ ] **Step 5: Smoke com banco real (túnel de pé)**

```bash
uv run python -c "
from api.previsao import get_previsao_fechamento
r = get_previsao_fechamento()
print(r['mes'], r['modo'], round(r['kpis']['resultado_previsto']))
print([a for a in r['avisos']])
r7 = get_previsao_fechamento('2026-07')
print(r7['modo'], r7['kpis']['consolidacao_pct'])
"
```
Expected: agosto `corrente` com resultado numérico plausível; julho `fechando` com consolidação 0,6–0,95. Comparar mentalmente com a DRE (jul deve estimar CV total na casa dos R$ 6-7 mi negativos, não R$ 3 mi).

- [ ] **Step 6: Commitar**

```bash
uv run python -c "from api import main"
git add api/previsao/ tests/previsao/test_servico.py
git commit -m "feat(previsao): orquestracao com fetch paralelo, comparaveis e snapshot diario"
```

---

### Task 7: Endpoints + RBAC (tela `fech`, seed v20)

**Files:**
- Modify: `api/main.py` (2 endpoints novos, logo após o bloco do orçamento ~linha 1242)
- Modify: `api/auth.py` (TELAS ~linha 62, ROTA_TELAS ~linha 102, `_PERFIS_MODELO` ~linha 201, seed v20 após o bloco v19 ~linha 441)
- Test: `tests/previsao/test_auth_fech.py`

**Interfaces:**
- Consumes: `api.previsao.get_previsao_fechamento`, `api.previsao.armazenamento`, `api.queries.DRE_MODELO` e `_RESP_CACHE`.
- Produces: `GET /api/controladoria/previsao?mes=YYYY-MM`; `POST /api/controladoria/previsao/ajuste` body `{mes, linha, tipo, valor, motivo}` (valor `null` remove); tela `fech` para perfis Controladoria e Diretoria.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/previsao/test_auth_fech.py
"""RBAC da tela fech: mapeamentos estaticos (sem banco)."""
from __future__ import annotations

from api import auth


def test_tela_registrada():
    assert auth.TELAS["fech"] == ("Fechamento do Mês", "Controladoria")


def test_rota_mapeada_para_a_tela():
    assert auth._telas_da_rota("/api/controladoria/previsao") == frozenset({"fech"})
    assert auth._telas_da_rota("/api/controladoria/previsao/ajuste") == frozenset({"fech"})
    # e o orcamento continua sendo do orcamento
    assert auth._telas_da_rota("/api/controladoria/orcamento") == frozenset({"orc"})


def test_perfis_modelo_incluem_fech():
    por_nome = {nome: telas for nome, _d, telas in auth._PERFIS_MODELO}
    assert "fech" in por_nome["Controladoria"]
    assert "fech" in por_nome["Diretoria"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/previsao/test_auth_fech.py -q`
Expected: FAIL (KeyError 'fech')

- [ ] **Step 3: Editar `api/auth.py`** (substituições literais; `uv run python -c "import ast; ast.parse(open('api/auth.py').read())"` antes de salvar em definitivo)

1. Em `TELAS`, logo após a linha `"orc":     ("Orçamento", "Controladoria"),` inserir:

```python
    "fech":    ("Fechamento do Mês", "Controladoria"),
```

2. Em `ROTA_TELAS`, imediatamente ANTES da linha `("/api/controladoria/orcamento",  frozenset({"orc"})),` inserir:

```python
    ("/api/controladoria/previsao",   frozenset({"fech"})),
```

3. Em `_PERFIS_MODELO`: na tupla `("Controladoria", ...)` trocar a lista para `["dre", "cont", "drecli", "qual", "orc", "extb", "fech"]`; na tupla `("Diretoria", ...)` acrescentar `"fech"` ao fim da lista.

4. Após o bloco `v19` em `_seed_perfis_modelo`, inserir:

```python
    # v20 (previsao de fechamento 2026-08-02): tela 'fech' aos perfis
    # Controladoria e Diretoria. Mesmo caso da v19/'extb': a tela nasceu depois
    # que os perfis ja existiam nas bases em uso.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v20'").fetchone():
        for nome_perfil in ("Controladoria", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=?", (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                          (row["id"], "fech"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v20', '1')")
```

- [ ] **Step 4: Endpoints em `api/main.py`** (inserir após o último endpoint do orçamento; import lazy, padrão do repo)

```python
@app.get("/api/controladoria/previsao")
def previsao_fechamento(mes: str | None = None) -> JSONResponse:
    from api.previsao import get_previsao_fechamento
    if mes is not None and not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", mes):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Parâmetro mes inválido: use o formato AAAA-MM."})
    try:
        return JSONResponse(get_previsao_fechamento(mes))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("previsao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a previsão."})


@app.post("/api/controladoria/previsao/ajuste")
async def previsao_ajuste(req: Request) -> JSONResponse:
    from api.previsao import armazenamento as parm
    from api.queries import DRE_MODELO, _RESP_CACHE
    try:
        body = await req.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Corpo da requisição inválido: envie um objeto JSON."})
    mes = str(body.get("mes") or "")
    linha = str(body.get("linha") or "")
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", mes):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "mes deve ser AAAA-MM."})
    rotulos = {r for r, _n, t, _s in DRE_MODELO if t != "formula"}
    if linha not in rotulos:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "linha deve ser uma linha DIRETA do modelo da DRE."})
    valor = body.get("valor")
    quem = (req.state.sessao or {}).get("nome") or "sistema"
    try:
        parm.init_db(parm.DB_PATH)
        if valor is None:
            parm.remover_ajuste_prev(parm.DB_PATH, mes, linha)
        else:
            parm.salvar_ajuste_prev(parm.DB_PATH, mes, linha,
                                    str(body.get("tipo") or "delta"),
                                    float(valor), str(body.get("motivo") or ""), quem)
        _RESP_CACHE.clear()
        return JSONResponse({"ok": True})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("previsao_ajuste falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao salvar o ajuste."})
```

- [ ] **Step 5: Rodar testes + smoke de import**

```bash
uv run pytest tests/previsao/test_auth_fech.py tests/ -q
uv run python -c "from api import main"
```
Expected: suíte inteira verde (as migrações de auth têm testes próprios — se `tests/test_auth_migracao.py` fixar o N do seed, atualizá-lo para v20).

- [ ] **Step 6: Commitar**

```bash
git add api/main.py api/auth.py tests/previsao/test_auth_fech.py
git commit -m "feat(previsao): endpoints /api/controladoria/previsao + tela fech no RBAC (seed v20)"
```

---

### Task 8: Backtest e calibração (`scripts/backtest_previsao.py`) — GATE de aceite

**Files:**
- Create: `scripts/backtest_previsao.py`
- Modify: `api/previsao/sql.py` (acrescentar `DIARIO_ASOF_SQL`)
- Modify: `tests/previsao/test_sql.py` (guardas da SQL nova)
- Create (gerados na execução): `data/previsao_calibracao.json`, `docs/previsao-backtest.md`

**Interfaces:**
- Consumes: `RAZAO_ASOF_SQL`, `ATING_HIST_SQL`, `VFC_MTD_SQL` (com `dtsaida < asof` — aproximação declarada), `montar_resposta`, `montar_curva`, `meses_fechados_prev`.
- Produces: `data/previsao_calibracao.json` = `{rotulo: {"5": {"p20": float, "p80": float}, "10": ..., "15": ..., "20": ..., "25": ...}}` com erro RELATIVO `(previsto - final) / |final|`; relatório `docs/previsao-backtest.md`.

- [ ] **Step 1: Acrescentar `DIARIO_ASOF_SQL` a `api/previsao/sql.py`** (mês parametrizado, mesmos filtros fiscais; realizado por dia + meta por dia):

```python
# Faturamento fiscal diario x meta de UM mes qualquer (para o backtest as-of;
# o VG_DIARIO_SQL de queries.py e fixo no mes corrente).
DIARIO_ASOF_SQL = """
SELECT dia, sum(realizado)::float8 AS realizado, sum(meta)::float8 AS meta FROM (
  SELECT extract(day from dtemissao)::int AS dia,
         coalesce(valortotalprestacao,0) AS realizado, 0::numeric AS meta
  FROM conhecimento
  WHERE dtemissao >= %(de)s::date AND dtemissao < %(ate)s::date
    AND grupo = 1 AND empresa = 1 AND unidade = 1 AND numero < 1000000
    AND dtcancelamento IS NULL AND situacaocte = 3 AND tipo IN (1,4)
  UNION ALL
  SELECT extract(day from dtemissao)::int, coalesce(valortotalbruto,0), 0
  FROM notafiscalservico
  WHERE dtemissao >= %(de)s::date AND dtemissao < %(ate)s::date
    AND grupo = 1 AND empresa = 1 AND numero < 1000000
    AND dtcancelamento IS NULL
    AND (emissaoeletronica = 2 OR (emissaoeletronica = 1 AND situacaonfse = 3))
  UNION ALL
  SELECT extract(day from dt)::int, 0, coalesce(valor,0)
  FROM sulista.metafaturamento_agrupamentoclientedia
  WHERE dt >= %(de)s::date AND dt < %(ate)s::date AND tipo = 1
) t GROUP BY 1 ORDER BY 1
"""
```

Acrescentar em `tests/previsao/test_sql.py`: `DIARIO_ASOF_SQL` na tupla `TODAS` e um assert `"situacaocte = 3" in DIARIO_ASOF_SQL`.

- [ ] **Step 2: Escrever o script**

```python
# scripts/backtest_previsao.py
"""Backtest da previsão de fechamento — roda o motor "as-of" datas passadas.

lancamento.dtinc reconstrói o razão como era visível em cada data; o driver
fiscal usa dtemissao (data do documento) e a meta é estática — as-of exato.
Aproximação declarada: viagens as-of por dtsaida (a data de INCLUSÃO da
programação não é filtrável aqui).

Uso: uv run python scripts/backtest_previsao.py [--meses 6] [--dias 5,10,15,20,25]
Gera: data/previsao_calibracao.json + docs/previsao-backtest.md
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from api import db
from api.orcamento.derivacao import indices_sazonais
from api.previsao.completude import montar_curva
from api.previsao.motor import linha_do_agrupador
from api.previsao.servico import _hist_linha, montar_resposta
from api.previsao.sql import (COMPLETUDE_SQL, DIARIO_ASOF_SQL, RAZAO_ASOF_SQL,
                              VFC_MTD_SQL, meses_fechados_prev)
from api.queries import DRE_MODELO, _comp_bounds

ROOT = Path(__file__).resolve().parent.parent


def _percentil(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _razao_asof(de: str, ate: str, asof: str) -> dict[str, dict[str, float]]:
    rows = db.query(RAZAO_ASOF_SQL, {"de": de, "ate": ate, "asof": asof})
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        out.setdefault(r["agrupador"], {})[r["mes"]] = \
            out.get(r["agrupador"], {}).get(r["mes"], 0.0) + r["valor"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meses", type=int, default=6)
    ap.add_argument("--dias", default="5,10,15,20,25")
    args = ap.parse_args()
    dias = [int(d) for d in args.dias.split(",")]
    hoje = date.today()
    alvos = meses_fechados_prev(hoje, args.meses)

    erros: dict[str, dict[int, list[float]]] = {}
    relatorio = ["# Backtest da previsão de fechamento", "",
                 f"Gerado em {hoje.isoformat()} · meses: {', '.join(alvos)}", ""]

    for mes in alvos:
        de_m, ate_m = _comp_bounds(mes, mes)
        prim = date(int(mes[:4]), int(mes[5:7]), 1)
        # "final" = razão com tudo que existe hoje
        final_ag = _razao_asof(de_m, ate_m, hoje.isoformat())
        final_linha: dict[str, float] = {}
        for ag, serie in final_ag.items():
            rot = linha_do_agrupador(ag)
            if rot:
                final_linha[rot] = final_linha.get(rot, 0.0) + serie.get(mes, 0.0)
        diario_rows = db.query(DIARIO_ASOF_SQL, {"de": de_m, "ate": ate_m})
        meta_mes = sum(r["meta"] for r in diario_rows)

        # historico/curva/indices SEM olhar o futuro: fechados ANTES do mes alvo
        hist_meses = meses_fechados_prev(prim, 24)
        de_h = f"{hist_meses[0]}-01"
        _, ate_h = _comp_bounds(hist_meses[-1], hist_meses[-1])
        hist_por_ag_full = _razao_asof(de_h, ate_h, hoje.isoformat())
        hist_ag = {ag: {m: v for m, v in serie.items() if m in hist_meses}
                   for ag, serie in hist_por_ag_full.items()}
        curva_meses = meses_fechados_prev(prim, 6)
        rows_c = db.query(COMPLETUDE_SQL, {"de": f"{curva_meses[0]}-01",
                                           "ate": de_m})
        ags = {r["agrupador"] for r in rows_c}
        curva = montar_curva([dict(r) for r in rows_c],
                             {a: linha_do_agrupador(a) for a in ags})
        indices = indices_sazonais(_hist_linha(hist_ag, hist_meses), hist_meses)
        ath_rows = db.query(DIARIO_ASOF_SQL,
                            {"de": f"{meses_fechados_prev(prim, 3)[0]}-01",
                             "ate": de_m})
        # atingimento medio 3m: agregado unico (meta e realizado somados)
        soma_meta = sum(r["meta"] for r in ath_rows)
        ating_hist = (sum(r["realizado"] for r in ath_rows) / soma_meta) \
            if soma_meta else None

        for dia in dias:
            asof = prim + timedelta(days=dia - 1)
            razao_asof = _razao_asof(de_m, ate_m, asof.isoformat())
            razao_ag_mes = {ag: serie.get(mes, 0.0)
                            for ag, serie in razao_asof.items()}
            real_acum = sum(r["realizado"] for r in diario_rows if r["dia"] <= dia)
            meta_acum = sum(r["meta"] for r in diario_rows if r["dia"] <= dia)
            dias_meta = sum(1 for r in diario_rows if r["meta"] and r["dia"] <= dia)
            vfc = db.query(VFC_MTD_SQL, {"de": de_m, "ate": asof.isoformat()})
            ctx = {"mes": mes, "modo": "corrente", "dia_rel": dia,
                   "hoje": asof.isoformat(), "dias_meta_decorridos": dias_meta,
                   "razao_ag_mes": razao_ag_mes, "hist_ag": hist_ag,
                   "meses_hist": hist_meses,
                   "diario": {"real_acum": real_acum, "meta_acum": meta_acum,
                              "meta_mes": meta_mes},
                   "ating_hist": ating_hist, "curva": curva,
                   "vfc": dict(vfc[0]) if vfc else {"frete_compra": 0.0,
                                                    "receita_viagens": 0.0,
                                                    "viagens": 0},
                   "ctaplus": None, "cap": None, "breakeven": None,
                   "orcado_linha": {}, "meses_circulares": [], "calibracao": {},
                   "ajustes": {}, "indices": indices, "snapshots": [],
                   "fontes": []}
            resp = montar_resposta(ctx)
            for ln in resp["linhas"]:
                rot = ln["linha"]
                final = final_linha.get(rot)
                if rot == "NAO ALOCADO / CLASSIFICAR" or ln["formula"] or not final:
                    continue
                err = (ln["previsto"] - final) / abs(final)
                erros.setdefault(rot, {}).setdefault(dia, []).append(err)

    calib = {rot: {str(d): {"p20": round(_percentil(v, 0.20), 4),
                            "p80": round(_percentil(v, 0.80), 4)}
                   for d, v in por_dia.items()}
             for rot, por_dia in erros.items()}
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "previsao_calibracao.json").write_text(
        json.dumps(calib, indent=1, ensure_ascii=True))

    relatorio.append("| Linha | " + " | ".join(f"D{d} p20..p80" for d in dias) + " |")
    relatorio.append("|---|" + "---|" * len(dias))
    for rot, _n, tipo, _s in DRE_MODELO:
        if tipo == "formula" or rot not in calib:
            continue
        cel = [f"{calib[rot].get(str(d), {}).get('p20', 0):+.1%} .. "
               f"{calib[rot].get(str(d), {}).get('p80', 0):+.1%}" for d in dias]
        relatorio.append(f"| {rot} | " + " | ".join(cel) + " |")
    (ROOT / "docs" / "previsao-backtest.md").write_text("\n".join(relatorio))
    print("ok: data/previsao_calibracao.json + docs/previsao-backtest.md")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Rodar com dado real e revisar o relatório (GATE)**

```bash
uv run pytest tests/previsao/test_sql.py -q
uv run python scripts/backtest_previsao.py
```
Expected: JSON + relatório gerados; erro de RECEITA BRUTA estreitando com o dia (D5 largo, D25 <±5%); folha estável desde D5. **Apresentar `docs/previsao-backtest.md` ao usuário e obter o OK antes de ir para o front** — este é o gate de aceite do motor (spec §6/§12). Se alguma linha tiver erro absurdo (>±50% em D15+), investigar a estratégia dessa linha antes de seguir.

- [ ] **Step 4: Commitar**

```bash
git add scripts/backtest_previsao.py api/previsao/sql.py tests/previsao/test_sql.py \
        data/previsao_calibracao.json docs/previsao-backtest.md
git commit -m "feat(previsao): backtest as-of via dtinc + calibracao das bandas"
```

---

### Task 9: Frontend — vista `fech` (SPA `api/static/index.html`)

Edições por **substituição literal de trecho conhecido** (nunca regex ampla). Após cada leva: `uv run python scratchpad/estrutura.py` e recarregar o app local.

**Files:**
- Modify: `api/static/index.html` (12 pontos de registro + section + JS)

**Interfaces:**
- Consumes: `GET /api/controladoria/previsao?mes=` e `POST /api/controladoria/previsao/ajuste` (Task 7); helpers existentes `kpi()`, `statChip()`, `skelKpis()`, `chartArea()`, `brlAbbr()`, `numBR()`, `esc()`, `fmtD()`, `showBanner()/hideBanner()`, `CC`.
- Produces: vista `#fech` completa (desktop + gaveta mobile).

- [ ] **Step 1: Registros estruturais (HTML)**

1. **Sidebar** — em `#subsCtr`, logo após o `<a>` do `#orc`:

```html
        <a href="#fech" class="sub" data-view="fech" title="Fechamento do Mês — previsão do resultado antes de fechar"><span class="ic" data-ic="dre"></span><span>Fechamento do Mês</span></a>
```

2. **Gaveta mobile** — no `.dgrp` `data-grp="Ctr"`, após o link do `#orc`:

```html
        <a href="#fech" onclick="fecharDrawer()"><span class="ic" data-ic="dre"></span>Fechamento do Mês</a>
```

3. **Section** — junto às demais sections (após `view-orc` se existir, senão após `view-qual`):

```html
      <section class="view" id="view-fech">
        <div class="card" style="padding:14px 18px;display:flex;gap:12px;align-items:center;flex-wrap:wrap">
          <label style="font-size:13px;color:var(--n500)">Mês
            <select id="fFechMes" onchange="loadFech()" style="margin-left:8px"></select>
          </label>
          <span class="hint" id="fech-carimbo"></span>
        </div>
        <div id="fech-avisos"></div>
        <div class="kpis" id="kpis-fech"></div>
        <div class="grid2">
          <div class="card"><div class="head"><h2>Evolução da previsão <span class="ihelp" tabindex="0" role="img" aria-label="fonte do dado" title="Snapshot diário gravado a cada consulta (data/previsao.db): como o resultado previsto do mês evoluiu conforme o dado chegou. A linha do orçado é a referência fixa da versão vigente.">i</span><span class="hint">resultado previsto por dia · linha = orçado</span></div>
            <div class="chartwrap narrow"><svg id="chartFechEvol" viewBox="0 0 640 200" preserveAspectRatio="xMidYMid meet" role="img"></svg></div></div>
          <div class="card"><div class="head"><h2>Maiores desvios vs orçado <span class="ihelp" tabindex="0" role="img" aria-label="fonte do dado" title="Linhas diretas da DRE com maior |previsto - orçado| do mês. Cor pelo EFEITO no resultado (custo acima do orçado = ruim), não pelo sinal.">i</span><span class="hint">explicar o delta, não só mostrá-lo</span></div>
            <div id="fech-desvios"></div></div>
        </div>
        <div class="card">
          <div class="head"><h2>Cascata prevista <span class="ihelp" tabindex="0" role="img" aria-label="fonte do dado" title="Razão do AVA (lancamento, historico<>18, ajustes locais aplicados) + drivers operacionais (CT-e/NFS-e x meta diária, viagens, abastecimentos). Cada linha diz a estratégia no badge; previsto = calculado + ajuste manual. Banda = erro histórico do método no dia (backtest via dtinc).">i</span><span class="hint" id="fech-casc-hint"></span></div>
          <div class="tablewrap tabroll" id="fech-casc" style="max-height:640px"></div>
        </div>
      </section>
```

- [ ] **Step 2: Registros no JS (substituições literais, uma a uma)**

1. Em `VIEWS` (linha única), após `orc:'Orçamento',` inserir ` fech:'Fechamento do Mês',`.
2. Em `VIEW_GROUP`, na linha `dre:'Ctr',cont:'Ctr',qual:'Ctr',orc:'Ctr',` acrescentar `fech:'Ctr',`.
3. Junto às variáveis de estado (`let qualSeq = 0;`): `let fechSeq = 0;\nlet DATAFECH = null;`.
4. No `qsView`, antes do case das vistas-snapshot:

```js
  } else if(k==='fech'){
    if(V('fFechMes'))p.set('mes',V('fFechMes'));
```

5. Em `semFilterbar`, acrescentar `||v==='fech'` ao return.
6. No router: `DATAMAP` ganha `fech:DATAFECH,` e `LOADMAP` ganha `fech:loadFech,`.
7. Em `reloadCurrent()`, o mapa `M` ganha `fech:loadFech,`.
8. Em `NAV_KW`, após a entrada `orc:`, inserir:

```js
  fech:'previsao fechamento forecast resultado projecao mes corrente cenario banda',
```

- [ ] **Step 3: Loader, render e POST (inserir junto de loadQual)**

```js
// ---------------- Fechamento do Mês (previsão) ----------------
function fechMesOpts(){
  const sel=document.getElementById('fFechMes'); if(!sel||sel.options.length) return;
  const hoje=new Date(), m0=`${hoje.getFullYear()}-${String(hoje.getMonth()+1).padStart(2,'0')}`;
  const ant=new Date(hoje.getFullYear(), hoje.getMonth()-1, 1);
  const m1=`${ant.getFullYear()}-${String(ant.getMonth()+1).padStart(2,'0')}`;
  sel.innerHTML=`<option value="${m0}">${m0} (corrente)</option><option value="${m1}">${m1} (fechando)</option>`;
}
async function loadFech(){
  fechMesOpts();
  const seq=++fechSeq, btn=document.getElementById('btnRefresh'); if(btn) btn.disabled=true;
  document.getElementById('content').classList.add('loading');
  skelKpis('kpis-fech',4);
  try{
    const qs=qsView('fech');
    const r=await fetch('/api/controladoria/previsao'+(qs?'?'+qs:''),{cache:'no-store'});
    const d=await r.json(); if(seq!==fechSeq) return;
    if(!r.ok){ showBanner(d.mensagem||'Erro ao montar a previsão.', d.detalhe); return; }
    hideBanner(); DATAFECH=d; LOADEDQS.fech=qs; renderFech(d);
  }catch(e){ if(seq===fechSeq) showBanner('Não foi possível falar com a API.', e.message); }
  finally{ if(seq===fechSeq){ if(btn) btn.disabled=false; document.getElementById('content').classList.remove('loading'); } }
}
const FECH_ESTRAT={driver_fiscal:['b-info','driver fiscal'],pct_receita:['b-info','% receita'],
  razao_completude:['b-info','razão÷completude'],nivel:['b-info','nível'],sazonal:['b-info','sazonal'],
  frete_compra:['b-info','frete compra'],runrate:['b-info','run-rate'],consolidado:['b-ok','consolidado'],
  formula:['','fórmula'],fechado:['b-ok','fechado']};
function renderFech(d){
  const k=d.kpis||{}, modo=d.modo;
  document.getElementById('fech-carimbo').textContent=
    `dados até ${fmtD(k.dados_ate)} · modo ${modo}`+
    (k.consolidacao_pct!=null?` · razão ${Math.round(k.consolidacao_pct*100)}% consolidado`:'');
  document.getElementById('fech-avisos').innerHTML=(d.avisos||[]).map(a=>
    `<div class="card" style="padding:10px 16px;border-left:4px solid var(--yellow);margin-bottom:8px;font-size:13px">${esc(a)}</div>`).join('');
  const banda=(k.resultado_pess!=null&&k.resultado_otim!=null)?
    `entre ${brlAbbr(k.resultado_pess)} e ${brlAbbr(k.resultado_otim)}`:'';
  const vsOrc=k.resultado_orcado!=null?
    statChip(k.resultado_previsto>=k.resultado_orcado?'good':'bad',
      `${k.resultado_previsto>=k.resultado_orcado?'+':''}${brlAbbr(k.resultado_previsto-k.resultado_orcado)} vs orçado`,
      'Diferença do resultado previsto para o orçado do mês (versão vigente do Orçamento).'):'';
  document.getElementById('kpis-fech').innerHTML=[
    kpi('Resultado previsto do mês', brlAbbr(k.resultado_previsto||0), banda||'sem banda calibrada',
      (k.resultado_previsto||0)>=0?'pos':'neg', 'Cascata completa da DRE prevista: conhecido + projetado por linha, com ajustes manuais. NÃO é número fechado.', vsOrc),
    kpi('Orçado do mês', k.resultado_orcado!=null?brlAbbr(k.resultado_orcado):'—',
      k.resultado_orcado!=null?'versão vigente do Orçamento':'sem versão do ano', ''),
    kpi('Receita prevista', brlAbbr(k.receita_prevista||0),
      k.meta_mes?`meta ${brlAbbr(k.meta_mes)}`:'sem meta carregada',
      k.meta_mes&&k.receita_prevista>=k.meta_mes?'pos':''),
    kpi('Atingimento até hoje', k.atingimento_mtd!=null?Math.round(k.atingimento_mtd*100)+'%':'—',
      'realizado fiscal ÷ meta acumulada', k.atingimento_mtd!=null&&k.atingimento_mtd<0.9?'neg':'pos'),
  ].join('');
  // evolução: 1 ponto por snapshot diário do RESULTADO DO EXERCICIO
  const snaps=(d.serie_snapshots||[]).filter(s=>s.linha==='RESULTADO DO EXERCICIO');
  if(snaps.length){
    const cats=snaps.map(s=>s.data.slice(8)+'/'+s.data.slice(5,7));
    const series=[{nome:'previsto',cor:CC.navy5||'#38648D',valores:snaps.map(s=>s.previsto_base)}];
    if(k.resultado_orcado!=null) series.push({nome:'orçado',cor:CC.amarelo||'#B97709',valores:snaps.map(()=>k.resultado_orcado)});
    chartArea('chartFechEvol',cats,series,{fmt:brlAbbr});
  }
  // maiores desvios (linhas diretas com orçado)
  const diretas=(d.linhas||[]).filter(l=>!l.formula&&l.desvio!=null&&l.linha!=='NAO ALOCADO / CLASSIFICAR');
  const top=diretas.slice().sort((a,b)=>Math.abs(b.desvio)-Math.abs(a.desvio)).slice(0,6);
  document.getElementById('fech-desvios').innerHTML=top.map(l=>{
    const bom=l.desvio>=0; // sinal credor-positivo: desvio>=0 melhora o resultado
    return `<div style="display:flex;justify-content:space-between;gap:10px;padding:8px 4px;border-bottom:1px solid var(--n100);font-size:13px">
      <span>${esc(l.linha)} <span class="badge ${FECH_ESTRAT[l.estrategia]?.[0]||''}">${FECH_ESTRAT[l.estrategia]?.[1]||esc(l.estrategia)}</span></span>
      <b style="color:${bom?'var(--green)':'var(--red)'};font-family:var(--mono)">${bom?'+':''}${brlAbbr(l.desvio)}</b></div>`;
  }).join('')||'<div class="hint">sem orçamento para comparar</div>';
  // cascata
  const rl=(d.linhas||[]).find(l=>l.linha==='RECEITA LIQUIDA');
  const rlv=rl?Math.abs(rl.previsto)||1:1;
  const rows=(d.linhas||[]).map(l=>{
    const [bc,bt]=FECH_ESTRAT[l.estrategia]||['',l.estrategia];
    const nomeCell=`${l.nivel?'&nbsp;&nbsp;&nbsp;':''}${l.formula?'<b>':''}${esc(l.linha)}${l.formula?'</b>':''}`+
      (l.ajuste?` <span class="badge b-warn" title="${esc(l.ajuste.motivo||'')} (${esc(l.ajuste.autor||'')})">ajustado</span>`:'');
    const bandaCell=(l.previsto_pess!==l.previsto_otim)?
      `<span title="cenário pessimista .. otimista">${brlAbbr(l.previsto_pess)} .. ${brlAbbr(l.previsto_otim)}</span>`:'—';
    const premissas=(l.premissas||[]).join(' · ');
    const aj=l.formula?'':`<a href="#" onclick="fechAjuste('${esc(d.mes)}','${esc(l.linha)}',${l.previsto});return false" title="ajuste manual">✎</a>`;
    return `<tr${l.formula?' style="background:var(--n50,#fafafa)"':''} title="${esc(premissas)}">
      <td>${nomeCell}</td>
      <td class="num">${brlAbbr(l.realizado||0)}</td>
      <td class="num">${brlAbbr(l.projetado||0)}</td>
      <td class="num"><b>${brlAbbr(l.previsto||0)}</b></td>
      <td class="num" style="font-size:12px;color:var(--n500)">${bandaCell}</td>
      <td class="num">${l.orcado!=null?brlAbbr(l.orcado):'—'}</td>
      <td class="num" style="color:${l.desvio==null?'var(--n500)':(l.desvio>=0?'var(--green)':'var(--red)')}">${l.desvio!=null?(l.desvio>=0?'+':'')+brlAbbr(l.desvio):'—'}</td>
      <td class="num" style="color:var(--n500)">${Math.round(100*(l.previsto||0)/rlv)}%</td>
      <td>${l.formula?'':`<span class="badge ${bc}">${bt}</span>`} ${aj}</td></tr>`;
  }).join('');
  document.getElementById('fech-casc').innerHTML=
    `<table><thead><tr><th>Linha</th><th class="num">Realizado até hoje</th><th class="num">Projetado</th><th class="num">Previsto</th><th class="num">Banda</th><th class="num">Orçado</th><th class="num">Desvio</th><th class="num">% RL</th><th>Estratégia</th></tr></thead><tbody>${rows}</tbody></table>`;
  document.getElementById('fech-casc-hint').textContent=
    `${modo==='corrente'?'mês corrente (aberto)':'mês em fechamento'} · previsto = conhecido + projetado · hover mostra as premissas`;
}
async function fechAjuste(mes, linha, atual){
  const raw=prompt(
    `Ajuste manual em ${linha} (${mes})\n\nPrevisto calculado: ${brlAbbr(atual)}\n\n`+
    `Digite um DELTA em R$ (ex.: -120000) ou =VALOR absoluto (ex.: =950000).\n`+
    `Vazio remove o ajuste existente.`);
  if(raw===null) return;
  let tipo='delta', valor=null;
  const t=raw.trim();
  if(t!==''){
    tipo = t.startsWith('=')?'valor':'delta';
    valor = numBR(t.replace(/^=/,''));
    if(valor===null||Number.isNaN(valor)){ showBanner('Valor inválido: use número pt-BR (ex.: -120.000,50).'); return; }
  }
  const motivo = t===''?'': (prompt('Motivo do ajuste (obrigatório):')||'').trim();
  if(t!==''&&!motivo){ showBanner('Motivo é obrigatório.'); return; }
  if(!confirm(t===''?`Remover o ajuste de ${linha}?`:
      `Aplicar ${tipo==='delta'?'delta':'valor absoluto'} de ${brlAbbr(valor)} em ${linha}?\nMotivo: ${motivo}`)) return;
  try{
    const r=await fetch('/api/controladoria/previsao/ajuste',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mes, linha, tipo, valor, motivo})});
    const d=await r.json();
    if(!r.ok){ showBanner(d.mensagem||'Erro ao salvar o ajuste.'); return; }
    loadFech();
  }catch(e){ showBanner('Não foi possível salvar: '+e.message); }
}
```

- [ ] **Step 4: Validar**

```bash
uv run python scratchpad/estrutura.py
uv run python -c "from api import main"
scripts/run_api.sh &  # ou o servidor já em execução com --reload
```
No navegador (`http://127.0.0.1:8000/#fech`): KPIs carregam; seletor mês corrente/anterior alterna `corrente`/`fechando`; hover das linhas mostra premissas; ✎ grava e o badge "ajustado" aparece; gaveta mobile tem o link. Se `estrutura.py` assertar contagem de telas, atualizar a contagem esperada.

- [ ] **Step 5: Commitar**

```bash
git add api/static/index.html
git commit -m "feat(previsao): vista fech - cascata prevista, evolucao, desvios e ajuste manual"
```

---

### Task 10: Alertas no digest (`api/alertas.py`)

**Files:**
- Modify: `api/alertas.py` (helper novo + bloco em `build_alertas` antes do sort final)
- Test: `tests/previsao/test_alertas_previsao.py`

**Interfaces:**
- Consumes: `api.previsao.get_previsao_fechamento` (lazy) — payload da Task 6.
- Produces: `_alertas_previsao(payload: dict) -> list[tuple[str, str, str]]` (nivel, titulo, texto).

- [ ] **Step 1: Teste que falha**

```python
# tests/previsao/test_alertas_previsao.py
from __future__ import annotations

from api.alertas import _alertas_previsao


def _payload(prev, orc, avisos=()):
    return {"mes": "2026-08", "kpis": {"resultado_previsto": prev,
                                       "resultado_orcado": orc},
            "avisos": list(avisos)}


def test_previsto_negativo_e_critico():
    itens = _alertas_previsao(_payload(-50000.0, 100000.0))
    assert itens[0][0] == "critico" and "negativo" in itens[0][1].lower()


def test_abaixo_do_orcado_e_atencao():
    itens = _alertas_previsao(_payload(80000.0, 100000.0))
    assert itens[0][0] == "atencao" and "orçado" in itens[0][1].lower()


def test_acima_do_orcado_sem_alerta_de_resultado():
    assert _alertas_previsao(_payload(120000.0, 100000.0)) == []


def test_aviso_de_divergencia_vira_info():
    itens = _alertas_previsao(_payload(120000.0, 100000.0,
                                       ["Combustivel diverge: razao x abastecimentos"]))
    assert itens[0][0] == "info" and "combust" in itens[0][2].lower()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/previsao/test_alertas_previsao.py -q`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implementar** — em `api/alertas.py`, antes de `build_alertas`:

```python
def _alertas_previsao(payload: dict) -> list[tuple[str, str, str]]:
    """Alertas da previsão de fechamento (mês corrente). Puro — testável."""
    itens: list[tuple[str, str, str]] = []
    k = payload.get("kpis") or {}
    prev = k.get("resultado_previsto")
    orc = k.get("resultado_orcado")
    if prev is not None and prev < 0:
        itens.append(("critico", "Resultado do mês previsto NEGATIVO",
                      f"A previsão de fechamento de {payload.get('mes')} aponta "
                      f"{_fmt_brl(prev)}. Detalhe: Controladoria > Fechamento do Mês."))
    elif prev is not None and orc is not None and prev < orc:
        itens.append(("atencao", "Resultado do mês abaixo do orçado",
                      f"Previsto {_fmt_brl(prev)} contra orçado {_fmt_brl(orc)} "
                      f"({_fmt_brl(prev - orc)}). Detalhe: Controladoria > Fechamento do Mês."))
    for a in payload.get("avisos") or []:
        if "diverge" in a.lower():
            itens.append(("info", "Divergência de fonte na previsão", a))
    return itens
```

E dentro de `build_alertas`, ANTES do bloco `ordem = {...}` final (mesmo padrão do extrato):

```python
    try:
        from api.previsao import get_previsao_fechamento
        p = get_previsao_fechamento()
        for nivel, titulo, texto in _alertas_previsao(p):
            add(nivel, titulo, texto)
    except Exception as exc:  # noqa: BLE001
        log.warning("alertas previsao: %s", exc)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/previsao/test_alertas_previsao.py -q && uv run python -c "from api import main"`
Expected: 4 passed; import ok

- [ ] **Step 5: Commitar**

```bash
git add api/alertas.py tests/previsao/test_alertas_previsao.py
git commit -m "feat(previsao): alertas de resultado em risco no digest diario"
```

---

### Task 11: Validação final integrada e entrega

**Files:** nenhum novo — verificação e fechamento.

- [ ] **Step 1: Suíte completa + validadores**

```bash
uv run pytest -q                       # TODOS os testes do repo verdes
uv run python -c "from api import main"
uv run python scratchpad/estrutura.py
```

- [ ] **Step 2: Validação funcional com dado real (túnel de pé)**

```bash
uv run python -c "
from api.previsao import get_previsao_fechamento
for mes in (None, '2026-07'):
    r = get_previsao_fechamento(mes)
    print(r['mes'], r['modo'], 'resultado', round(r['kpis']['resultado_previsto']),
          'avisos', len(r['avisos']))
"
```
Conferências de sanidade contra telas existentes: (a) a linha RECEITA BRUTA prevista do mês corrente deve conversar com o atingimento da Visão Geral; (b) o realizado por linha do mês FECHADO deve bater ao centavo com a tela DRE (mesma base + ajustes); (c) julho "fechando" deve estimar CUSTO VARIAVEL na casa do jun/26 (~R$ -6,5 mi), não o parcial (~R$ -3,4 mi).

- [ ] **Step 3: Smoke de tela (Playwright, padrão do repo)**

Servidor de teste com auth isolada (padrão das validações anteriores: `auth.DB_PATH` para um SQLite temporário + `init_db()`), navegar `#fech` em 1280×800 e 390×844, conferir: KPIs renderizados, tabela com 23+ linhas, badge de estratégia presente, link na gaveta mobile. Registrar screenshot no scratchpad.

- [ ] **Step 4: Gate final com o usuário**

Apresentar: `docs/previsao-backtest.md` (erro por linha × dia) + screenshot da tela + os 3 números de sanidade do Step 2. **Deploy (git push → AutoDeploy) só com aprovação explícita do usuário.** Após o push, confirmar produção: tarefa AutoDeploy puxou o commit (`logs/deployed.txt`) e o painel público responde na vista `fech` (perfis Controladoria/Diretoria ganham a tela pelo seed v20 no primeiro restart).

- [ ] **Step 5: Commit final (se sobrou algo) e encerramento**

```bash
git status --short   # nada pendente
```

---

## Cobertura do spec (self-check)

| Spec § | Onde no plano |
|---|---|
| §3 arquitetura/fluxo (fetch paralelo, rollup, snapshot) | Task 6 |
| §4 estratégias por linha (driver fiscal, pct, frete_compra, razão÷completude, nível, sazonal, NAO ALOCADO) | Tasks 3, 4, 6 |
| §5 M-1 (curva dtinc, guarda <30%, trava 97%, barra de consolidação) | Tasks 2, 4, 6, 9 |
| §6 cenários + backtest + calibração + interpolação | Tasks 4, 8 |
| §7 ajustes manuais (SQLite, motivo obrigatório, coalesce, log) | Tasks 1, 6, 7, 9 |
| §8 API + RBAC (fech, v20, rota antes da genérica) | Task 7 |
| §9 tela (5 camadas, badges, ⓘ, tabroll, numBR) | Task 9 |
| §10 alertas/digest | Task 10 |
| §11 degradação (503, orçado "—", fonte degradada, snapshot best-effort) | Tasks 6, 7 (try/except em cada fonte) |
| §12 testes + gate de backtest | Tasks 1–8 (TDD), 8 (gate), 11 |
| §13 fora de escopo (GLOBUS, filial, rolling, TV) | Nenhuma task os implementa (guardado) |
| §14 riscos declarados (restatement, 1ºs dias, CAP=caixa, duas classificações) | Task 6 (kpis.cap_mes informativo; breakeven só como KPI; avisos) |


