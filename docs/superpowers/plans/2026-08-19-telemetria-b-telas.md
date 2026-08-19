# Telemetria B — Consumo, Condução e Hodômetro/Rastro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Três telas no grupo Telemetria sobre as APIs da Gobrax: consumo real da frota cruzado com os abastecimentos do AVA, indicadores de condução por veículo, e hodômetro com rastro no mapa.

**Architecture:** As APIs lentas (66–73 s para a frota) são coletadas em segundo plano e guardadas em `data/telemetria.db`; as rápidas são consultadas ao vivo. Cada tela declara de onde veio o número e de quando ele é.

**Tech Stack:** Python 3.12, `api/gobrax/cliente.py` (token), SQLite WAL, psycopg 3 para o cruzamento com o AVA, Leaflet (já na Torre), pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-08-19-telemetria-gobrax-design.md`

## Global Constraints

- **Latências medidas em 19/08/2026:** `vehicle-statistics` frota = 73 s; `vehicle-odometer` frota = 66 s; `vehicle-performance` **exige placa** e leva ~17 s cada; `positions` v2 = **0,7 s** para a frota num dia.
- **Consequência inegociável:** statistics e odometer NUNCA no carregamento da tela. Vêm do cache, com botão de atualizar. Performance é sob demanda por placa. Rastro pode ser ao vivo.
- **Toda tela declara a idade do dado** — "coletado em …". Número de telemetria sem data engana.
- **Nenhum CPF** gravado ou exibido; **o token** nunca em log ou payload.
- **Cobertura declarada**: veículo sem telemetria no período mostra `—` e entra no denominador, nunca num delta inventado.
- **Rodar**: `uv run pytest tests/telemetria/ -v`. Versão 0.7.0 → 0.8.0.

---

### Task 1: Armazenamento das coletas de telemetria

**Files:**
- Create: `api/gobrax/armazenamento.py`
- Test: `tests/telemetria/test_armazenamento.py`

**Interfaces:**
- Produces:
  - `DB_PATH` = `data/telemetria.db`
  - `init_db(path=None)`
  - `gravar(colecao: str, competencia: str, registros: list[dict], path=None) -> int` — substitui a coleção daquela competência numa transação; lista vazia levanta `ColetaVazia`
  - `ler(colecao: str, competencia: str, path=None) -> list[dict]`
  - `ultima(colecao: str, path=None) -> dict | None` — `{competencia, quando, registros}`
  - `class ColetaVazia(Exception)`

`colecao` é `"estatisticas"` ou `"odometro"`; `competencia` é `AAAA-MM`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/telemetria/test_armazenamento.py
"""Cache das coletas lentas de telemetria."""
from __future__ import annotations

import pytest

from api.gobrax import armazenamento as arm


@pytest.fixture
def base(tmp_path):
    p = tmp_path / "telemetria.db"
    arm.init_db(p)
    return p


def _reg(placa="AAA1A11", **kw):
    return {"placa": placa, "km": 1000.0, **kw}


def test_grava_e_le_por_colecao_e_competencia(base):
    arm.gravar("estatisticas", "2026-07", [_reg(), _reg("BBB2B22")], base)
    lido = arm.ler("estatisticas", "2026-07", base)
    assert {r["placa"] for r in lido} == {"AAA1A11", "BBB2B22"}


def test_colecoes_diferentes_nao_se_misturam(base):
    arm.gravar("estatisticas", "2026-07", [_reg("AAA1A11")], base)
    arm.gravar("odometro", "2026-07", [_reg("ZZZ9Z99")], base)
    assert [r["placa"] for r in arm.ler("odometro", "2026-07", base)] == ["ZZZ9Z99"]


def test_competencias_diferentes_convivem(base):
    arm.gravar("estatisticas", "2026-06", [_reg("AAA1A11")], base)
    arm.gravar("estatisticas", "2026-07", [_reg("BBB2B22")], base)
    assert len(arm.ler("estatisticas", "2026-06", base)) == 1
    assert len(arm.ler("estatisticas", "2026-07", base)) == 1


def test_recoleta_substitui_a_competencia(base):
    arm.gravar("estatisticas", "2026-07", [_reg("AAA1A11"), _reg("BBB2B22")], base)
    arm.gravar("estatisticas", "2026-07", [_reg("CCC3C33")], base)
    assert [r["placa"] for r in arm.ler("estatisticas", "2026-07", base)] == ["CCC3C33"]


def test_coleta_vazia_nao_apaga_o_que_estava_la(base):
    """Mesma regra da premiação e do RNTRC: vazio não sobrescreve dado bom."""
    arm.gravar("estatisticas", "2026-07", [_reg()], base)
    with pytest.raises(arm.ColetaVazia):
        arm.gravar("estatisticas", "2026-07", [], base)
    assert len(arm.ler("estatisticas", "2026-07", base)) == 1


def test_ultima_diz_de_quando_e_o_dado(base):
    """Número de telemetria sem data engana: a tela precisa mostrar a idade."""
    arm.gravar("estatisticas", "2026-07", [_reg()], base)
    u = arm.ultima("estatisticas", base)
    assert u["competencia"] == "2026-07" and u["registros"] == 1 and u["quando"]


def test_sem_coleta_devolve_vazio_sem_quebrar(base):
    assert arm.ler("estatisticas", "2026-01", base) == []
    assert arm.ultima("estatisticas", base) is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/telemetria/test_armazenamento.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar**

Espelhe `api/antt/armazenamento.py` (conexão curta, WAL, `with c:`).

```python
# api/gobrax/armazenamento.py
"""Cache local das coletas lentas da Gobrax — data/telemetria.db.

vehicle-statistics leva 73 s para a frota e vehicle-odometer 66 s. Nenhuma tela
pode pagar isso no carregamento, então o resultado é coletado em segundo plano e
lido daqui. O registro vai como JSON: o formato da API muda com o tempo e não
vale criar coluna para cada campo.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "telemetria.db"


class ColetaVazia(Exception):
    """Coleta sem registros. Nunca substitui o que já está gravado."""


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


def init_db(path: Path | None = None) -> None:
    with _conn(path or DB_PATH) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS coleta(
            colecao     TEXT NOT NULL,
            competencia TEXT NOT NULL,
            registro    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_coleta ON coleta(colecao, competencia);
        CREATE TABLE IF NOT EXISTS coleta_log(
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            colecao     TEXT NOT NULL,
            competencia TEXT NOT NULL,
            quando      TEXT NOT NULL,
            registros   INTEGER NOT NULL
        );
        """)


