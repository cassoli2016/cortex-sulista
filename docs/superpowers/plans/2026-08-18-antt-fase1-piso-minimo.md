# ANTT Fase 1 — Piso Mínimo de Frete (compra) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Conferir cada viagem paga a agregado/terceiro contra o piso mínimo legal da ANTT, numa tela nova `#anpiso`, apontando quanto a Sulista pagou abaixo do piso e para quem.

**Architecture:** Cálculo local, sem API externa. Os coeficientes das resoluções vivem em YAML versionado por vigência; a base de viagens é `programacaoembarque`, a mesma já validada na tela Agregados. O piso é uma coluna derivada sobre essa base, não uma fonte nova. Dado nosso (nenhum, nesta fase) seguiria em SQLite; a Fase 1 é somente leitura.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3 (PG 9.3 read-only), PyYAML, pytest, SPA vanilla JS em `api/static/index.html`.

**Spec:** `docs/superpowers/specs/2026-08-18-antt-design.md`

## Global Constraints

- **PG 9.3**: proibido `FILTER (WHERE ...)`. `LATERAL` existe no 9.3, mas o padrão da casa evita — siga o teste de guarda de `tests/previsao/test_sql.py`.
- **LATIN-1**: todo SQL precisa passar em `sql.encode("latin-1")`. Sem travessão, sem seta, sem aspa curva dentro de string SQL.
- **Nunca inventar número**: viagem sem eixo, sem tipo de carga ou sem km mostra `—` e entra no denominador de cobertura. O KPI declara "conferido em X de Y".
- **Vigência histórica**: o coeficiente é o da data da viagem (`dtemissao`), nunca o de hoje.
- **Sem PII**: nenhum CPF gravado, logado ou exibido.
- **Sem credencial nova**: nenhuma variável de ambiente, nenhum segredo, nenhuma API paga.
- **Rodar a suíte**: `uv sync --group test` uma vez; depois `uv run pytest tests/antt/ -v`.
- **Versão corrente**: 0.3.0 em `pyproject.toml` e no topo de `docs/versoes.yaml` — esta entrega sobe para 0.4.0.

---

### Task 1: Coeficientes da ANTT em YAML, resolvidos por vigência

O arquivo de coeficientes é o dado mais delicado da fase: um número errado acusa um transportador de pagar abaixo do piso quando ele não pagou. Por isso a transcrição é conferida contra a calculadora oficial, nunca contra blog — durante o levantamento, uma fonte de terceiros publicou CC de R$ 782,50 para carga geral 2 eixos, quando o texto oficial diz R$ 451,84.

**Files:**
- Create: `config/antt_coeficientes.yaml`
- Create: `api/antt/__init__.py`
- Create: `api/antt/coeficientes.py`
- Test: `tests/antt/__init__.py`, `tests/antt/test_coeficientes.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `carregar(path: Path | None = None) -> dict` — YAML cru, com cache de módulo.
  - `coeficiente(tipo_carga: str, eixos: int, quando: date, tabela: str = "A") -> dict | None` — devolve `{"ccd": float, "cc": float, "resolucao": str}` ou `None` quando a combinação não existe.
  - `TIPOS_CARGA: tuple[str, ...]` — as 12 classes.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_coeficientes.py
"""Coeficientes ANTT: vigência por data e combinações inexistentes."""
from __future__ import annotations

from datetime import date

from api.antt.coeficientes import TIPOS_CARGA, coeficiente


def test_carga_geral_2_eixos_na_vigencia_de_janeiro():
    c = coeficiente("carga_geral", 2, date(2026, 3, 15))
    assert c["ccd"] == 3.6815
    assert c["cc"] == 436.39
    assert c["resolucao"] == "6.076/2026"


def test_mesma_carga_na_vigencia_de_julho_usa_a_tabela_nova():
    c = coeficiente("carga_geral", 2, date(2026, 8, 1))
    assert c["ccd"] == 3.9826
    assert c["cc"] == 451.84
    assert c["resolucao"] == "6.084/2026"


def test_reajuste_do_cc_confere_com_os_3_54_por_cento_anunciados():
    velho = coeficiente("carga_geral", 2, date(2026, 3, 15))["cc"]
    novo = coeficiente("carga_geral", 2, date(2026, 8, 1))["cc"]
    assert abs(novo - velho * 1.0354) < 0.01


def test_combinacao_inexistente_devolve_none_em_vez_de_zero():
    # conteinerizada não tem linha de 9 eixos na Tabela A
    assert coeficiente("conteinerizada", 9, date(2026, 8, 1)) is None


def test_data_anterior_a_qualquer_vigencia_devolve_none():
    assert coeficiente("carga_geral", 2, date(2019, 1, 1)) is None


def test_as_doze_classes_estao_declaradas():
    assert len(TIPOS_CARGA) == 12
    assert "carga_geral" in TIPOS_CARGA
    assert "perigosa_granel_liquido" in TIPOS_CARGA
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_coeficientes.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.antt'`

- [ ] **Step 3: Criar o YAML com as duas vigências**

Transcreva o Anexo II das duas resoluções. Comece pela Tabela A (composição veicular), que é a usada no cálculo automático; a Tabela B entra no mesmo formato, sob a chave `B`. Estrutura:

```yaml
# config/antt_coeficientes.yaml
# Coeficientes dos pisos mínimos — Política Nacional de Pisos Mínimos (Lei 13.703/2018).
# Fonte: Anexo II da Res. ANTT 5.867/2020, na redação vigente de cada período.
# CCD em R$/km, CC em R$. NÃO editar sem conferir contra calculadorafrete.antt.gov.br.
# Tabela A = contratação da composição veicular. Tabela B = só a unidade de tração.
vigencias:
  - resolucao: "6.076/2026"
    inicio: 2026-01-20
    fim: 2026-07-16
    tabelas:
      A:
        carga_geral:
          2: {ccd: 3.6815, cc: 436.39}
          3: {ccd: 4.7062, cc: 523.33}
          4: {ccd: 5.3386, cc: 568.72}
          5: {ccd: 6.1604, cc: 635.08}
          6: {ccd: 6.7774, cc: 648.95}
          7: {ccd: 7.4902, cc: 803.22}
          9: {ccd: 8.5104, cc: 872.44}
        granel_solido:
          2: {ccd: 3.7123, cc: 444.84}
          3: {ccd: 4.7427, cc: 533.36}
          4: {ccd: 5.3672, cc: 576.59}
          5: {ccd: 6.1859, cc: 642.10}
          6: {ccd: 6.8058, cc: 656.76}
          7: {ccd: 7.4505, cc: 792.30}
          9: {ccd: 8.5300, cc: 877.83}
        granel_liquido:
          2: {ccd: 3.7837, cc: 455.84}
          3: {ccd: 4.8350, cc: 550.10}
          4: {ccd: 5.5162, cc: 600.27}
          5: {ccd: 6.3480, cc: 669.38}
          6: {ccd: 6.9730, cc: 685.45}
          7: {ccd: 7.5842, cc: 811.76}
          9: {ccd: 8.6837, cc: 902.80}
        frigorificada:
          2: {ccd: 4.3423, cc: 502.29}
          3: {ccd: 5.5387, cc: 601.96}
          4: {ccd: 6.3226, cc: 663.16}
          5: {ccd: 7.2435, cc: 732.07}
          6: {ccd: 7.9625, cc: 745.94}
          7: {ccd: 8.8534, cc: 949.16}
          9: {ccd: 10.0426, cc: 1030.58}
        conteinerizada:
          2: {ccd: 4.7164, cc: 526.13}
          3: {ccd: 5.2975, cc: 557.42}
          4: {ccd: 6.1243, cc: 625.16}
          5: {ccd: 6.7426, cc: 639.38}
          6: {ccd: 7.4482, cc: 791.67}
          7: {ccd: 8.4497, cc: 855.76}
        neogranel:
          2: {ccd: 3.3488, cc: 436.39}
          3: {ccd: 4.7048, cc: 522.93}
          4: {ccd: 5.3649, cc: 575.96}
          5: {ccd: 6.1604, cc: 635.08}
          6: {ccd: 6.7774, cc: 648.95}
          7: {ccd: 7.4902, cc: 803.22}
          9: {ccd: 8.5104, cc: 872.44}
        # perigosa_granel_solido, perigosa_granel_liquido, perigosa_frigorificada,
        # perigosa_conteinerizada, perigosa_carga_geral, granel_pressurizada:
        # transcrever do mesmo Anexo II, mesma estrutura.
  - resolucao: "6.084/2026"
    inicio: 2026-07-17
    fim: null
    tabelas:
      A:
        carga_geral:
          2: {ccd: 3.9826, cc: 451.84}
          3: {ccd: 5.0977, cc: 541.86}
          4: {ccd: 5.7822, cc: 588.86}
          5: {ccd: 6.6718, cc: 657.56}
          6: {ccd: 7.3547, cc: 671.93}
          7: {ccd: 8.0927, cc: 831.66}
          9: {ccd: 9.2027, cc: 903.32}
        granel_solido:
          2: {ccd: 4.0144, cc: 460.59}
          3: {ccd: 5.1355, cc: 552.24}
          4: {ccd: 5.8118, cc: 597.00}
          5: {ccd: 6.6983, cc: 664.83}
          6: {ccd: 7.3841, cc: 680.01}
          7: {ccd: 8.0516, cc: 820.34}
          9: {ccd: 9.2231, cc: 908.91}
        # demais tipos: transcrever do Anexo II da Res. 6.084/2026.
```

