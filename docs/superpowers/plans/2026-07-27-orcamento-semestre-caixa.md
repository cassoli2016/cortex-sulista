# Orçamento base 1º semestre + provisão de caixa — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Novo método de derivação "Semestre × sazonalidade" no módulo Orçamento e série de provisão orçamentária (competência → caixa via DSO/DPO) no Fluxo de Caixa.

**Architecture:** Duas funções puras novas em `api/orcamento/derivacao.py` (índices sazonais por linha + derivação semestral), coluna `metodo` em `orc_versao`, o `gerar()` do serviço ramifica por método; `api/orcamento/caixa.py` puro converte o orçado em caixa com deslocamento fracionário e `get_fluxo` anexa a série lida do SQLite local.

**Tech Stack:** Python (FastAPI, sqlite3, pytest), SPA vanilla-JS (`api/static/index.html`), PG 9.3 read-only via `HIST_CONTA_SQL` (só leitura de histórico).

## Global Constraints

- **Branch:** `feat/orcamento-semestre-caixa` a partir de `main` (Task 1). SEM push/merge — decisão do usuário no fim.
- **Spec governa:** `docs/superpowers/specs/2026-07-27-orcamento-semestre-caixa-design.md`. Divergência → perguntar.
- **ERP AVA é réplica somente-leitura**; este trabalho só LÊ (`HIST_CONTA_SQL` em janelas de 6 e 24 meses).
- **O método espelho NÃO muda**: gerar com `metodo="espelho"` (ou omitido) tem de produzir exatamente o que produz hoje (teste de regressão obrigatório).
- Fórmulas exatas: `nivel = soma(6 meses)/6`; `valor = nivel × indice_linha[mes] × (1+fator)`; índice `= media_cal[m]/media_geral` renormalizado p/ média 1; flat se `|media_geral| < 1e-9` OU índice fora de **[0, 3]** OU linha com menos de 24 meses de dado na janela.
- Caixa: `x = dias/30.44`, `k = floor(x)`, `f = x−k` → `(1−f)` em `M+k` e `f` em `M+k+1`; entradas (valores >0) usam DSO, saídas (<0) usam DPO; além de dezembro = transbordo (fora da série, reportado). Fallback DSO 49 / DPO 79 com `dso_fonte: "padrao"`.
- Domínio de `origem` ganha `"semestre"`; `metodo` ∈ {`espelho`,`semestre`} (POST com outro valor → 422).
- Front: edições por substituição literal + `node --check` após CADA edição; `ast.parse` nos `.py`; campo decimal via `numBR()`; nenhum `const` de topo lendo `CC`.
- Suíte atual: **193 testes** — continuam passando após cada task. `uv run --with pytest python -m pytest tests/ -q`.
- **Túnel AVA pode estar FORA** (sshd da máquina em mau estado): toda validação contra o Postgres real é *best-effort* — se `nc -z 127.0.0.1 15432` falhar, registrar a pendência e validar com stubs/SQLite (a Task 6 detalha).
- Commits pt-BR curtos ao fim de cada task.

## Estrutura de arquivos

| Arquivo | Mudança |
|---|---|
| `api/orcamento/derivacao.py` | + `indices_sazonais()`, + `derivar_semestre()` (puros) |
| `api/orcamento/armazenamento.py` | + coluna `metodo` (migração PRAGMA/ALTER), criar/atualizar aceitam `metodo` |
| `api/orcamento/servico.py` | `gerar(metodo=...)` ramifica; regerar usa o método gravado; resposta com `metodo`/`linhas_flat` |
| `api/orcamento/caixa.py` | NOVO: `provisao_caixa()` e `provisao_do_ano()` (SQLite local, sem Postgres) |
| `api/main.py` | validação de `metodo` no POST /gerar |
| `api/queries.py` | `get_fluxo` anexa `provisao_orc` (try/except, nunca quebra o fluxo) |
| `api/static/index.html` | Montagem: select de método, badge, aviso flat; Fluxo: série tracejada + tooltip + ⓘ |
| `tests/orcamento/test_derivacao.py`, `test_caixa.py` (novo), `test_servico.py`, `test_armazenamento.py` | testes por camada |