def gravar(colecao: str, competencia: str, registros: list[dict],
           path: Path | None = None) -> int:
    if not registros:
        raise ColetaVazia(f"coleta de {colecao}/{competencia} veio vazia")
    p = path or DB_PATH
    init_db(p)
    with _conn(p) as c:
        c.execute("DELETE FROM coleta WHERE colecao=? AND competencia=?",
                  (colecao, competencia))
        c.executemany(
            "INSERT INTO coleta(colecao, competencia, registro) VALUES(?,?,?)",
            [(colecao, competencia, json.dumps(r, ensure_ascii=False))
             for r in registros])
        c.execute("INSERT INTO coleta_log(colecao, competencia, quando, registros)"
                  " VALUES(?,?,?,?)",
                  (colecao, competencia,
                   datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(registros)))
    return len(registros)


def ler(colecao: str, competencia: str, path: Path | None = None) -> list[dict]:
    p = path or DB_PATH
    if not Path(p).exists():
        return []
    with _conn(p) as c:
        return [json.loads(r["registro"]) for r in c.execute(
            "SELECT registro FROM coleta WHERE colecao=? AND competencia=?",
            (colecao, competencia))]


def ultima(colecao: str, path: Path | None = None) -> dict | None:
    p = path or DB_PATH
    if not Path(p).exists():
        return None
    with _conn(p) as c:
        row = c.execute(
            "SELECT competencia, quando, registros FROM coleta_log"
            " WHERE colecao=? ORDER BY id DESC LIMIT 1", (colecao,)).fetchone()
    return dict(row) if row else None
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/telemetria/test_armazenamento.py -v`
Expected: PASS, 7 testes.

- [ ] **Step 5: Commit**

```bash
git add api/gobrax/armazenamento.py tests/telemetria/test_armazenamento.py
git commit -m "feat(telemetria): cache local das coletas lentas"
```

---

### Task 2: Estatísticas e odômetro — coleta e normalização

**Files:**
- Create: `api/gobrax/estatisticas.py`, `api/gobrax/odometro.py`
- Test: `tests/telemetria/test_estatisticas.py`

**Interfaces:**
- Produces:
  - `estatisticas.coletar(competencia: str, cliente=None) -> list[dict]` — `{placa, km, litros, km_l, vel_media, odometro, freadas, freadas_alta}`
  - `estatisticas.sincronizar(competencia: str, cliente=None, path=None) -> dict`
  - `odometro.coletar(competencia: str, cliente=None) -> list[dict]` — `{placa, odometro, lido_em}`
  - `odometro.sincronizar(competencia: str, cliente=None, path=None) -> dict`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/telemetria/test_estatisticas.py
"""Normalização das estatísticas e do odômetro."""
from __future__ import annotations

from api.gobrax import estatisticas, odometro

RESP_STATS = {"records": [
    {"vehicleIdentification": "ABC-1234", "averageSpeed": 60.0,
     "consumptionAverage": 1.73, "odometer": 291862.215, "totalConsumption": 12.82,
     "totalMileage": 22.17, "totalBreakingOnHighSpeed": 0, "totalBreaking": 9},
    {"vehicleIdentification": "DDD-4444", "averageSpeed": 71.0,
     "consumptionAverage": 0, "odometer": 311202.110, "totalConsumption": 0,
     "totalMileage": 0, "totalBreakingOnHighSpeed": 1, "totalBreaking": 19},
]}

RESP_ODO = {"records": [
    {"vehicleIdentification": "ABC-1234", "odometer": 140773.04,
     "lastUpdated": "2026-07-31 23:59:35+0000"},
    {"vehicleIdentification": "SEM-LEITURA", "odometer": 0, "lastUpdated": None},
]}


class ClienteFalso:
    def __init__(self, resp):
        self.resp = resp
        self.chamadas = []

    def get(self, caminho, params=None, timeout=120):
        self.chamadas.append((caminho, params))
        return self.resp


def test_estatisticas_normaliza_os_campos():
    r = estatisticas.coletar("2026-07", cliente=ClienteFalso(RESP_STATS))[0]
    assert r["placa"] == "ABC-1234"
    assert r["km_l"] == 1.73
    assert r["km"] == 22.17
    assert r["litros"] == 12.82
    assert r["freadas"] == 9
    assert r["freadas_alta"] == 0


def test_estatisticas_pede_o_mes_inteiro():
    c = ClienteFalso(RESP_STATS)
    estatisticas.coletar("2026-07", cliente=c)
    _caminho, params = c.chamadas[0]
    assert params["startDate"] == "2026-07-01 00:00:00"
    assert params["endDate"] == "2026-07-31 23:59:59"


def test_fevereiro_tem_o_ultimo_dia_certo():
    c = ClienteFalso(RESP_STATS)
    estatisticas.coletar("2026-02", cliente=c)
    assert c.chamadas[0][1]["endDate"] == "2026-02-28 23:59:59"


def test_veiculo_sem_consumo_fica_com_km_l_nulo_nao_zero():
    """Zero é uma medida; ausência não é. Um km/l zero entraria na média da
    frota e a puxaria para baixo sem que ninguém tenha rodado mal."""
    linhas = estatisticas.coletar("2026-07", cliente=ClienteFalso(RESP_STATS))
    ddd = [l for l in linhas if l["placa"] == "DDD-4444"][0]
    assert ddd["km_l"] is None


def test_odometro_normaliza_e_marca_sem_leitura():
    linhas = odometro.coletar("2026-07", cliente=ClienteFalso(RESP_ODO))
    ok = [l for l in linhas if l["placa"] == "ABC-1234"][0]
    assert ok["odometro"] == 140773.04
    assert ok["lido_em"] == "2026-07-31 23:59:35+0000"
    sem = [l for l in linhas if l["placa"] == "SEM-LEITURA"][0]
    assert sem["odometro"] is None


def test_resposta_sem_records_devolve_lista_vazia():
    assert estatisticas.coletar("2026-07", cliente=ClienteFalso({})) == []
    assert odometro.coletar("2026-07", cliente=ClienteFalso({})) == []
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/telemetria/test_estatisticas.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar**

```python
# api/gobrax/periodo.py  (helper compartilhado)
"""Primeiro e último instante de uma competência AAAA-MM."""
from __future__ import annotations