Os valores de carga geral e granel sólido da vigência de julho vieram do texto oficial em `anttlegis.antt.gov.br`; os de janeiro, do texto da Res. 6.076/2026. Os demais tipos precisam ser transcritos antes do Step 8.

- [ ] **Step 4: Implementar o carregador**

```python
# api/antt/coeficientes.py
"""Coeficientes dos pisos mínimos da ANTT, resolvidos pela vigência da viagem.

A tabela muda duas vezes por ano. Conferir um acerto de março contra a tabela de
agosto reescreveria todo período fechado a cada reajuste — por isso a busca é
sempre pela data do fato, nunca pela data de hoje.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
YAML_PATH = ROOT / "config" / "antt_coeficientes.yaml"

TIPOS_CARGA: tuple[str, ...] = (
    "granel_solido", "granel_liquido", "frigorificada", "conteinerizada",
    "carga_geral", "neogranel", "perigosa_granel_solido",
    "perigosa_granel_liquido", "perigosa_frigorificada",
    "perigosa_conteinerizada", "perigosa_carga_geral", "granel_pressurizada",
)


@lru_cache(maxsize=1)
def carregar(path: Path | None = None) -> dict:
    p = path or YAML_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _vigencia(quando: date, dados: dict) -> dict | None:
    for v in dados.get("vigencias", []):
        inicio, fim = v["inicio"], v.get("fim")
        if quando >= inicio and (fim is None or quando <= fim):
            return v
    return None


def coeficiente(tipo_carga: str, eixos: int, quando: date,
                tabela: str = "A") -> dict | None:
    """CCD e CC vigentes na data, ou None se a combinação não existe.

    None é resposta legítima: a Tabela A não tem linha para toda combinação de
    carga e eixo (célula vazia = não usada no mercado). Quem chama trata como
    'não calculável', nunca como zero.
    """
    v = _vigencia(quando, carregar())
    if v is None:
        return None
    linha = v["tabelas"].get(tabela, {}).get(tipo_carga, {}).get(eixos)
    if not linha:
        return None
    return {"ccd": float(linha["ccd"]), "cc": float(linha["cc"]),
            "resolucao": v["resolucao"]}
```

Crie também `api/antt/__init__.py` e `tests/antt/__init__.py` vazios.

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `uv run pytest tests/antt/test_coeficientes.py -v`
Expected: PASS, 6 testes.

- [ ] **Step 6: Validar contra a calculadora oficial**

Este passo é manual e não pode ser pulado. Abra `https://calculadorafrete.antt.gov.br/`, calcule três combinações — carga geral 5 eixos a 500 km, granel sólido 6 eixos a 1.200 km, frigorificada 7 eixos a 300 km — e confira contra `(km × ccd) + cc` do YAML. Divergência acima de um centavo significa transcrição errada: corrija o YAML, não o teste.

Registre o resultado num comentário no topo do YAML, com a data da conferência.

- [ ] **Step 7: Completar os tipos de carga que faltam**

Transcreva do Anexo II de cada resolução os seis tipos ainda comentados no YAML (as cinco variantes de perigosa e a granel pressurizada), nas duas vigências, e repita a conferência do Step 6 para uma combinação de carga perigosa.

- [ ] **Step 8: Commit**

```bash
git add config/antt_coeficientes.yaml api/antt/__init__.py api/antt/coeficientes.py tests/antt/
git commit -m "feat(antt): coeficientes de piso minimo resolvidos por vigencia"
```

---

### Task 2: Cálculo do piso (função pura)

**Files:**
- Create: `api/antt/piso.py`
- Test: `tests/antt/test_piso.py`

**Interfaces:**
- Consumes: `api.antt.coeficientes.coeficiente`.
- Produces:
  - `ESTADOS: tuple[str, ...]` = `("calculado", "sem_eixos", "sem_carga", "sem_km", "sem_tabela", "isento")`
  - `calcular_piso(km: float, tipo_carga: str | None, eixos: int | None, quando: date, vazio: bool = False, vazio_obrigatorio: bool = False, tabela: str = "A") -> dict` — devolve `{"estado": str, "piso": float | None, "ccd": float | None, "cc": float | None, "resolucao": str | None}`.
  - `avaliar(pago: float, piso_calc: dict) -> dict` — acrescenta `{"gap": float | None, "abaixo": bool}`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_piso.py
"""Piso mínimo: fórmula, vazio a 92%, e os estados de não-cálculo."""
from __future__ import annotations

from datetime import date

from api.antt.piso import avaliar, calcular_piso

QUANDO = date(2026, 8, 1)  # vigência da Res. 6.084/2026


def test_formula_basica_km_vezes_ccd_mais_cc():
    r = calcular_piso(km=500.0, tipo_carga="carga_geral", eixos=2, quando=QUANDO)
    assert r["estado"] == "calculado"
    assert abs(r["piso"] - (500.0 * 3.9826 + 451.84)) < 1e-9
    assert r["resolucao"] == "6.084/2026"


def test_vazio_obrigatorio_paga_92_por_cento_do_ccd_sem_cc():
    r = calcular_piso(km=300.0, tipo_carga="conteinerizada", eixos=5,
                      quando=QUANDO, vazio=True, vazio_obrigatorio=True)
    assert r["estado"] == "calculado"
    assert abs(r["piso"] - (0.92 * r["ccd"] * 300.0)) < 1e-9
    assert r["cc"] is None  # carga e descarga não incide em deslocamento vazio


def test_vazio_sem_obrigacao_e_isento_nao_abaixo_do_piso():
    r = calcular_piso(km=300.0, tipo_carga="carga_geral", eixos=5,
                      quando=QUANDO, vazio=True, vazio_obrigatorio=False)
    assert r["estado"] == "isento"
    assert r["piso"] is None


def test_sem_eixos_nao_inventa_numero():
    r = calcular_piso(km=500.0, tipo_carga="carga_geral", eixos=None, quando=QUANDO)
    assert r["estado"] == "sem_eixos"
    assert r["piso"] is None


def test_sem_tipo_de_carga_nao_inventa_numero():
    r = calcular_piso(km=500.0, tipo_carga=None, eixos=5, quando=QUANDO)
    assert r["estado"] == "sem_carga"
    assert r["piso"] is None


def test_km_zero_e_estado_proprio():
    r = calcular_piso(km=0.0, tipo_carga="carga_geral", eixos=5, quando=QUANDO)
    assert r["estado"] == "sem_km"
    assert r["piso"] is None


def test_combinacao_fora_da_tabela_vira_sem_tabela():
    r = calcular_piso(km=100.0, tipo_carga="conteinerizada", eixos=9, quando=QUANDO)
    assert r["estado"] == "sem_tabela"
    assert r["piso"] is None


def test_viagem_antiga_usa_a_tabela_da_epoca():
    r = calcular_piso(km=500.0, tipo_carga="carga_geral", eixos=2,
                      quando=date(2026, 3, 15))
    assert r["resolucao"] == "6.076/2026"
    assert abs(r["piso"] - (500.0 * 3.6815 + 436.39)) < 1e-9


def test_avaliar_marca_abaixo_do_piso():
    calc = calcular_piso(km=500.0, tipo_carga="carga_geral", eixos=2, quando=QUANDO)
    a = avaliar(pago=1000.00, piso_calc=calc)
    assert a["abaixo"] is True
    assert abs(a["gap"] - (1000.00 - calc["piso"])) < 1e-9