---

### Task 1: Índices sazonais + derivação semestral (puros)

**Files:**
- Modify: `api/orcamento/derivacao.py`
- Test: `tests/orcamento/test_derivacao.py` (append)

**Interfaces:**
- Consumes: nada novo (módulo já é puro).
- Produces:
  - `indices_sazonais(serie_linha: dict[str, dict[str, float]], meses24: list[str]) -> tuple[dict[str, dict[int, float]], list[str]]` — entrada `{linha: {"AAAA-MM": valor}}` (JÁ agregada por linha; quem agrega é o serviço na Task 2); saída `({linha: {1..12: indice}}, linhas_flat)`.
  - `derivar_semestre(historico: dict[str, dict[str, float]], meses_base: list[str], indices: dict[str, dict[int, float]], mapa_linha: dict[str, str | None], fator: float) -> list[dict]` — mesmas chaves de linha de saída do `derivar` atual (`conta, mes, valor_baseline, origem, meses_com_dado`), com `origem ∈ {"semestre","sem_base"}`. Conta cuja linha não tem índice (mapa devolve None ou linha fora de `indices`) usa índice 1 (flat) — a exclusão de conta sem linha é responsabilidade do serviço, como hoje.

- [ ] **Step 1: Criar a branch e escrever os testes (append em `tests/orcamento/test_derivacao.py`)**

```bash
git checkout main && git pull --ff-only 2>/dev/null; git checkout -b feat/orcamento-semestre-caixa
```