import calendar
from datetime import date

from api.gobrax.cliente import periodo_api


def mes_inteiro(competencia: str) -> tuple[str, str]:
    ano, mes = (int(x) for x in competencia.split("-"))
    ultimo = calendar.monthrange(ano, mes)[1]
    return periodo_api(date(ano, mes, 1), date(ano, mes, ultimo))
```

```python
# api/gobrax/estatisticas.py
"""vehicle-statistics — consumo, velocidade e frenagens por veículo.

Aceita a frota inteira numa chamada, mas leva ~73 s: só é chamada pela
sincronização, nunca pelo carregamento de uma tela.
"""
from __future__ import annotations

from pathlib import Path

from api.gobrax import armazenamento
from api.gobrax.cliente import Cliente
from api.gobrax.periodo import mes_inteiro

CAMINHO = "/api/v1/vehicle-statistics"
COLECAO = "estatisticas"


def _num(valor):
    """Zero da API vira None: ausência de medida não é medida zero."""
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def coletar(competencia: str, cliente=None) -> list[dict]:
    ini, fim = mes_inteiro(competencia)
    c = cliente or Cliente()
    corpo = c.get(CAMINHO, {"startDate": ini, "endDate": fim,
                            "vehicleIdentification": ""}, timeout=240)
    saida = []
    for r in (corpo.get("records") or []):
        saida.append({
            "placa": (r.get("vehicleIdentification") or "").strip(),
            "km": _num(r.get("totalMileage")),
            "litros": _num(r.get("totalConsumption")),
            "km_l": _num(r.get("consumptionAverage")),
            "vel_media": _num(r.get("averageSpeed")),
            "odometro": _num(r.get("odometer")),
            "freadas": int(r.get("totalBreaking") or 0),
            "freadas_alta": int(r.get("totalBreakingOnHighSpeed") or 0),
        })
    return saida