def test_avaliar_nao_julga_o_que_nao_foi_calculado():
    calc = calcular_piso(km=500.0, tipo_carga=None, eixos=None, quando=QUANDO)
    a = avaliar(pago=1000.00, piso_calc=calc)
    assert a["abaixo"] is False
    assert a["gap"] is None


def test_pago_exatamente_no_piso_nao_e_abaixo():
    calc = calcular_piso(km=500.0, tipo_carga="carga_geral", eixos=2, quando=QUANDO)
    a = avaliar(pago=calc["piso"], piso_calc=calc)
    assert a["abaixo"] is False
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_piso.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.antt.piso'`

- [ ] **Step 3: Implementar**

```python
# api/antt/piso.py
"""Piso mínimo de frete por viagem — Lei 13.703/2018, Res. ANTT 5.867/2020.

piso = (distância × CCD) + CC

Deslocamento sem carga com pagamento obrigatório (contêiner e frota dedicada
por razão sanitária ou certificação) vale 92% do CCD pela distância, sem CC:
não há carga nem descarga a remunerar.

A função nunca devolve zero para dado ausente. Zero é um piso de verdade e
faria uma viagem parecer regular; ausência tem estado próprio.
"""
from __future__ import annotations

from datetime import date

from api.antt.coeficientes import coeficiente

ESTADOS: tuple[str, ...] = (
    "calculado", "sem_eixos", "sem_carga", "sem_km", "sem_tabela", "isento")

FATOR_VAZIO = 0.92


def _vazio_resultado(estado: str) -> dict:
    return {"estado": estado, "piso": None, "ccd": None, "cc": None,
            "resolucao": None}


def calcular_piso(km: float, tipo_carga: str | None, eixos: int | None,
                  quando: date, vazio: bool = False,
                  vazio_obrigatorio: bool = False, tabela: str = "A") -> dict:
    if vazio and not vazio_obrigatorio:
        return _vazio_resultado("isento")
    if not km or km <= 0:
        return _vazio_resultado("sem_km")
    if eixos is None:
        return _vazio_resultado("sem_eixos")
    if not tipo_carga:
        return _vazio_resultado("sem_carga")
    c = coeficiente(tipo_carga, eixos, quando, tabela)
    if c is None:
        return _vazio_resultado("sem_tabela")
    if vazio:
        piso = FATOR_VAZIO * c["ccd"] * km
        return {"estado": "calculado", "piso": piso, "ccd": c["ccd"],
                "cc": None, "resolucao": c["resolucao"]}
    piso = km * c["ccd"] + c["cc"]
    return {"estado": "calculado", "piso": piso, "ccd": c["ccd"],
            "cc": c["cc"], "resolucao": c["resolucao"]}


def avaliar(pago: float, piso_calc: dict) -> dict:
    """Acrescenta gap e a marca de abaixo-do-piso ao resultado do cálculo.

    Só julga o que foi calculado: viagem sem eixo mapeado não é irregular, é
    desconhecida — e acusar transportador com base em desconhecido é pior do
    que não medir.
    """
    out = dict(piso_calc)
    if piso_calc.get("piso") is None:
        out["gap"] = None
        out["abaixo"] = False
        return out
    gap = float(pago) - float(piso_calc["piso"])
    out["gap"] = gap
    out["abaixo"] = gap < 0
    return out
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/antt/test_piso.py -v`
Expected: PASS, 11 testes.

- [ ] **Step 5: Commit**

```bash
git add api/antt/piso.py tests/antt/test_piso.py
git commit -m "feat(antt): calculo do piso minimo com estados de nao-calculo"
```

---

### Task 3: Mapa de eixos e tipo de carga

O AVA não tem número de eixos. O mapa traduz o que ele tem — `descricao_tipo`, `descricao_carroceria`, `bitrem` — para o par (eixos, tipo de carga) que a tabela da ANTT exige. Veículo não resolvido não vira erro mudo: entra numa lista que a tela mostra, para virar fila de cadastro.

**Files:**
- Create: `config/antt_eixos.yaml`
- Create: `api/antt/eixos.py`
- Test: `tests/antt/test_eixos.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `resolver_eixos(tipo: str | None, carroceria: str | None, bitrem: bool) -> int | None`
  - `resolver_carga(tipo_carga_veiculo: str | None, carroceria: str | None) -> str | None`
  - `normalizar(texto: str | None) -> str` — maiúsculas, sem acento, sem espaço duplo.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_eixos.py
"""Tradução do cadastro do AVA para (eixos, tipo de carga) da tabela ANTT."""
from __future__ import annotations

from api.antt.eixos import normalizar, resolver_carga, resolver_eixos


def test_normalizar_tira_acento_e_caixa():
    assert normalizar(" Semi-Reboque Frigorífico ") == "SEMI-REBOQUE FRIGORIFICO"
    assert normalizar(None) == ""


def test_cavalo_com_semirreboque_comum_da_5_eixos():
    assert resolver_eixos("CAVALO MECANICO", "CARGA SECA", bitrem=False) == 5


def test_bitrem_da_7_eixos():
    assert resolver_eixos("CAVALO MECANICO", "CARGA SECA", bitrem=True) == 7


def test_truck_da_3_eixos():
    assert resolver_eixos("TRUCK", "CARGA SECA", bitrem=False) == 3


def test_toco_da_2_eixos():
    assert resolver_eixos("TOCO", "CARGA SECA", bitrem=False) == 2


def test_tipo_desconhecido_devolve_none():
    assert resolver_eixos("NAVE ESPACIAL", "CARGA SECA", bitrem=False) is None


def test_carroceria_frigorifica_vira_carga_frigorificada():
    assert resolver_carga(None, "FRIGORIFICO") == "frigorificada"


def test_tipo_de_carga_do_veiculo_tem_precedencia_sobre_a_carroceria():
    assert resolver_carga("GRANEL SOLIDO", "CARGA SECA") == "granel_solido"


def test_carga_seca_cai_no_default_carga_geral():
    assert resolver_carga(None, "CARGA SECA") == "carga_geral"


def test_sem_nenhuma_informacao_devolve_none():
    assert resolver_carga(None, None) is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_eixos.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.antt.eixos'`

- [ ] **Step 3: Criar o YAML**

```yaml
# config/antt_eixos.yaml
# Traduz o cadastro de veículo do AVA para o que a tabela da ANTT exige.
# O AVA não guarda número de eixos — este mapa é a ponte, e é revisável pelo
# negócio. Chave comparada já normalizada (maiúscula, sem acento).
#
# eixos: combinação de unidade de tração + implemento.
eixos:
  por_tipo:
    "TOCO": 2
    "TRUCK": 3
    "BITRUCK": 4
    "CAVALO MECANICO": 5      # cavalo + semirreboque de 3 eixos
    "CAVALO MECANICO TRUCADO": 6
    "VUC": 2
    "3/4": 2
  bitrem: 7                    # sobrepõe o tipo quando o cadastro marca bitrem
  rodotrem: 9

carga:
  # tem precedência: vem do campo descricao_tipocargaveiculo do AVA
  por_tipo_carga:
    "GRANEL SOLIDO": granel_solido
    "GRANEL LIQUIDO": granel_liquido
    "FRIGORIFICADA": frigorificada
    "CONTEINER": conteinerizada
    "CARGA GERAL": carga_geral
    "NEOGRANEL": neogranel
    "PERIGOSA": perigosa_carga_geral
  # usada quando o campo acima está vazio
  por_carroceria:
    "FRIGORIFICO": frigorificada
    "SIDER": carga_geral
    "BAU": carga_geral
    "CARGA SECA": carga_geral
    "GRANELEIRO": granel_solido
    "TANQUE": granel_liquido
    "PORTA CONTAINER": conteinerizada
```

- [ ] **Step 4: Implementar**