```python
# ------------------------------------------------- semestre × sazonalidade

from api.orcamento.derivacao import derivar_semestre, indices_sazonais

MESES6 = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
MESES24 = [f"{a}-{m:02d}" for a in (2024, 2025) for m in range(7, 13)] + \
          [f"{a}-{m:02d}" for a in (2025, 2026) for m in range(1, 7)]
MESES24 = sorted(set(MESES24))  # jul/24..jun/26, 24 meses


def _serie_linha(valor_por_mes_cal: dict[int, float]) -> dict[str, float]:
    return {m: valor_por_mes_cal.get(int(m[5:7]), 100.0) for m in MESES24}


def test_indice_sazonal_captura_a_queda_de_dezembro():
    serie = {"RECEITA BRUTA": _serie_linha({12: 40.0})}   # dez=40, resto=100
    idx, flat = indices_sazonais(serie, MESES24)
    # media_geral = (22*100 + 2*40)/24 = 95 -> dez = 40/95, demais = 100/95
    assert abs(idx["RECEITA BRUTA"][12] - 40.0 / 95.0) < 1e-9
    assert abs(idx["RECEITA BRUTA"][3] - 100.0 / 95.0) < 1e-9
    assert abs(sum(idx["RECEITA BRUTA"].values()) / 12 - 1.0) < 1e-9   # média 1
    assert flat == []


def test_indice_vira_flat_nas_tres_guardas():
    quase_zero = {m: (100.0 if int(m[5:7]) % 2 else -100.0) for m in MESES24}
    pico = {m: (50.0 if m == "2026-03" else 1.0) for m in MESES24}
    curta = {m: 100.0 for m in MESES24[6:]}            # só 18 meses
    idx, flat = indices_sazonais(
        {"OSCILA": quase_zero, "PICO": pico, "CURTA": curta}, MESES24)
    assert sorted(flat) == ["CURTA", "OSCILA", "PICO"]
    for linha in ("OSCILA", "PICO", "CURTA"):
        assert all(v == 1.0 for v in idx[linha].values())


def test_derivar_semestre_nivel_x_indice_x_fator():
    hist = {"1|100": {m: 100.0 for m in MESES6}}       # nível = 600/6 = 100
    indices = {"CUSTO VARIAVEL": {m: (0.6 if m == 12 else 1.0) for m in range(1, 13)}}
    mapa = {"1|100": "CUSTO VARIAVEL"}
    linhas = derivar_semestre(hist, MESES6, indices, mapa, 0.0)
    por_mes = {l["mes"]: l for l in linhas if l["conta"] == "1|100"}
    assert len(por_mes) == 12
    assert por_mes[12]["valor_baseline"] == 60.0        # 100 × 0,6
    assert por_mes[3]["valor_baseline"] == 100.0
    assert all(l["origem"] == "semestre" for l in por_mes.values())
    assert all(l["meses_com_dado"] == 6 for l in por_mes.values())
    com_fator = derivar_semestre(hist, MESES6, indices, mapa, -0.10)
    assert {l["mes"]: l for l in com_fator}[12]["valor_baseline"] == 54.0


def test_derivar_semestre_conta_sem_movimento_e_linha_sem_indice():
    hist = {"7|700": {}, "1|100": {"2026-02": 300.0}}   # nível 1|100 = 50
    linhas = derivar_semestre(hist, MESES6, {}, {"1|100": "LINHA X", "7|700": "LINHA X"}, 0.0)
    por_conta = {}
    for l in linhas:
        por_conta.setdefault(l["conta"], []).append(l)
    assert all(l["origem"] == "sem_base" and l["valor_baseline"] == 0.0
               for l in por_conta["7|700"])
    # linha sem índice calculado -> flat (índice 1): todos os meses = nível
    assert all(l["valor_baseline"] == 50.0 for l in por_conta["1|100"])
    assert all(l["meses_com_dado"] == 1 for l in por_conta["1|100"])


def test_derivar_semestre_esporadica_diluida_sem_mediana():
    """Sem corte de recorrência: 1 mês de 600 no semestre vira nível 100 em
    todos os meses — o total anual (~1200 com índice flat) é 2× o semestre."""
    hist = {"9|900": {"2026-04": 600.0}}
    linhas = derivar_semestre(hist, MESES6, {}, {"9|900": None}, 0.0)
    assert sum(l["valor_baseline"] for l in linhas) == 1200.0
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run --with pytest python -m pytest tests/orcamento/test_derivacao.py -q` → FAIL (import).
- [ ] **Step 3: Implementar em `api/orcamento/derivacao.py`** (append; módulo segue puro):

```python
INDICE_MIN, INDICE_MAX = 0.0, 3.0


def indices_sazonais(serie_linha: dict[str, dict[str, float]],
                     meses24: list[str]) -> tuple[dict[str, dict[int, float]], list[str]]:
    """Índice sazonal por linha da DRE: média do mês-calendário ÷ média geral,
    renormalizado para média 1. Linha sem massa, com índice fora de [0,3] ou
    com menos de 24 meses de dado vira FLAT (índice 1) e entra em linhas_flat —
    forma sem sentido econômico não pode moldar orçamento."""
    flat_ = {m: 1.0 for m in range(1, 13)}
    indices: dict[str, dict[int, float]] = {}
    linhas_flat: list[str] = []
    for linha, serie in serie_linha.items():
        valores = [serie.get(m) for m in meses24]
        if any(v is None for v in valores):
            indices[linha] = dict(flat_)
            linhas_flat.append(linha)
            continue
        media_geral = sum(valores) / len(valores)
        if abs(media_geral) < 1e-9:
            indices[linha] = dict(flat_)
            linhas_flat.append(linha)
            continue
        soma_cal: dict[int, float] = {m: 0.0 for m in range(1, 13)}
        n_cal: dict[int, int] = {m: 0 for m in range(1, 13)}
        for m, v in zip(meses24, valores):
            cal = int(m[5:7])
            soma_cal[cal] += v
            n_cal[cal] += 1
        bruto = {m: (soma_cal[m] / n_cal[m]) / media_geral for m in range(1, 13)}
        media_idx = sum(bruto.values()) / 12
        norm = {m: v / media_idx for m, v in bruto.items()} if media_idx else bruto
        if any(not (INDICE_MIN <= v <= INDICE_MAX) for v in norm.values()):
            indices[linha] = dict(flat_)
            linhas_flat.append(linha)
            continue
        indices[linha] = norm
    return indices, sorted(linhas_flat)


def derivar_semestre(historico: dict[str, dict[str, float]],
                     meses_base: list[str],
                     indices: dict[str, dict[int, float]],
                     mapa_linha: dict[str, str | None],
                     fator: float) -> list[dict]:
    """Nível do semestre (soma/6) × índice sazonal da LINHA × (1+fator).
    Sem corte de recorrência: a média semestral já dilui a conta esporádica e a
    forma vem da linha, não da conta. Conta sem movimento -> sem_base 12×0."""
    linhas: list[dict] = []
    for conta, serie in sorted(historico.items()):
        com_dado = {m: v for m, v in serie.items() if m in meses_base and v}
        nivel = sum(com_dado.values()) / len(meses_base)
        rot = mapa_linha.get(conta)
        idx = indices.get(rot) if rot else None
        for mes in range(1, 13):
            if not com_dado:
                valor, origem = 0.0, "sem_base"
            else:
                fator_mes = idx.get(mes, 1.0) if idx else 1.0
                valor, origem = nivel * fator_mes * (1 + fator), "semestre"
            linhas.append({
                "conta": conta,
                "mes": mes,
                "valor_baseline": round(valor, 2),
                "origem": origem,
                "meses_com_dado": len(com_dado),
            })
    return linhas
```