def sincronizar(competencia: str, cliente=None, path: Path | None = None) -> dict:
    linhas = coletar(competencia, cliente)
    gravadas = armazenamento.gravar(COLECAO, competencia, linhas, path)
    return {"competencia": competencia, "gravadas": gravadas}
```

```python
# api/gobrax/odometro.py
"""vehicle-odometer — hodômetro e data da última leitura.

Leva ~66 s para a frota: mesma regra das estatísticas, só pela sincronização.
"""
from __future__ import annotations

from pathlib import Path

from api.gobrax import armazenamento
from api.gobrax.cliente import Cliente
from api.gobrax.periodo import mes_inteiro

CAMINHO = "/api/v2/vehicle-odometer"
COLECAO = "odometro"


def coletar(competencia: str, cliente=None) -> list[dict]:
    ini, fim = mes_inteiro(competencia)
    c = cliente or Cliente()
    corpo = c.get(CAMINHO, {"startDate": ini, "endDate": fim,
                            "vehicleIdentification": ""}, timeout=240)
    saida = []
    for r in (corpo.get("records") or []):
        try:
            odo = float(r.get("odometer") or 0)
        except (TypeError, ValueError):
            odo = 0
        saida.append({
            "placa": (r.get("vehicleIdentification") or "").strip(),
            "odometro": odo if odo > 0 else None,
            "lido_em": r.get("lastUpdated"),
        })
    return saida