```python
# api/antt/eixos.py
"""Ponte entre o cadastro de veículo do AVA e a tabela de coeficientes.

O AVA descreve o veículo por tipo, carroceria e um flag de bitrem; a ANTT cobra
número de eixos e uma das 12 classes de carga. Nada aqui adivinha: o que o mapa
não conhece volta None e a tela mostra como pendência de cadastro.
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
YAML_PATH = ROOT / "config" / "antt_eixos.yaml"


@lru_cache(maxsize=1)
def _mapa(path: Path | None = None) -> dict:
    p = path or YAML_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def normalizar(texto: str | None) -> str:
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto.strip().upper())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.split())


def resolver_eixos(tipo: str | None, carroceria: str | None,
                   bitrem: bool) -> int | None:
    m = _mapa().get("eixos", {})
    if bitrem:
        return m.get("bitrem")
    return m.get("por_tipo", {}).get(normalizar(tipo))


def resolver_carga(tipo_carga_veiculo: str | None,
                   carroceria: str | None) -> str | None:
    m = _mapa().get("carga", {})
    achado = m.get("por_tipo_carga", {}).get(normalizar(tipo_carga_veiculo))
    if achado:
        return achado
    return m.get("por_carroceria", {}).get(normalizar(carroceria))
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `uv run pytest tests/antt/test_eixos.py -v`
Expected: PASS, 10 testes.

- [ ] **Step 6: Commit**

```bash
git add config/antt_eixos.yaml api/antt/eixos.py tests/antt/test_eixos.py
git commit -m "feat(antt): mapa de eixos e tipo de carga do cadastro do AVA"
```

---

### Task 4: SQL das viagens de agregado com os campos do veículo

Reusa a base já validada da tela Agregados (`_agr_base` em `api/queries.py:1092`), acrescentando os campos do veículo que o piso precisa. Não invente uma fonte nova: `programacaoembarque` com `semaforo = 1`, não cancelada, `utilizacaoveiculo IN ('AGR','TER')` é a fonte canônica do frete de compra.

**Files:**
- Create: `api/antt/sql.py`
- Test: `tests/antt/test_sql.py`

**Interfaces:**
- Consumes: nada (só monta string SQL).
- Produces:
  - `PISO_VIAGENS_SQL: str` — parâmetros nomeados `%(dt_de)s`, `%(dt_ate)s`, `%(filial)s`, `%(modalidade)s`, `%(transportador)s`. Colunas: `numero, dtemissao, codigo, transportador, placa, origem, destino, km, pago, vazio, veic_tipo, veic_carroceria, veic_bitrem, veic_tipocarga`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_sql.py
"""Guardas do SQL do piso: PG 9.3, LATIN-1 e a fonte canônica correta."""
from __future__ import annotations

from api.antt.sql import PISO_VIAGENS_SQL


def test_sem_recursos_ausentes_no_pg93():
    assert "FILTER (WHERE" not in PISO_VIAGENS_SQL.upper()


def test_somente_latin1():
    PISO_VIAGENS_SQL.encode("latin-1")


def test_usa_a_fonte_canonica_do_frete_de_compra():
    s = PISO_VIAGENS_SQL
    assert "programacaoembarque" in s
    assert "p.semaforo = 1" in s
    assert "p.dtcancelamento IS NULL" in s
    assert "v.utilizacaoveiculo IN ('AGR','TER')" in s


def test_traz_os_campos_que_o_piso_precisa():
    s = PISO_VIAGENS_SQL
    for campo in ("kmfretecompra", "valorfretecompra", "veic_tipo",
                  "veic_carroceria", "veic_bitrem", "veic_tipocarga"):
        assert campo in s


def test_marca_deslocamento_vazio_pelo_tipo_3():
    assert "(p.tipo = 3)" in PISO_VIAGENS_SQL


def test_aceita_os_filtros_da_tela():
    for p in ("%(dt_de)s", "%(dt_ate)s", "%(filial)s", "%(modalidade)s",
              "%(transportador)s"):
        assert p in PISO_VIAGENS_SQL
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_sql.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.antt.sql'`

- [ ] **Step 3: Implementar**

```python
# api/antt/sql.py
"""Viagens de agregado/terceiro com os campos de veiculo que o piso exige.

Fonte canonica do frete de compra e programacaoembarque -- a mesma da tela
Agregados (api/queries.py::_agr_base). Nao trocar por acertoviagemagregado: o
acerto e o fechamento financeiro do periodo, e o piso incide sobre o frete
contratado de cada viagem.

Sem acento neste arquivo: o SQL trafega em LATIN-1 no PG 9.3.
"""
from __future__ import annotations

PISO_VIAGENS_SQL = """
SELECT p.numero,
       to_char(p.dtemissao,'YYYY-MM-DD') AS dtemissao,
       p.cnpjcpfcodigoveiculo AS codigo,
       coalesce(nullif(trim(c.nomefantasia),''), nullif(trim(c.razaosocial),''),
                '(sem cadastro)') AS transportador,
       p.veiculo AS placa,
       coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?')
         AS origem,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?')
         AS destino,
       coalesce(p.kmfretecompra,0)::float8 AS km,
       coalesce(p.valorfretecompra,0)::float8 AS pago,
       (p.tipo = 3) AS vazio,
       tv.descricao AS veic_tipo,
       cr.descricao AS veic_carroceria,
       coalesce(v.bitrem, false) AS veic_bitrem,
       tc.descricao AS veic_tipocarga
FROM programacaoembarque p
JOIN veiculo v ON v.placa = p.veiculo AND v.utilizacaoveiculo IN ('AGR','TER')
LEFT JOIN cadastro c ON c.codigo = p.cnpjcpfcodigoveiculo
LEFT JOIN tipoveiculo tv ON tv.codigo = v.tipo
LEFT JOIN carroceria cr ON cr.codigo = v.carroceria
LEFT JOIN tipocargaveiculo tc ON tc.codigo = v.tipocargaveiculo
WHERE p.dtemissao >= %(dt_de)s::date AND p.dtemissao < %(dt_ate)s::date + 1
  AND p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.numero < 1000000
  AND (p.filial = %(filial)s OR %(filial)s::int IS NULL)
  AND (v.utilizacaoveiculo = %(modalidade)s OR %(modalidade)s::text IS NULL)
  AND (%(transportador)s::text IS NULL
       OR c.nomefantasia ILIKE '%%'||%(transportador)s||'%%'
       OR c.razaosocial ILIKE '%%'||%(transportador)s||'%%')
ORDER BY p.dtemissao DESC, p.numero DESC
"""
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/antt/test_sql.py -v`
Expected: PASS, 6 testes.

- [ ] **Step 5: Conferir os nomes reais das tabelas de apoio**

Os joins `tipoveiculo`, `carroceria` e `tipocargaveiculo` e as colunas `v.tipo`, `v.carroceria`, `v.tipocargaveiculo`, `v.bitrem` foram inferidos da query `Querys Sulista/AVACORP/OPERACAO - Veiculos (Todos).sql`, que consome a view `fnc_veiculo_gridview` e expõe `descricao_tipo`, `descricao_carroceria`, `bitrem` e `descricao_tipocargaveiculo`. Com o túnel SSH aberto, confirme os nomes reais:

```bash
scripts/db.sh -c "\d veiculo" | grep -i "tipo\|carroceria\|bitrem"
```

Se os nomes divergirem, ajuste o SQL e o teste juntos. Se o túnel não estiver disponível, pare aqui e reporte — não adivinhe nome de coluna.

- [ ] **Step 6: Commit**

```bash
git add api/antt/sql.py tests/antt/test_sql.py
git commit -m "feat(antt): sql das viagens de agregado com campos do veiculo"
```

---

### Task 5: Serviço — monta o payload da tela

**Files:**
- Create: `api/antt/servico.py`
- Test: `tests/antt/test_servico.py`

**Interfaces:**
- Consumes: `api.antt.sql.PISO_VIAGENS_SQL`, `api.antt.eixos.resolver_eixos/resolver_carga`, `api.antt.piso.calcular_piso/avaliar`.
- Produces:
  - `conferir_viagens(linhas: list[dict]) -> list[dict]` — puro, testável sem banco. Cada item ganha `eixos`, `tipo_carga`, `piso`, `gap`, `abaixo`, `estado`, `resolucao`.
  - `resumir(conferidas: list[dict]) -> dict` — KPIs.
  - `serie_mensal(conferidas: list[dict]) -> list[dict]` — `[{"mes": "AAAA-MM", "conferidas": int, "abaixo": int, "exposicao": float, "aderencia": float | None}]`, ordenada por mês.
  - `get_piso_minimo(filial, dt_de, dt_ate, modalidade, transportador) -> dict` — payload completo `{"kpis": ..., "transportadores": [...], "pendencias": [...], "dt_de": ..., "dt_ate": ..., "fonte": ...}`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_servico.py