- [ ] **Step 4: Suíte inteira verde** (193 + 5 novos). `ast.parse` antes de gravar.
- [ ] **Step 5: Commit** — `git commit -m "Orçamento: índices sazonais por linha e derivação semestre × sazonalidade (puros)"`

---

### Task 2: Persistência do método + serviço + endpoint

**Files:**
- Modify: `api/orcamento/armazenamento.py` (coluna `metodo`), `api/orcamento/servico.py` (gerar/regerar), `api/main.py` (validação)
- Test: `tests/orcamento/test_armazenamento.py`, `tests/orcamento/test_servico.py` (append)

**Interfaces:**
- Consumes: `indices_sazonais`/`derivar_semestre` (Task 1); `HIST_CONTA_SQL`, `meses_fechados`, `mapa_conta_linha`, `ler_ajustes` (existentes).
- Produces:
  - `orc_versao.metodo` TEXT default `'espelho'` (migração no `init_db` copiando o padrão da coluna `meses_base` — PRAGMA table_info + ALTER TABLE; `criar_versao(..., metodo="espelho")` e `atualizar_versao(..., metodo=None)` que NÃO altera método quando None).
  - `servico.gerar(ano, rotulo, fator, quem, path=None, hoje=None, versao_id=None, metodo="espelho")`:
    - `metodo="espelho"`: caminho ATUAL, intocado (base 12 meses, `derivar`).
    - `metodo="semestre"`: base = `meses_fechados(hoje, 6)` com o MESMO bloqueio de base incompleta; índices de `_historico(meses_fechados(hoje, 24))` agregado por linha via `mapa_conta_linha`; deriva com `derivar_semestre`; resposta ganha `"linhas_flat"`.
    - **Regerar (`versao_id`)**: IGNORA o parâmetro `metodo` e usa o GRAVADO na versão (ler de `listar_versoes`); re-deriva com a base ATUAL do método (rolante); `meses_base` e `metodo` regravados coerentes.
    - Resposta sempre inclui `"metodo"`.
  - `POST /api/controladoria/orcamento/gerar`: aceita `"metodo"`; valor fora de {"espelho","semestre"} → 422 `{"erro":"parametro_invalido","mensagem":"Método de derivação inválido: use 'espelho' ou 'semestre'."}`.
  - Agregação por linha para os índices (no serviço): `_serie_por_linha(hist24, mapa) -> dict[linha, dict[mes, float]]` somando as contas de cada linha por mês (conta sem linha fica fora).