def sincronizar(competencia: str, cliente=None, path: Path | None = None) -> dict:
    linhas = coletar(competencia, cliente)
    gravadas = armazenamento.gravar(COLECAO, competencia, linhas, path)
    return {"competencia": competencia, "gravadas": gravadas}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/telemetria/test_estatisticas.py -v`
Expected: PASS, 6 testes.

- [ ] **Step 5: Provar contra a API real (leva ~2,5 min)**

```bash
uv run python -c "
import os
from pathlib import Path
for l in Path('.env').read_text().splitlines():
    if l.strip() and not l.startswith('#') and '=' in l:
        k,v=l.split('=',1); os.environ.setdefault(k.strip(), v.strip())
from api.gobrax import estatisticas, odometro
e = estatisticas.sincronizar('2026-07'); print('estatisticas:', e)
o = odometro.sincronizar('2026-07'); print('odometro:', o)
"
```

Expected: ~74 veículos em cada. Se demorar mais que 4 minutos, aumente o
timeout em vez de reduzir o escopo — a lentidão é da API, não do código.

- [ ] **Step 6: Commit**

```bash
git add api/gobrax tests/telemetria
git commit -m "feat(telemetria): coleta de estatisticas e odometro"
```

---

### Task 3: Cruzamento com o combustível do AVA

**Files:**
- Create: `api/gobrax/consumo.py`, `api/gobrax/sql.py`
- Test: `tests/telemetria/test_consumo.py`

**Interfaces:**
- Produces:
  - `sql.ABASTECIMENTO_MES_SQL: str` — por placa: litros e km do AVA no mês
  - `consumo.cruzar(telemetria: list[dict], ava: list[dict]) -> list[dict]`
  - `consumo.resumir(linhas: list[dict]) -> dict`
  - `consumo.get_consumo(competencia: str) -> dict`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/telemetria/test_consumo.py
"""Telemetria × abastecimento: duas medidas independentes do mesmo consumo."""
from __future__ import annotations

from api.gobrax import consumo


def _tel(placa="AAA1A11", km=1000.0, litros=250.0, km_l=4.0):
    return {"placa": placa, "km": km, "litros": litros, "km_l": km_l,
            "vel_media": 60.0, "odometro": 100000.0, "freadas": 5,
            "freadas_alta": 1}


def _ava(placa="AAA1A11", litros=250.0, km=1000.0):
    return {"placa": placa, "litros_ava": litros, "km_ava": km}


def test_placas_que_batem_ganham_as_duas_medidas():
    l = consumo.cruzar([_tel()], [_ava()])[0]
    assert l["km_l"] == 4.0
    assert l["km_l_ava"] == 4.0
    assert l["delta_pct"] == 0


def test_divergencia_e_calculada_em_percentual():
    """Telemetria 4,0 e abastecimento 3,2: a telemetria está 25% acima."""
    l = consumo.cruzar([_tel(km_l=4.0)], [_ava(litros=312.5)])[0]
    assert round(l["km_l_ava"], 2) == 3.2
    assert round(l["delta_pct"], 1) == 25.0


def test_veiculo_so_na_telemetria_nao_inventa_delta():
    l = consumo.cruzar([_tel()], [])[0]
    assert l["km_l_ava"] is None
    assert l["delta_pct"] is None


def test_veiculo_so_no_ava_aparece_como_sem_telemetria():
    linhas = consumo.cruzar([], [_ava(placa="BBB2B22")])
    assert linhas[0]["placa"] == "BBB2B22"
    assert linhas[0]["km_l"] is None


def test_placa_com_e_sem_hifen_casa():
    """A Gobrax devolve ABC-1234 e o AVA guarda ABC1234."""
    l = consumo.cruzar([_tel(placa="ABC-1234")], [_ava(placa="ABC1234")])[0]
    assert l["km_l_ava"] is not None


def test_abastecimento_sem_litros_nao_vira_divisao_por_zero():
    l = consumo.cruzar([_tel()], [_ava(litros=0)])[0]
    assert l["km_l_ava"] is None
    assert l["delta_pct"] is None


def test_resumo_declara_a_cobertura_do_cruzamento():
    linhas = consumo.cruzar([_tel(), _tel(placa="BBB2B22")], [_ava()])
    k = consumo.resumir(linhas)
    assert k["veiculos"] == 2
    assert k["com_as_duas_medidas"] == 1
    assert k["km_l_frota"] is not None


def test_resumo_de_lista_vazia_nao_divide_por_zero():
    k = consumo.resumir([])
    assert k["veiculos"] == 0 and k["km_l_frota"] is None


def test_divergentes_sao_os_que_passam_do_limite():
    linhas = consumo.cruzar(
        [_tel(placa="OK", km_l=4.0), _tel(placa="RUIM", km_l=4.0)],
        [_ava(placa="OK", litros=250.0), _ava(placa="RUIM", litros=400.0)])
    k = consumo.resumir(linhas, limite_pct=15.0)
    assert k["divergentes"] == 1
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/telemetria/test_consumo.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar o SQL**

Reuse a fonte de abastecimento que a tela de Combustível já usa. Procure em
`api/queries.py` por `ctaplus_abastecimentos` e siga os mesmos filtros —
inclusive a exclusão de ARLA, que já está lá.

```python
# api/gobrax/sql.py
"""Abastecimento do AVA por placa, para cruzar com a telemetria.

Mesma fonte da tela de Combustivel (sulista.ctaplus_abastecimentos), com os
mesmos filtros: ARLA fora, distancia sana. Sem acento: LATIN-1 no PG 9.3.
"""
from __future__ import annotations