"""Conferência e KPIs — puros, sem banco."""
from __future__ import annotations

from api.antt.servico import conferir_viagens, resumir, serie_mensal


def _linha(**kw):
    base = {"numero": 1, "dtemissao": "2026-08-01", "codigo": "T1",
            "transportador": "TRANSP UM", "placa": "AAA1A11",
            "origem": "SBC/SP", "destino": "RIO/RJ", "km": 500.0,
            "pago": 1000.0, "vazio": False, "veic_tipo": "CAVALO MECANICO",
            "veic_carroceria": "CARGA SECA", "veic_bitrem": False,
            "veic_tipocarga": "CARGA GERAL"}
    base.update(kw)
    return base


def test_viagem_completa_e_conferida_e_marcada_abaixo():
    r = conferir_viagens([_linha()])[0]
    assert r["estado"] == "calculado"
    assert r["eixos"] == 5
    assert r["tipo_carga"] == "carga_geral"
    assert r["abaixo"] is True          # 1000 < 500*6,6718 + 657,56
    assert r["gap"] < 0


def test_viagem_bem_paga_nao_e_abaixo():
    r = conferir_viagens([_linha(pago=9000.0)])[0]
    assert r["abaixo"] is False
    assert r["gap"] > 0


def test_veiculo_sem_tipo_conhecido_vira_pendencia_nao_irregular():
    r = conferir_viagens([_linha(veic_tipo="NAVE ESPACIAL")])[0]
    assert r["estado"] == "sem_eixos"
    assert r["abaixo"] is False
    assert r["piso"] is None


def test_vazio_sem_obrigacao_fica_isento():
    r = conferir_viagens([_linha(vazio=True)])[0]
    assert r["estado"] == "isento"
    assert r["abaixo"] is False


def test_resumo_declara_cobertura_e_nao_conta_isento_no_denominador():
    conferidas = conferir_viagens([
        _linha(numero=1),
        _linha(numero=2, veic_tipo="NAVE ESPACIAL"),
        _linha(numero=3, vazio=True),
    ])
    k = resumir(conferidas)
    assert k["viagens"] == 3
    assert k["conferidas"] == 1        # só a completa
    assert k["nao_conferidas"] == 1    # a sem eixos
    assert k["isentas"] == 1
    assert k["abaixo"] == 1
    assert k["exposicao"] < 0


def test_resumo_de_lista_vazia_nao_divide_por_zero():
    k = resumir([])
    assert k["viagens"] == 0
    assert k["aderencia"] is None


def test_serie_mensal_agrupa_por_competencia_e_ordena():
    conferidas = conferir_viagens([
        _linha(numero=1, dtemissao="2026-08-01"),
        _linha(numero=2, dtemissao="2026-07-15", pago=9000.0),
        _linha(numero=3, dtemissao="2026-08-20"),
    ])
    serie = serie_mensal(conferidas)
    assert [r["mes"] for r in serie] == ["2026-07", "2026-08"]
    assert serie[0]["abaixo"] == 0 and serie[0]["aderencia"] == 1.0
    assert serie[1]["abaixo"] == 2 and serie[1]["aderencia"] == 0.0


def test_serie_mensal_ignora_isento_e_nao_conferido():
    conferidas = conferir_viagens([
        _linha(numero=1, dtemissao="2026-08-01", vazio=True),
        _linha(numero=2, dtemissao="2026-08-02", veic_tipo="NAVE ESPACIAL"),
    ])
    assert serie_mensal(conferidas) == []


def test_pendencias_agrupam_o_que_falta_cadastrar():
    conferidas = conferir_viagens([
        _linha(numero=1, veic_tipo="NAVE ESPACIAL", placa="BBB2B22"),
        _linha(numero=2, veic_tipo="NAVE ESPACIAL", placa="BBB2B22"),
    ])
    k = resumir(conferidas)
    assert k["placas_pendentes"] == 1   # a mesma placa não conta duas vezes
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_servico.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.antt.servico'`

- [ ] **Step 3: Implementar**

```python
# api/antt/servico.py
"""Confere as viagens de compra contra o piso mínimo e resume para a tela.

A separação importa: conferir_viagens e resumir são puros e testáveis sem
banco; só get_piso_minimo toca no AVA.
"""
from __future__ import annotations

from datetime import date, datetime

from api import db
from api.antt.eixos import resolver_carga, resolver_eixos
from api.antt.piso import avaliar, calcular_piso
from api.antt.sql import PISO_VIAGENS_SQL

# contêiner é o caso em que o retorno vazio é obrigatório por norma; frota
# dedicada por razão sanitária depende de contrato e não está no cadastro, por
# isso não é inferida aqui.
CARGAS_VAZIO_OBRIGATORIO = frozenset({"conteinerizada", "perigosa_conteinerizada"})


def conferir_viagens(linhas: list[dict]) -> list[dict]:
    out = []
    for l in linhas:
        eixos = resolver_eixos(l.get("veic_tipo"), l.get("veic_carroceria"),
                               bool(l.get("veic_bitrem")))
        carga = resolver_carga(l.get("veic_tipocarga"), l.get("veic_carroceria"))
        quando = datetime.strptime(l["dtemissao"], "%Y-%m-%d").date()
        vazio = bool(l.get("vazio"))
        calc = calcular_piso(
            km=float(l.get("km") or 0), tipo_carga=carga, eixos=eixos,
            quando=quando, vazio=vazio,
            vazio_obrigatorio=vazio and carga in CARGAS_VAZIO_OBRIGATORIO)
        item = dict(l)
        item.update(avaliar(float(l.get("pago") or 0), calc))
        item["eixos"] = eixos
        item["tipo_carga"] = carga
        out.append(item)
    return out


def resumir(conferidas: list[dict]) -> dict:
    viagens = len(conferidas)
    calc = [c for c in conferidas if c["estado"] == "calculado"]
    isentas = [c for c in conferidas if c["estado"] == "isento"]
    pendentes = [c for c in conferidas
                 if c["estado"] not in ("calculado", "isento")]
    abaixo = [c for c in calc if c["abaixo"]]
    return {
        "viagens": viagens,
        "conferidas": len(calc),
        "isentas": len(isentas),
        "nao_conferidas": len(pendentes),
        "placas_pendentes": len({c.get("placa") for c in pendentes if c.get("placa")}),
        "pago": sum(float(c.get("pago") or 0) for c in calc),
        "piso_total": sum(float(c["piso"]) for c in calc),
        "abaixo": len(abaixo),
        "exposicao": sum(float(c["gap"]) for c in abaixo),
        "aderencia": (1 - len(abaixo) / len(calc)) if calc else None,
    }


def serie_mensal(conferidas: list[dict]) -> list[dict]:
    """Aderência mês a mês. Só entra o que foi efetivamente conferido — mês
    inteiro sem cálculo não vira ponto de 100%, some do gráfico."""
    por_mes: dict[str, dict] = {}
    for c in conferidas:
        if c["estado"] != "calculado":
            continue
        mes = c["dtemissao"][:7]
        r = por_mes.setdefault(mes, {"mes": mes, "conferidas": 0, "abaixo": 0,
                                     "exposicao": 0.0})
        r["conferidas"] += 1
        if c["abaixo"]:
            r["abaixo"] += 1
            r["exposicao"] += float(c["gap"])
    saida = []
    for mes in sorted(por_mes):
        r = por_mes[mes]
        r["aderencia"] = 1 - r["abaixo"] / r["conferidas"]
        saida.append(r)
    return saida


def get_piso_minimo(filial: int | None, dt_de: str, dt_ate: str,
                    modalidade: str | None = None,
                    transportador: str | None = None) -> dict:
    params = {"filial": filial, "dt_de": dt_de, "dt_ate": dt_ate,
              "modalidade": modalidade, "transportador": transportador}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(PISO_VIAGENS_SQL, params)
        linhas = cur.fetchall()
    conferidas = conferir_viagens([dict(l) for l in linhas])
    por_transp: dict[str, dict] = {}
    for c in conferidas:
        t = por_transp.setdefault(c["codigo"] or "(sem)", {
            "codigo": c["codigo"], "transportador": c["transportador"],
            "viagens": 0, "pago": 0.0, "abaixo": 0, "exposicao": 0.0,
            "detalhe": []})
        t["viagens"] += 1
        t["pago"] += float(c.get("pago") or 0)
        if c["abaixo"]:
            t["abaixo"] += 1
            t["exposicao"] += float(c["gap"])
        t["detalhe"].append(c)
    ordenado = sorted(por_transp.values(), key=lambda x: x["exposicao"])
    pendentes = sorted({
        (c.get("placa"), c.get("veic_tipo"), c.get("veic_carroceria"), c["estado"])
        for c in conferidas if c["estado"] not in ("calculado", "isento")})
    return {
        "kpis": resumir(conferidas),
        "mensal": serie_mensal(conferidas),
        "transportadores": ordenado,
        "pendencias": [{"placa": p, "tipo": t, "carroceria": cr, "motivo": e}
                       for p, t, cr, e in pendentes],
        "dt_de": dt_de, "dt_ate": dt_ate,
        "fonte": ("ERP AVA · programacaoembarque (frete de compra) × tabela ANTT "
                  "vigente na data da viagem · leitura"),
    }
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/antt/test_servico.py -v`
Expected: PASS, 9 testes.