- [ ] **Step 1: Testes.** Em `test_armazenamento.py`: migração adiciona `metodo` a banco velho (criar DB sem a coluna via SQL manual, rodar `init_db`, PRAGMA confirma; `criar_versao` grava metodo e `listar_versoes` devolve). Em `test_servico.py` (padrão dos testes existentes — monkeypatch em `SNAP... `arm.DB_PATH`, `svc.ler_ajustes`, `svc.db.query`):

```python
def test_gerar_semestre_deriva_nivel_x_indice(tmp_path, monkeypatch):
    """fake_query devolve: HIST 6m p/ a conta (600 no total) e HIST 24m p/ os
    índices (linha com dez=40/resto=100 => índice dez=40/95). Confere dez orçado."""

def test_gerar_semestre_bloqueia_base_incompleta(tmp_path, monkeypatch):
    """5 dos 6 meses com dado -> ValueError com o mês faltante na mensagem."""

def test_gerar_espelho_continua_identico(tmp_path, monkeypatch):
    """REGRESSÃO: gerar(metodo='espelho') e gerar() sem metodo produzem as
    MESMAS linhas que hoje (fake 12m; comparar com o resultado esperado do
    espelho para 2-3 contas, incluindo uma esporádica pela mediana)."""

def test_regerar_usa_metodo_gravado_e_preserva_ajuste(tmp_path, monkeypatch):
    """Gera com metodo='semestre'; ajusta uma célula; regerar SEM metodo (ou
    com metodo='espelho' no body — deve ser ignorado) mantém metodo='semestre',
    re-deriva pela base semestral e o ajuste sobrevive."""

def test_resposta_traz_metodo_e_linhas_flat(tmp_path, monkeypatch): ...
```

  (Escrever os corpos completos seguindo a mecânica dos testes vizinhos; o fake_query diferencia as janelas pelo parâmetro `de` — 6m vs 24m.)
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar** armazenamento → serviço → endpoint. No serviço, o histórico de 24 meses reusa `_historico(meses)` existente com `meses_fechados(hoje, 24)`. Conferir `uv run python -c "from api import main"`.
- [ ] **Step 4: Suíte inteira verde.**
- [ ] **Step 5: Commit** — `git commit -m "Orçamento: método semestre × sazonalidade com coluna metodo e regerar coerente"`

---

### Task 3: Conversão competência → caixa (pura)

**Files:**
- Create: `api/orcamento/caixa.py`
- Test: `tests/orcamento/test_caixa.py` (novo)

**Interfaces:**
- Consumes: `armazenamento.listar_versoes/ler_linhas` (só em `provisao_do_ano`; `provisao_caixa` é 100% pura).
- Produces:
  - `DSO_PADRAO = 49.0`, `DPO_PADRAO = 79.0`, `DIAS_MES = 30.44`.
  - `provisao_caixa(entradas: dict[int, float], saidas: dict[int, float], dso: float, dpo: float) -> dict` → `{"meses": [{"mes": 1..12, "entradas": e, "saidas": s, "geracao": e+s}], "transbordo": {"entradas": x, "saidas": y}}` (12 meses sempre presentes; valores com 2 casas).
  - `provisao_do_ano(ano: int, dso: float | None, dpo: float | None, hoje, db_path=None) -> dict | None` — lê a versão mais recente do ano no SQLite (`listar_versoes(path, ano)[0]`; sem versão → None); monta `entradas/saidas` por mês somando o `valor_efetivo` positivo/negativo por conta; devolve `{"versao": {"id","rotulo","metodo"}, "dso", "dpo", "dso_fonte": "medido"|"padrao", "meses": [só meses >= hoje.month], "transbordo": {...}}`. `dso=None` → usa `DSO_PADRAO` e `dso_fonte="padrao"` (idem dpo — fonte é "padrao" se QUALQUER um caiu no padrão).

- [ ] **Step 1: Testes (`tests/orcamento/test_caixa.py`):**

```python
from datetime import date

from api.orcamento.caixa import DIAS_MES, provisao_caixa, provisao_do_ano


def test_split_fracionario_dso_49():
    """49d -> x=1,6097: 39,03% em M+1 e 60,97% em M+2 (recomputável à mão)."""
    r = provisao_caixa({8: 1000.0}, {}, dso=49.0, dpo=79.0)
    por_mes = {m["mes"]: m for m in r["meses"]}
    x = 49.0 / DIAS_MES
    f = x - int(x)
    assert abs(por_mes[9]["entradas"] - round(1000 * (1 - f), 2)) < 0.01
    assert abs(por_mes[10]["entradas"] - round(1000 * f, 2)) < 0.01
    assert por_mes[8]["entradas"] == 0.0


def test_dpo_79_cai_entre_m2_e_m3():
    r = provisao_caixa({}, {8: -1000.0}, dso=49.0, dpo=79.0)
    por_mes = {m["mes"]: m for m in r["meses"]}
    x = 79.0 / DIAS_MES
    f = x - int(x)
    assert abs(por_mes[10]["saidas"] - round(-1000 * (1 - f), 2)) < 0.01
    assert abs(por_mes[11]["saidas"] - round(-1000 * f, 2)) < 0.01


def test_transbordo_alem_de_dezembro():
    r = provisao_caixa({12: 1000.0}, {12: -500.0}, dso=49.0, dpo=79.0)
    assert all(m["entradas"] == 0.0 for m in r["meses"])          # tudo cai em jan+/fev+
    assert abs(r["transbordo"]["entradas"] - 1000.0) < 0.01
    assert abs(r["transbordo"]["saidas"] + 500.0) < 0.01


def test_dso_zero_paga_no_proprio_mes():
    r = provisao_caixa({5: 100.0}, {5: -40.0}, dso=0.0, dpo=0.0)
    m5 = next(m for m in r["meses"] if m["mes"] == 5)
    assert m5["entradas"] == 100.0 and m5["saidas"] == -40.0 and m5["geracao"] == 60.0


def test_provisao_do_ano_le_sqlite_e_fallback(tmp_path):
    from api.orcamento import armazenamento as arm
    arm.init_db(tmp_path / "o.db")
    vid = arm.criar_versao(tmp_path / "o.db", 2026, "teste", 0.0, "t")
    arm.gravar_baseline(tmp_path / "o.db", vid, [
        {"conta": "1|1", "mes": 8, "valor_baseline": 1000.0, "origem": "semestre", "meses_com_dado": 6},
        {"conta": "1|2", "mes": 8, "valor_baseline": -400.0, "origem": "semestre", "meses_com_dado": 6},
    ])
    r = provisao_do_ano(2026, None, None, hoje=date(2026, 7, 27), db_path=tmp_path / "o.db")
    assert r["dso"] == 49.0 and r["dso_fonte"] == "padrao"
    assert r["versao"]["id"] == vid
    assert all(m["mes"] >= 7 for m in r["meses"])                 # só meses >= corrente
    assert provisao_do_ano(2027, 49, 79, hoje=date(2026, 7, 27),
                           db_path=tmp_path / "o.db") is None     # sem versão do ano
```

  (Incluir também um teste de que `valor_efetivo` — ajuste manual via
  `arm.ajustar` — é o que entra na provisão, não o baseline.)
- [ ] **Step 2: Ver falhar; Step 3: implementar `api/orcamento/caixa.py`; Step 4: suíte verde; Step 5: commit** — `git commit -m "Orçamento: conversão competência → caixa com deslocamento DSO/DPO fracionário"`

---

### Task 4: `get_fluxo` anexa a provisão

**Files:**
- Modify: `api/queries.py` (função `get_fluxo`, logo após o cálculo de `kpis["dso_3m"]/["dpo_3m"]` ~linha 423)
- Test: `tests/orcamento/test_caixa.py` (append — a lógica testável já está na Task 3; aqui é só o encaixe)

**Interfaces:**
- Consumes: `provisao_do_ano` (Task 3), `kpis["dso_3m"]`/`kpis["dpo_3m"]` já calculados.
- Produces: chave `"provisao_orc"` no retorno do `get_fluxo` (shape da Task 3, com `dso_fonte`), presente só quando há versão do ano corrente e nada falhou.

- [ ] **Step 1:** No `get_fluxo`, após os KPIs de ciclo:

```python
    # Provisão orçamentária de caixa: orçado (competência) deslocado por DSO/DPO
    # reais. Qualquer falha aqui NÃO pode derrubar o fluxo — o orçamento é
    # SQLite local e opcional.
    try:
        from api.orcamento.caixa import provisao_do_ano
        provisao = provisao_do_ano(dref.year, kpis.get("dso_3m"), kpis.get("dpo_3m"),
                                   hoje=dref)
    except Exception:  # noqa: BLE001
        provisao = None
```

  e no `return`, `**({"provisao_orc": provisao} if provisao else {})`.
- [ ] **Step 2:** Teste de encaixe: como `get_fluxo` exige Postgres, o teste fica na camada da Task 3 (já cobre presença/ausência de versão). Validar o import: `uv run python -c "from api import queries"`.
- [ ] **Step 3: Suíte verde; Step 4: Commit** — `git commit -m "Fluxo: série de provisão orçamentária (competência → caixa) anexada ao get_fluxo"`

---

### Task 5: Front — Montagem (método) + Fluxo (série)

**Files:**
- Modify: `api/static/index.html`

**Interfaces:**
- Consumes: POST /gerar com `"metodo"`; resposta com `metodo`/`linhas_flat`; `d.provisao_orc` no fluxo; `d.versao.metodo`/`meses_base` no orçamento.
- Produces: UI completa.

**Montagem (funções `renderOrcMontagem`/`orcGerar`/`renderOrcGrade` — grep pelos nomes):**

- [ ] **Step 1:** Select `id="fOrcMetodo"` no card "Gerar baseline", antes do campo de ano:
  `<option value="espelho">Mês espelho (12 meses)</option><option value="semestre">Semestre × sazonalidade (últimos 6 meses)</option>`.
  Ao trocar, o texto do banner explicativo do card alterna (espelho: texto atual; semestre: "O baseline parte do NÍVEL médio dos últimos 6 meses fechados, com a FORMA de cada mês vinda da sazonalidade histórica da linha da DRE (24 meses). Regerar não apaga ajuste manual."). Valor default = método da versão carregada (`ver.metodo || 'espelho'`); o form de REGERAR não envia método (o back usa o gravado) — deixar o select desabilitado quando a intenção é regerar? Não: o select vale para "Gerar nova versão"; um `hint` ao lado diz "Regerar mantém o método da versão".
- [ ] **Step 2:** `orcGerar()` envia `metodo` no body (só quando NÃO é regeração); rótulo default vira `'Orçamento '+ano+(metodo==='semestre'?' — base '+_orcRotuloBase():'')` onde `_orcRotuloBase()` formata os últimos 6 meses fechados como `"jan–jun/26"` (helper JS local, meses pt-BR abreviados). Mensagem pós-geração inclui `linhas_flat` quando houver: `' · N linha(s) sem forma sazonal (flat): '+d.linhas_flat.join(', ')`.
- [ ] **Step 3:** Grade (`renderOrcGrade`): badge por origem —
  `mediana`→"base fraca" (atual); `semestre`→badge neutra `b-info`-like com texto `base ${_orcRotuloBaseDe(d.versao.meses_base)}` (ex.: "base jan–jun/26"; title: "nível médio do semestre × sazonalidade da linha"); **"base fraca" também quando `origem==='semestre' && meses_com_dado<3`** (badge extra). A regra atual `fraca = origem !== 'espelho'` precisa mudar para: `fraca = origem==='mediana' || origem==='sem_base' || (origem==='semestre' && c.meses_com_dado<3)`.
- [ ] **Step 4:** `node --check` + Playwright local: gerar nova versão semestre NÃO é possível sem túnel (precisa do Postgres) — validar a UI no estado atual (select aparece, banner troca, regressão visual da grade da versão espelho existente).

**Fluxo (função `chartFluxo` ~linha 3930 e o card correspondente):**

- [ ] **Step 5:** Série "provisão orçamentária": linha TRACEJADA laranja (`stroke-dasharray="5 4"`, cor resolvida DENTRO da função via `CC`/var `--orange-500`) plotando `geracao` por mês de `d.provisao_orc.meses`, alinhada às colunas do fluxo pelo mês (`fluxo[i].periodo` — conferir o formato do campo com grep antes; meses do fluxo sem provisão não desenham ponto). Legenda curta no card. Tooltip (padrão `<title>` da série existente): "Orçado: entradas R$ X · saídas R$ Y · geração R$ Z" + linha de transbordo quando `d.provisao_orc.transbordo` tiver valor.
- [ ] **Step 6:** ⓘ do card do fluxo ganha, quando a série existe: `Provisão da versão "{rotulo}" do orçamento · competência deslocada por DSO {dso}d / DPO {dpo}d ({dso_fonte==='medido'?'medidos':'padrão'}) · impostos e folha têm prazos próprios — não modelados`. Sem `provisao_orc`, nada muda na tela.
- [ ] **Step 7:** `node --check`; Playwright no fluxo local (o túnel pode estar fora — nesse caso o fluxo nem carrega dados do ERP; validar então só sintaxe + estrutura, registrando a pendência).
- [ ] **Step 8:** estrutura.py (33 telas) + suíte pytest.
- [ ] **Step 9: Commit** — `git commit -m "Orçamento/Fluxo: UI do método semestre e série de provisão orçamentária"`

---

### Task 6: Validação ponta a ponta (best-effort com o túnel)

**Files:** nenhum novo (ajustes se a validação achar defeito).

- [ ] **Step 1:** `nc -z 127.0.0.1 15432` — decide o caminho:
  - **Túnel OK:** subir servidor local :8099; gerar de verdade "Orçamento 2026 — base jan–jun/26" (`metodo=semestre`, fator 0); conferir à mão 1 conta recorrente (nível×índice), dezembro < média nas linhas com queda histórica; regerar preserva ajuste; abrir o Fluxo e ver a série tracejada com a defasagem (receita de ago → set/out); screenshots de ambas as telas.
  - **Túnel FORA:** rodar a suíte inteira + estrutura + validar o Fluxo com a versão espelho local existente (a série de provisão funciona com QUALQUER versão — o SQLite está local); registrar no relatório que a geração semestral real fica pendente do túnel, com o comando exato para rodar depois.
- [ ] **Step 2:** Aceites 1–7 da spec, um a um, marcando o que ficou pendente de túnel.
- [ ] **Step 3:** Commit final se houver ajuste.

---

## Self-review (do plano)

- **Cobertura da spec:** §1 regra/índices/guardas→T1; persistência/API/regerar rolante→T2; badge/base fraca/aviso flat→T5; §2 caixa puro/fallback/transbordo→T3; get_fluxo→T4; tela do fluxo/ⓘ→T5; erros→T2/T3/T4; aceites→T6. Fora de escopo respeitado.
- **Placeholders:** T2 Step 1 lista os testes por nome com comportamento definido (mecânica idêntica aos vizinhos do arquivo — decisão consciente); T3 tem os corpos completos.
- **Consistência de tipos:** `derivar_semestre` devolve as mesmas chaves do `derivar` (o `gravar_baseline`/grade consomem sem mudança); `provisao_do_ano` shape idêntico entre T3/T4/T5; `metodo` default `'espelho'` em todas as camadas.
- **Nota:** `_serie_por_linha` (T2) é agregação simples de 6 linhas cuja assinatura e semântica estão no bloco Interfaces — único trecho sem código literal, decisão consciente.