ABASTECIMENTO_MES_SQL = """
SELECT upper(regexp_replace(coalesce(a.veiculo_placa,''),'[^A-Za-z0-9]','','g'))
         AS placa,
       coalesce(sum(a.volume),0)::float8 AS litros_ava,
       coalesce(sum(CASE WHEN a.distancia > 0 AND a.distancia < 3000
                         THEN a.distancia ELSE 0 END),0)::float8 AS km_ava
FROM sulista.ctaplus_abastecimentos a
WHERE a.data_inicio_abastecimento >= %(de)s::date
  AND a.data_inicio_abastecimento <  %(ate)s::date
  AND coalesce(a.combustivel_descricao,'') NOT ILIKE '%%arla%%'
GROUP BY 1
"""
```

**Confirme os nomes das colunas contra o banco antes de seguir** — a Fase 1 da
ANTT mostrou que coluna suposta não existe. Rode:

```bash
uv run python -c "
import os
from pathlib import Path
for l in Path('.env').read_text().splitlines():
    if l.strip() and not l.startswith('#') and '=' in l:
        k,v=l.split('=',1); os.environ.setdefault(k.strip(), v.strip())
from api import db
with db.get_conn() as c, c.cursor() as cur:
    cur.execute('''SELECT column_name FROM information_schema.columns
                   WHERE table_schema='sulista' AND table_name='ctaplus_abastecimentos'
                   ORDER BY 1''')
    print([r['column_name'] for r in cur.fetchall()])