- [ ] **Step 5: Commit**

```bash
git add api/antt/servico.py tests/antt/test_servico.py
git commit -m "feat(antt): servico de conferencia do piso e KPIs"
```

---

### Task 6: Endpoint e RBAC

**Files:**
- Modify: `api/main.py` (novo endpoint, junto do bloco de Suprimentos/Operação)
- Modify: `api/auth.py:48` (`TELAS`) e `api/auth.py:95` (`ROTA_TELAS`)
- Test: `tests/antt/test_endpoint.py`

**Interfaces:**
- Consumes: `api.antt.servico.get_piso_minimo`.
- Produces: `GET /api/operacao/antt/piso?filial=&dt_de=&dt_ate=&modalidade=&transportador=`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_endpoint.py
"""Contrato do endpoint e registro no RBAC."""
from __future__ import annotations

from api.auth import ROTA_TELAS, TELAS


def test_tela_registrada_no_rbac():
    assert TELAS["anpiso"] == ("Piso Mínimo de Frete", "ANTT")


def test_rota_mapeada_para_a_tela():
    achado = [telas for prefixo, telas in ROTA_TELAS
              if prefixo == "/api/operacao/antt/piso"]
    assert achado and achado[0] == frozenset({"anpiso"})


def test_rota_do_piso_vem_antes_de_prefixo_mais_generico():
    # fail-closed: prefixo mais específico primeiro, senão outra rota captura
    idx = {p: i for i, (p, _) in enumerate(ROTA_TELAS)}
    if "/api/operacao" in idx:
        assert idx["/api/operacao/antt/piso"] < idx["/api/operacao"]
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_endpoint.py -v`
Expected: FAIL com `KeyError: 'anpiso'`

- [ ] **Step 3: Registrar a tela no RBAC**

Em `api/auth.py`, no dict `TELAS`, logo depois da última linha do grupo Recursos Humanos (`"he": ("Horas Extras", "Recursos Humanos"),`):

```python
    "anpiso":  ("Piso Mínimo de Frete", "ANTT"),
```

Em `ROTA_TELAS`, junto das demais rotas específicas (antes de qualquer prefixo mais curto que possa capturá-la):

```python
    ("/api/operacao/antt/piso",       frozenset({"anpiso"})),
```

- [ ] **Step 4: Escrever o endpoint**

Em `api/main.py`, seguindo o padrão do bloco da Previsão (`api/main.py:1308`):

```python
# ---------------------------------------------------------------- ANTT — piso mínimo

@app.get("/api/operacao/antt/piso")
def antt_piso(filial: int | None = None, dt_de: str | None = None,
              dt_ate: str | None = None, modalidade: str | None = None,
              transportador: str | None = None) -> JSONResponse:
    from api.antt.servico import get_piso_minimo
    de, ate = _periodo_padrao(dt_de, dt_ate)
    if modalidade is not None and modalidade not in ("AGR", "TER"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Parâmetro modalidade inválido: use AGR ou TER."})
    try:
        return JSONResponse(get_piso_minimo(filial, de, ate, modalidade,
                                            transportador))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("antt_piso falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao conferir o piso mínimo."})
```

Antes de escrever, procure em `api/main.py` como as outras telas de período resolvem a data padrão (`grep -n "dt_de" api/main.py | head`) e use o mesmo helper — se ele tiver outro nome, use o nome real em vez de `_periodo_padrao`.

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `uv run pytest tests/antt/ -v`
Expected: PASS, toda a suíte do módulo.

- [ ] **Step 6: Subir a API e conferir a resposta real**

```bash
scripts/run_api.sh
curl -s "http://127.0.0.1:8000/api/operacao/antt/piso?dt_de=2026-07-01&dt_ate=2026-07-31" | head -c 600
```

Expected: JSON com `kpis`, `transportadores`, `pendencias`. Se vier 503, o túnel SSH está fechado — abra antes de seguir.

Confira a sanidade: `kpis.conferidas + kpis.isentas + kpis.nao_conferidas` tem que ser igual a `kpis.viagens`. Se não bater, há estado não contabilizado.

- [ ] **Step 7: Commit**

```bash
git add api/main.py api/auth.py tests/antt/test_endpoint.py
git commit -m "feat(antt): endpoint do piso minimo com registro no RBAC"
```

---

### Task 7: Tela `#anpiso` e o grupo ANTT no menu

**Files:**
- Modify: `api/static/index.html` — menu lateral (`api/static/index.html:980`), gaveta mobile (`:11418`), `qsView` (`:3029`), visibilidade de filtros (`:3200`), `DATAMAP`/`LOADMAP` (`:3242`), e a seção de views
- Test: `tests/antt/test_tela_e2e.py`

**Interfaces:**
- Consumes: `GET /api/operacao/antt/piso`.
- Produces: view `anpiso` registrada em `LOADMAP`/`DATAMAP`; funções `loadAnpiso()` e `renderAnpiso(d)`.

- [ ] **Step 1: Escrever o teste que falha**

Siga o padrão de `tests/frontend/test_doc_e2e.py` (Playwright contra o `index.html` real, sem banco).

```python
# tests/antt/test_tela_e2e.py
"""A tela existe, está no menu, no mobile e nos mapas de carga."""
from __future__ import annotations

from pathlib import Path

HTML = Path(__file__).resolve().parent.parent.parent / "api" / "static" / "index.html"


def test_menu_tem_o_grupo_antt():
    s = HTML.read_text(encoding="utf-8")
    assert 'id="grpAntt"' in s
    assert 'data-view="anpiso"' in s


def test_view_registrada_nos_mapas_de_carga():
    s = HTML.read_text(encoding="utf-8")
    assert "anpiso:loadAnpiso" in s
    assert "anpiso:DATAANPISO" in s


def test_tela_entra_na_gaveta_mobile():
    s = HTML.read_text(encoding="utf-8")
    drawer = s.split('<div class="drawer"', 1)[1]
    assert 'href="#anpiso"' in drawer


def test_filtros_da_tela_estao_no_qsview():
    s = HTML.read_text(encoding="utf-8")
    bloco = s.split("function qsView(k){", 1)[1].split("\n}", 1)[0]
    assert "k==='anpiso'" in bloco
    assert "modalidade" in bloco
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_tela_e2e.py -v`
Expected: FAIL — `assert 'id="grpAntt"' in s`

- [ ] **Step 3: Acrescentar o grupo no menu lateral**

Em `api/static/index.html`, depois do bloco `subsRh` e antes de `grpTv`:

```html
      <button class="group" id="grpAntt" aria-expanded="false" aria-controls="subsAntt" onclick="toggleGroup('grpAntt','subsAntt','cs.anttGroup')" title="ANTT">
        <span class="ic" data-ic="qualic"></span><span>ANTT</span><span class="ic chev" data-ic="chev"></span>
      </button>
      <div class="subs closed" id="subsAntt">
        <a href="#anpiso" class="sub" data-view="anpiso" title="Piso Mínimo de Frete — conferência do que se paga ao agregado"><span class="ic" data-ic="qualic"></span><span>Piso Mínimo de Frete</span></a>
      </div>
```

- [ ] **Step 4: Registrar a view nos mapas e nos filtros**

Em `qsView` (`:3029`), junto dos outros ramos:

```javascript
  } else if(k==='anpiso'){
    if(V('fFilial'))p.set('filial',V('fFilial'));
    if(V('fEmiDe'))p.set('dt_de',V('fEmiDe'));
    if(V('fEmiAte'))p.set('dt_ate',V('fEmiAte'));
    if(V('fAnpTipo'))p.set('modalidade',V('fAnpTipo'));
    if(T('fAnpTransp'))p.set('transportador',T('fAnpTransp'));
```