"
```

Se `veiculo_placa`, `volume`, `distancia` ou `combustivel_descricao` tiverem
outro nome, ajuste o SQL e o teste juntos.

- [ ] **Step 4: Implementar o cruzamento**

```python
# api/gobrax/consumo.py
"""Telemetria × abastecimento — duas medidas independentes do mesmo consumo.

A telemetria mede o que o motor gastou; o abastecimento mede o que saiu da
bomba. Onde os dois divergem muito há desvio, bomba descalibrada ou
abastecimento não lançado — e é essa diferença, não cada número isolado, que
justifica a tela.
"""
from __future__ import annotations

import re

from api.gobrax import armazenamento, estatisticas

_SO_ALNUM = re.compile(r"[^A-Za-z0-9]")

LIMITE_DIVERGENCIA_PCT = 15.0


def normalizar_placa(placa: str | None) -> str:
    """A Gobrax devolve ABC-1234; o AVA guarda ABC1234."""
    return _SO_ALNUM.sub("", (placa or "")).upper()


def cruzar(telemetria: list[dict], ava: list[dict]) -> list[dict]:
    por_placa: dict[str, dict] = {}
    for t in telemetria:
        chave = normalizar_placa(t.get("placa"))
        if chave:
            por_placa[chave] = {**t, "km_l_ava": None, "delta_pct": None}
    for a in ava:
        chave = normalizar_placa(a.get("placa"))
        if not chave:
            continue
        linha = por_placa.setdefault(chave, {
            "placa": a.get("placa"), "km": None, "litros": None, "km_l": None,
            "vel_media": None, "odometro": None, "freadas": 0, "freadas_alta": 0,
            "km_l_ava": None, "delta_pct": None})
        litros = float(a.get("litros_ava") or 0)
        km = float(a.get("km_ava") or 0)
        linha["litros_ava"] = litros or None
        linha["km_ava"] = km or None
        # km/l do abastecimento: km da telemetria é a medida boa de distância;
        # o AVA só tem a distância declarada no abastecimento, que falha mais
        km_ref = linha.get("km") or km
        if litros > 0 and km_ref > 0:
            linha["km_l_ava"] = km_ref / litros
            if linha.get("km_l"):
                linha["delta_pct"] = (linha["km_l"] / linha["km_l_ava"] - 1) * 100
    return sorted(por_placa.values(),
                  key=lambda l: -abs(l.get("delta_pct") or 0))


def resumir(linhas: list[dict], limite_pct: float = LIMITE_DIVERGENCIA_PCT) -> dict:
    com_duas = [l for l in linhas if l.get("km_l") and l.get("km_l_ava")]
    km = sum(float(l.get("km") or 0) for l in linhas)
    litros = sum(float(l.get("litros") or 0) for l in linhas)
    return {
        "veiculos": len(linhas),
        "com_telemetria": sum(1 for l in linhas if l.get("km_l")),
        "com_as_duas_medidas": len(com_duas),
        "km_total": km,
        "litros_total": litros,
        "km_l_frota": (km / litros) if litros > 0 else None,
        "freadas": sum(int(l.get("freadas") or 0) for l in linhas),
        "freadas_alta": sum(int(l.get("freadas_alta") or 0) for l in linhas),
        "divergentes": sum(1 for l in com_duas
                           if abs(l.get("delta_pct") or 0) > limite_pct),
        "limite_pct": limite_pct,
    }