Em `DATAMAP` e `LOADMAP` (`:3242`), acrescente `anpiso:DATAANPISO` e `anpiso:loadAnpiso`. Declare `let DATAANPISO=null;` junto das outras globais de dados.

Na visibilidade de filtros (`:3200`), inclua `anpiso` onde `agr` já aparece: rótulo de data ("Emissão da viagem de"), `grpEmi`, `emiPresetSync()` e o grupo próprio `grpAnp` com o select de modalidade (AGR/TER) e a busca por transportador — espelhando `grpAgr`.

- [ ] **Step 5: Escrever a marcação da view**

Espelhe `view-agr` (`api/static/index.html:1533`). O `ihelp` com a fonte do dado
não é enfeite: é o padrão da casa e é o que permite auditar de onde veio o número.

```html
      <!-- ===================== PISO MÍNIMO ANTT ===================== -->
      <section class="view" id="view-anpiso">
        <div class="kpis" id="kpis-anpiso"></div>
        <div class="card">
          <div class="head"><h2>Aderência ao piso por mês <span class="ihelp" tabindex="0" role="img" aria-label="fonte do dado" title="programacaoembarque (não cancelada, semáforo = 1) dos veículos com veiculo.utilizacaoveiculo em AGR/TER, por data de emissão. Pago = valorfretecompra; distância = kmfretecompra. O piso é (km × CCD) + CC da tabela ANTT vigente NA DATA DA VIAGEM (Res. 6.076/2026 e 6.084/2026), pelo número de eixos e tipo de carga do veículo. Mês sem nenhuma viagem conferida não aparece no gráfico.">i</span></h2><span class="hint" id="hintAnpiso">só viagens conferidas</span></div>
          <div class="chartwrap" id="wrapAnpiso">
            <svg id="chartAnpiso" viewBox="0 0 960 250" preserveAspectRatio="xMidYMid meet"
                 tabindex="0" role="img" aria-label="Percentual de viagens pagas no piso mínimo ou acima, por mês. Use as setas do teclado para percorrer os meses."></svg>
            <div class="tip" id="tipAnpiso"></div>
          </div>
        </div>
        <div class="card">
          <div class="head"><h2>Transportadores do período <span class="ihelp" tabindex="0" role="img" aria-label="fonte do dado" title="Mesma fonte do gráfico, agrupada por transportador (cnpjcpfcodigoveiculo). Exposição = soma do que faltou para o piso nas viagens pagas abaixo dele. Clique na linha para ver as viagens.">i</span></h2><span class="hint" id="hintAnpisoT">ordenado por exposição · clique para ver as viagens</span></div>
          <div class="tablewrap tabroll"><table><thead><tr>
            <th style="width:34px"></th><th>Transportador</th><th class="num">Viagens</th><th class="num">Pago</th><th class="num">Abaixo do piso</th><th class="num">Exposição</th>
          </tr></thead><tbody id="anpiso-transp"></tbody></table></div>
        </div>
        <div class="card">
          <div class="head"><h2>Pendências de cadastro <span class="ihelp" tabindex="0" role="img" aria-label="fonte do dado" title="Veículos cujo tipo, carroceria ou tipo de carga não foi possível traduzir para número de eixos e classe da ANTT (config/antt_eixos.yaml). Estas viagens NÃO entram na conferência — não são irregulares, são desconhecidas.">i</span></h2><span class="hint">estas viagens ficaram fora da conferência</span></div>
          <div class="tablewrap"><table><thead><tr>
            <th>Placa</th><th>Tipo</th><th>Carroceria</th><th>Motivo</th>
          </tr></thead><tbody id="anpiso-pend"></tbody></table></div>
        </div>
      </section>
```

- [ ] **Step 6: Escrever loader e render**

Espelhe `loadAgr` (`api/static/index.html:9698`) — mesmo controle de sequência, mesmo `skelKpis`, mesmo tratamento de erro:

```javascript
let anpisoSeq=0;
async function loadAnpiso(){
  skelKpis('kpis-anpiso',5);
  const seq = ++anpisoSeq;
  const btn=document.getElementById('btnRefresh');
  btn.disabled=true;
  document.getElementById('content').classList.add('loading');
  try{
    const q=qsView('anpiso');
    const r=await fetch('/api/operacao/antt/piso?'+q,{cache:'no-store'});
    const d=await r.json();
    if(seq!==anpisoSeq) return;
    if(!r.ok){ showBanner(d.mensagem||'Erro ao conferir o piso mínimo.', d.detalhe); return; }
    hideBanner(); DATAANPISO=d; renderAnpiso(d); LOADEDQS.anpiso=qsView('anpiso');
  }catch(e){ if(seq===anpisoSeq) showBanner('Não foi possível falar com a API.', e.message); }
  finally{
    if(seq===anpisoSeq){ btn.disabled=false; document.getElementById('content').classList.remove('loading'); }
  }
}
```

O `renderAnpiso` monta cinco KPIs, e **cada um declara a cobertura**. A assinatura
é `kpi(label, val, sub, cls, help, trend)` (`api/static/index.html:3612`):

```javascript
function renderAnpiso(d){
  const k=d.kpis;
  if(!document.getElementById('fEmiDe').value) document.getElementById('fEmiDe').value=d.dt_de;
  if(!document.getElementById('fEmiAte').value) document.getElementById('fEmiAte').value=d.dt_ate;
  const pctAb = k.conferidas ? Math.round(100*k.abaixo/k.conferidas) : 0;
  document.getElementById('kpis-anpiso').innerHTML=[
    kpi('Viagens conferidas', k.conferidas.toLocaleString('pt-BR'),
        'conferido em '+k.conferidas+' de '+k.viagens+' viagens · '+k.isentas+' isentas', ''),
    kpi('Pago no período', BRL.format(k.pago),
        'frete de compra das viagens conferidas', ''),
    kpi('Abaixo do piso', k.abaixo.toLocaleString('pt-BR'),
        pctAb+'% das conferidas', k.abaixo>0?'alerta':''),
    kpi('Exposição', BRL.format(Math.abs(k.exposicao)),
        'soma do que faltou para o piso legal', k.exposicao<0?'alerta':''),
    kpi('Aderência', k.aderencia==null?'—':Math.round(100*k.aderencia)+'%',
        k.aderencia==null?'nenhuma viagem conferida no período':'viagens no piso ou acima', '')
  ].join('');
  renderAnpisoTabela(d.transportadores);
  renderAnpisoPendencias(d.pendencias);
  chartAnpisoRender(d.mensal||[], d.dt_de, d.dt_ate);
}
```

Confira a classe de alerta usada pelos KPIs vizinhos (`grep -n "kpi('" api/static/index.html | head`) e use o mesmo nome — se a casa usar outro rótulo em vez de `'alerta'`, siga o dela.

As duas funções de tabela seguem o padrão expansível da casa — espelhe
`agrTranspTable`/`agrToggle` (`api/static/index.html:9756`):