def get_consumo(competencia: str) -> dict:
    import calendar
    from datetime import date

    from api import db
    from api.gobrax.sql import ABASTECIMENTO_MES_SQL

    tel = armazenamento.ler(estatisticas.COLECAO, competencia)
    ano, mes = (int(x) for x in competencia.split("-"))
    ultimo = calendar.monthrange(ano, mes)[1]
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(ABASTECIMENTO_MES_SQL,
                    {"de": date(ano, mes, 1).isoformat(),
                     "ate": date(ano, mes, ultimo).isoformat()})
        ava = [dict(r) for r in cur.fetchall()]
    linhas = cruzar(tel, ava)
    return {
        "competencia": competencia,
        "kpis": resumir(linhas),
        "linhas": linhas,
        "sync": armazenamento.ultima(estatisticas.COLECAO),
        "fonte": ("Gobrax vehicle-statistics (cache local) × "
                  "sulista.ctaplus_abastecimentos do AVA, por placa"),
    }
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `uv run pytest tests/telemetria/test_consumo.py -v`
Expected: PASS, 9 testes.

- [ ] **Step 6: Provar contra os dois lados reais**

```bash
uv run python -c "
import os
from pathlib import Path
for l in Path('.env').read_text().splitlines():
    if l.strip() and not l.startswith('#') and '=' in l:
        k,v=l.split('=',1); os.environ.setdefault(k.strip(), v.strip())
from api.gobrax import consumo
d = consumo.get_consumo('2026-07')
print(d['kpis'])
for l in d['linhas'][:5]:
    print(l['placa'], 'tel', l['km_l'], 'ava', l['km_l_ava'], 'delta%', l['delta_pct'])
"
```

Expected: cobertura declarada e alguns veículos com as duas medidas. **Se
`com_as_duas_medidas` vier zero, o casamento de placa falhou** — é o defeito
mais provável desta tarefa, e não um achado de negócio.

- [ ] **Step 7: Commit**

```bash
git add api/gobrax/consumo.py api/gobrax/sql.py tests/telemetria/test_consumo.py
git commit -m "feat(telemetria): cruzamento de consumo telemetria x abastecimento"
```

---

### Task 4: Endpoints, RBAC e as três telas

**Files:**
- Modify: `api/main.py`, `api/auth.py`, `api/static/index.html`
- Create: `api/gobrax/performance.py`, `api/gobrax/rastro.py`
- Test: `tests/telemetria/test_telas_e2e.py`

**Interfaces:**
- `GET /api/telemetria/consumo?competencia=AAAA-MM`
- `POST /api/telemetria/consumo/atualizar`
- `GET /api/telemetria/conducao?placa=&competencia=` — ao vivo, ~17 s
- `GET /api/telemetria/hodometro?competencia=`
- `GET /api/telemetria/rastro?placa=&data=AAAA-MM-DD` — ao vivo, rápido

Telas `telcon`, `telcond`, `telhod` no grupo Telemetria, com o mesmo tratamento
das anteriores: registro em `VIEWS`, `DATAMAP`, `LOADMAP`, gaveta mobile e RBAC
(seed v25, perfis Frota e Diretoria — a telemetria é operação de frota).

- [ ] **Step 1..N**

Siga, para cada tela, o roteiro já validado nas telas de ANTT: teste de
marcação, registro nos cinco pontos do `index.html`, marcação da view com
`ihelp` declarando a fonte, loader espelhando `loadAnpiso`, e teste de browser
com payload real do serviço.

**Pontos específicos que não podem ser esquecidos:**

- `telcon` mostra a **idade do cache** ("coletado em …") e o botão de atualizar
  avisa que leva mais de um minuto.
- `telcond` **exige placa**: sem placa selecionada a tela não chama a API, e
  explica que a consulta demora ~17 s.
- `telhod` cruza o odômetro com a **Manutenção Preventiva** só como referência
  visual; não altera nada naquela tela.
- O rastro desenha no Leaflet **reusando o mapa da Torre**; ponto sem `speed`
  não vira marcador colorido.

- [ ] **Passo final: versão 0.8.0, manual, CLAUDE.md e suíte completa**

---

## Fora do escopo

`vehicle-event` e `drivers` (escrita) continuam fora. A coleta agendada
automática também: por ora as sincronizações são pelo botão, como no RNTRC.