```javascript
function renderAnpisoTabela(ts){
  document.getElementById('anpiso-transp').innerHTML = (ts||[]).map((t,i)=>{
    const det = `
      <div class="tablewrap"><table>
        <thead><tr><th class="num">Manif.</th><th class="num">Emissão</th><th>Placa</th><th>Origem</th><th>Destino</th><th class="num">Km</th><th class="num">Eixos</th><th>Carga</th><th class="num">Pago</th><th class="num">Piso</th><th class="num">Diferença</th><th>Situação</th></tr></thead>
        <tbody>${(t.detalhe||[]).map(v=>`<tr>
          <td class="num">${v.numero}</td>
          <td class="num">${fmtD(v.dtemissao)}</td>
          <td class="num" style="font-family:var(--mono)">${esc(v.placa)}</td>
          <td>${esc(v.origem)}</td>
          <td>${esc(v.destino)}</td>
          <td class="num">${fmtKm(v.km)}</td>
          <td class="num">${v.eixos!=null?v.eixos:'—'}</td>
          <td>${v.tipo_carga?esc(v.tipo_carga.replace(/_/g,' ')):'—'}</td>
          <td class="num">${BRL.format(v.pago)}</td>
          <td class="num">${v.piso!=null?BRL.format(v.piso):'—'}</td>
          <td class="num" style="font-weight:600;color:${v.gap==null?'inherit':(v.gap<0?'var(--red)':'var(--green,#1E7F4F)')}">${v.gap!=null?BRL.format(v.gap):'—'}</td>
          <td>${ANPISO_SIT[v.estado]||esc(v.estado)}</td>
        </tr>`).join('')}</tbody>
      </table></div>`;
    return `
    <tr class="forn-row" aria-expanded="false" aria-controls="anpiso-det-${i}" tabindex="0" role="button"
        onclick="anpisoToggle(${i})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();anpisoToggle(${i});}">
      <td><span class="expander">${ICONS['chevr2']}</span></td>
      <td><div style="font-weight:600">${esc(t.transportador)}</div></td>
      <td class="num">${t.viagens.toLocaleString('pt-BR')}</td>
      <td class="num" style="font-weight:600">${BRL.format(t.pago)}</td>
      <td class="num">${t.abaixo>0?`<span class="badge b-warn">${t.abaixo}</span>`:'—'}</td>
      <td class="num" style="font-weight:700;color:${t.exposicao<0?'var(--red)':'inherit'}">${t.exposicao<0?BRL.format(t.exposicao):'—'}</td>
    </tr>
    <tr class="forn-det" id="anpiso-det-${i}"><td colspan="6">${det}</td></tr>`;
  }).join('') || '<tr><td colspan="6" style="color:var(--n500)">sem viagens de agregado no período</td></tr>';
}
function anpisoToggle(i){
  const det=document.getElementById('anpiso-det-'+i);
  if(!det) return;
  const open=det.classList.toggle('open');
  det.previousElementSibling.setAttribute('aria-expanded', String(open));
}
function renderAnpisoPendencias(ps){
  document.getElementById('anpiso-pend').innerHTML = (ps||[]).map(p=>`<tr>
      <td class="num" style="font-family:var(--mono)">${esc(p.placa||'—')}</td>
      <td>${esc(p.tipo||'—')}</td>
      <td>${esc(p.carroceria||'—')}</td>
      <td>${ANPISO_SIT[p.motivo]||esc(p.motivo)}</td>
    </tr>`).join('') || '<tr><td colspan="4" style="color:var(--n500)">nenhuma pendência — todas as viagens foram conferidas</td></tr>';
}
```

O dicionário de rótulos fica junto das outras constantes de rótulo do arquivo
(perto de `TF_LBL`/`MODAL_LBL`), e é ele que impede a tela de mostrar o nome
interno do estado ao usuário:

```javascript
const ANPISO_SIT = {
  calculado:   '<span class="badge b-ok">conferida</span>',
  isento:      '<span class="badge">vazio sem obrigação</span>',
  sem_eixos:   '<span class="badge b-warn">eixos não cadastrados</span>',
  sem_carga:   '<span class="badge b-warn">tipo de carga não cadastrado</span>',
  sem_km:      '<span class="badge b-warn">viagem sem km</span>',
  sem_tabela:  '<span class="badge b-warn">combinação fora da tabela ANTT</span>'
};
```

Confira os nomes reais das classes de badge (`grep -n 'class="badge b-' api/static/index.html | head`) e use os da casa.

- [ ] **Step 7: Gráfico de aderência mensal**

Espelhe `chartAgrRender` (`api/static/index.html:9801`), que já resolve tudo o que
esse gráfico precisa: `niceTicks`, `unitOf`, `colPath`, hachura de mês parcial via
`_mesParcial`, registro em `GEOM` e `bindHover`. Duas diferenças:

- o eixo é **percentual de aderência**, não dinheiro: o topo é 100 e o rótulo do
  eixo é `%`, sem `unitOf`;
- a barra é pintada de vermelho quando a aderência do mês fica abaixo de 100%, e
  o rótulo em cima mostra `r.abaixo+' abaixo'` em vez de valor em reais.

```javascript
function chartAnpisoRender(mensal, dtDe, dtAte){
  const svg=document.getElementById('chartAnpiso');
  GEOM['chartAnpiso']=null; ACTIVE['chartAnpiso']=-1;
  if(!mensal.length){ svg.innerHTML='<text x="480" y="120" text-anchor="middle" fill="#6E7883" font-size="14">sem viagem conferida no período</text>'; return; }
  // resto: mesma geometria de chartAgrRender, com top=100 fixo e
  // y=v=>mT+ih-(v/100)*ih sobre r.aderencia*100
}
```

Um mês sem nenhuma viagem conferida **não** vira barra de 100% — ele já sai de
`serie_mensal` fora da lista, e é isso que evita ler ausência de dado como
conformidade.

- [ ] **Step 8: Acrescentar à gaveta mobile**

No `<div class="drawer">` (`:11418`), no grupo correspondente, acrescente:

```html
<a href="#anpiso" onclick="fecharDrawer()"><span class="ic" data-ic="qualic"></span>Piso ANTT</a>
```

Siga a marcação exata dos vizinhos dentro do mesmo `dgrp-b`.

- [ ] **Step 9: Rodar os testes e olhar a tela**

Run: `uv run pytest tests/antt/ -v`
Expected: PASS.

Depois suba a API, abra `http://127.0.0.1:8000/#anpiso` e confira: KPIs preenchidos, tabela abrindo, filtro de período mudando o resultado, e a tela aparecendo no menu e na gaveta mobile (janela estreita).

- [ ] **Step 10: Commit**

```bash
git add api/static/index.html tests/antt/test_tela_e2e.py
git commit -m "feat(antt): tela do piso minimo e grupo ANTT no menu"
```

---

### Task 8: Ganchos, versionamento e documentação

**Files:**
- Modify: `api/static/index.html` — coluna na tela Agregados e linha no Make vs Buy
- Modify: `pyproject.toml` (versão), `docs/versoes.yaml`, `CLAUDE.md`, `docs/manual.yaml`
- Modify: `CHANGELOG.md` (gerado, não editado à mão)

- [ ] **Step 1: Gancho na tela Agregados**

Em `renderAgr`, na linha de cada transportador, acrescente uma coluna "vs piso" que aparece apenas quando `DATAANPISO` já foi carregado para o mesmo período — nunca dispare uma segunda consulta a partir da tela Agregados. Sem dado carregado, a coluna mostra `—` com o tooltip "abra Piso Mínimo de Frete para conferir".

- [ ] **Step 2: Gancho no Make vs Buy**

Em `renderMvb`, na linha de custo de compra, acrescente o piso legal como referência textual, com a mesma regra: só quando o dado do piso já estiver em memória.

- [ ] **Step 3: Subir a versão**

`pyproject.toml`: `version = "0.4.0"`.

No topo de `docs/versoes.yaml`:

```yaml
- versao: "0.4.0"
  data: "2026-08-18"
  adicionado:
    - >-
      Grupo ANTT no menu, com a tela Piso Mínimo de Frete: cada viagem paga a
      agregado ou terceiro é conferida contra o piso legal da ANTT vigente na
      data da viagem.
    - >-
      A tela mostra quanto foi pago abaixo do piso, para quem, e a exposição
      total do período — com a cobertura sempre declarada: conferido em X de Y
      viagens.
    - >-
      Veículo sem número de eixos ou tipo de carga cadastrado aparece em
      "Pendências de cadastro" em vez de sumir da conta.
```

- [ ] **Step 4: Gerar o CHANGELOG**

Run: `uv run python scripts/gerar_changelog.py`
Expected: `CHANGELOG.md` com a seção 0.4.0 no topo.

- [ ] **Step 5: Atualizar CLAUDE.md e o manual**

Em `CLAUDE.md`, na seção 3 (Módulos do portal), acrescente a linha do módulo ANTT. Em `docs/manual.yaml`, acrescente a entrada da tela `anpiso` seguindo o formato das vizinhas — é o que alimenta a tela de Documentação.

- [ ] **Step 6: Rodar a suíte inteira**

Run: `uv run pytest -q`
Expected: toda a suíte passando, incluindo os testes pré-existentes. Se algo que não é do módulo ANTT quebrou, conserte antes de commitar.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(antt): ganchos nas telas vizinhas, versao 0.4.0 e documentacao"
```

---

## Fora do escopo desta fase

RNTRC, autos de infração e mercado/pedágio são as fases 2, 3 e 4 da spec. A Tabela B (contratação só da unidade de tração) fica carregada no YAML mas sem uso automático: escolher entre A e B depende do que o contrato diz, e isso não está no AVA.
