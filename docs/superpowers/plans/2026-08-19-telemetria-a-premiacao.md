# Telemetria A — cliente Gobrax e Premiação por nota × km — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar o cliente único da API Gobrax por token, trocar a fonte e a regra da Premiação para nota × km, e mover a tela para um grupo de menu novo chamado Telemetria.

**Architecture:** Um cliente HTTP compartilhado (`api/gobrax/`) autenticando por `Authorization: Bearer`, com os gotchas de data medidos embutidos. A Premiação passa a consumir `driversOverview` em vez do login Kratos, e a regra de litros economizados dá lugar a `km × valor_por_km × (nota/100)`. Snapshot passa a gravar qual regra o gerou, para que mês já pago continue exibindo o valor com que foi pago.

**Tech Stack:** Python 3.12, urllib puro (o venv não tem requests — import de requests já derrubou a app), FastAPI, pytest + Playwright, SPA vanilla.

**Spec:** `docs/superpowers/specs/2026-08-19-telemetria-gobrax-design.md`

## Global Constraints

- **Medido em 19/08/2026, não suposto:** `Authorization: Bearer <token>`; host `https://gateway-v3.gobrax.com.br:8889`; `driversOverview` usa `MM-YYYY` e **exige `endDate` diferente de `startDate`** (mês igual devolve HTTP 400 code 67); 12 meses numa chamada estouram timeout; a resposta traz 87 motoristas.
- **O `Reward` da API é ignorado** — vem zerado. O prêmio é calculado por nós.
- **Nenhum CPF gravado, logado ou exibido.** `DocumentNumber` serve para casar e é descartado.
- **O token nunca aparece em log, em payload ou em mensagem de erro.**
- **Coleta vazia nunca sobrescreve snapshot com dados** (já custou um mês de dados).
- **Histórico não é recalculado**: snapshot antigo mantém a regra e o valor com que foi pago.
- **Rodar**: `uv run pytest tests/gobrax/ tests/premiacao/ -v`. Versão 0.6.0 → 0.7.0.

---

### Task 1: Cliente HTTP da Gobrax

**Files:**
- Create: `api/gobrax/__init__.py`, `api/gobrax/cliente.py`
- Test: `tests/gobrax/__init__.py`, `tests/gobrax/test_cliente.py`

**Interfaces:**
- Produces:
  - `BASE: str`, `configurado() -> bool`
  - `class GobraxNaoConfigurado(Exception)`, `class GobraxIndisponivel(Exception)`
  - `class Cliente` com `get(caminho: str, params: dict | None = None, timeout: int = 120) -> dict`
  - `mes_api(mes: str) -> tuple[str, str]` — `"2026-03"` → `("03-2026", "04-2026")`
  - `periodo_api(inicio: date, fim: date) -> tuple[str, str]` — `"YYYY-MM-DD HH:MM:SS"`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/gobrax/test_cliente.py
"""Cliente da API Gobrax: autenticação, formatos de data e erros.

Os formatos aqui não são suposição: foram medidos contra a API em 19/08/2026.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.gobrax import cliente as cli


def test_mes_vira_mm_yyyy_com_fim_no_mes_seguinte():
    """A API devolve HTTP 400 quando startDate == endDate. Pedir março exige
    passar abril como fim — foi o primeiro erro da sondagem."""
    assert cli.mes_api("2026-03") == ("03-2026", "04-2026")


def test_virada_de_ano_no_mes_seguinte():
    assert cli.mes_api("2026-12") == ("12-2026", "01-2027")


def test_mes_invalido_e_recusado_antes_de_ir_na_rede():
    for ruim in ("2026-13", "26-03", "2026/03", "", None):
        with pytest.raises(ValueError):
            cli.mes_api(ruim)


def test_periodo_usa_o_formato_das_apis_de_veiculo():
    ini, fim = cli.periodo_api(date(2026, 7, 1), date(2026, 7, 31))
    assert ini == "2026-07-01 00:00:00"
    assert fim == "2026-07-31 23:59:59"


def test_token_vai_no_header_como_bearer():
    chamadas = []

    def http_falso(url, headers, timeout):
        chamadas.append((url, headers))
        return 200, b'{"ok": true}'

    c = cli.Cliente(token="TOKEN-DE-TESTE", http=http_falso)
    assert c.get("/api/v2/driversOverview") == {"ok": True}
    _url, headers = chamadas[0]
    assert headers["Authorization"] == "Bearer TOKEN-DE-TESTE"


def test_sem_token_levanta_erro_proprio():
    with pytest.raises(cli.GobraxNaoConfigurado):
        cli.Cliente(token="")


def test_erro_http_nao_vaza_o_token_na_mensagem():
    """Mensagem de erro vai para log e para a tela. O token não pode viajar."""
    def http_falso(url, headers, timeout):
        return 401, b'{"erro": "nao autorizado"}'

    c = cli.Cliente(token="SEGREDO-QUE-NAO-PODE-VAZAR", http=http_falso)
    with pytest.raises(cli.GobraxIndisponivel) as e:
        c.get("/api/v2/driversOverview")
    assert "SEGREDO" not in str(e.value)
    assert "401" in str(e.value)


def test_timeout_da_rede_vira_gobrax_indisponivel():
    """A API leva 73 s na frota inteira e estoura em período longo — timeout é
    comportamento esperado, não bug, e tem de virar erro tratável."""
    def http_falso(url, headers, timeout):
        raise TimeoutError("read timed out")

    c = cli.Cliente(token="X", http=http_falso)
    with pytest.raises(cli.GobraxIndisponivel):
        c.get("/api/v1/vehicle-statistics")


def test_resposta_nao_json_vira_gobrax_indisponivel():
    def http_falso(url, headers, timeout):
        return 200, b"<html>gateway</html>"

    c = cli.Cliente(token="X", http=http_falso)
    with pytest.raises(cli.GobraxIndisponivel):
        c.get("/api/v2/driversOverview")


def test_params_none_sao_omitidos_da_query():
    chamadas = []

    def http_falso(url, headers, timeout):
        chamadas.append(url)
        return 200, b"{}"

    c = cli.Cliente(token="X", http=http_falso)
    c.get("/x", {"a": "1", "b": None})
    assert "a=1" in chamadas[0]
    assert "b=" not in chamadas[0]
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/gobrax/test_cliente.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.gobrax'`

- [ ] **Step 3: Implementar**

```python
# api/gobrax/cliente.py
"""Cliente das APIs públicas da Gobrax — autenticação por token.

urllib puro de propósito: o venv não tem requests nem httpx, e um import de
requests já derrubou a aplicação inteira uma vez.

Isto NÃO é o mesmo caminho do api/premiacao/gobrax.py antigo, que fala com
gateway-v3-waf e faz login no Kratos com e-mail e senha. As APIs públicas são
outro host, outra porta e outra autenticação.

Comportamentos medidos contra a API em 19/08/2026, não supostos:
  - Authorization: Bearer <token>
  - driversOverview usa MM-YYYY e EXIGE endDate != startDate (400 code 67)
  - período de 12 meses estoura timeout; coletar mês a mês
  - vehicle-statistics da frota inteira leva ~73 s
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

BASE = "https://gateway-v3.gobrax.com.br:8889"

_CTX = ssl.create_default_context()


class GobraxNaoConfigurado(Exception):
    """Falta GOBRAX_TOKEN no ambiente."""


class GobraxIndisponivel(Exception):
    """A API não respondeu, respondeu erro, ou respondeu coisa que não é JSON."""


def configurado() -> bool:
    return bool(os.environ.get("GOBRAX_TOKEN", "").strip())


def mes_api(mes: str) -> tuple[str, str]:
    """'2026-03' -> ('03-2026', '04-2026').

    O fim é o mês SEGUINTE porque a API recusa startDate igual a endDate com
    HTTP 400 'Datas fornecidas inválidas'.
    """
    if not isinstance(mes, str) or len(mes) != 7 or mes[4] != "-":
        raise ValueError(f"mês inválido: {mes!r} — use o formato AAAA-MM")
    ano, m = mes.split("-")
    if not (ano.isdigit() and m.isdigit() and 1 <= int(m) <= 12):
        raise ValueError(f"mês inválido: {mes!r} — use o formato AAAA-MM")
    ano_i, m_i = int(ano), int(m)
    prox = (ano_i + 1, 1) if m_i == 12 else (ano_i, m_i + 1)
    return f"{m_i:02d}-{ano_i}", f"{prox[1]:02d}-{prox[0]}"


def periodo_api(inicio: date, fim: date) -> tuple[str, str]:
    """Formato das APIs de veículo: 'AAAA-MM-DD HH:MM:SS'."""
    return (inicio.strftime("%Y-%m-%d 00:00:00"), fim.strftime("%Y-%m-%d 23:59:59"))


def _http(url: str, headers: dict, timeout: int):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Cliente:
    def __init__(self, token: str | None = None, http=None):
        self.token = (token if token is not None
                      else os.environ.get("GOBRAX_TOKEN", "")).strip()
        if not self.token:
            raise GobraxNaoConfigurado(
                "GOBRAX_TOKEN não está no ambiente — a integração fica desligada")
        self._http = http or _http

    def get(self, caminho: str, params: dict | None = None,
            timeout: int = 120) -> dict:
        limpos = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{BASE}{caminho}"
        if limpos:
            url += "?" + urllib.parse.urlencode(limpos)
        try:
            status, corpo = self._http(
                url, {"Authorization": f"Bearer {self.token}",
                      "Accept": "application/json"}, timeout)
        except Exception as exc:  # noqa: BLE001 — timeout, DNS, socket
            # a mensagem vai para log e para a tela: nunca inclui o token
            raise GobraxIndisponivel(
                f"falha de rede ao chamar {caminho}: {type(exc).__name__}") from None
        if status != 200:
            trecho = (corpo or b"")[:200].decode("utf-8", "ignore")
            raise GobraxIndisponivel(f"{caminho} respondeu HTTP {status}: {trecho}")
        try:
            return json.loads(corpo)
        except json.JSONDecodeError:
            raise GobraxIndisponivel(
                f"{caminho} respondeu algo que não é JSON") from None
```

Crie `api/gobrax/__init__.py` e `tests/gobrax/__init__.py` vazios.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/gobrax/test_cliente.py -v`
Expected: PASS, 9 testes.

- [ ] **Step 5: Provar contra a API real**

```bash
uv run python -c "
import os
from pathlib import Path
for l in Path('.env').read_text().splitlines():
    if l.strip() and not l.startswith('#') and '=' in l:
        k,v=l.split('=',1); os.environ.setdefault(k.strip(), v.strip())
from api.gobrax.cliente import Cliente, mes_api
ini, fim = mes_api('2026-04')
d = Cliente().get('/api/v2/driversOverview',
                  {'documentNumbers': '', 'startDate': ini, 'endDate': fim})
print('motoristas:', len((d.get('data') or [])))
"
```

Expected: 87 motoristas. Se vier HTTP 400, o `mes_api` regrediu no gotcha do
`endDate`. **Não imprima o token em nenhuma verificação.**

- [ ] **Step 6: Commit**

```bash
git add api/gobrax tests/gobrax
git commit -m "feat(gobrax): cliente das APIs publicas por token"
```

---

### Task 2: Coleta do driversOverview

**Files:**
- Create: `api/gobrax/overview.py`
- Test: `tests/gobrax/test_overview.py`

**Interfaces:**
- Consumes: `cliente.Cliente`, `cliente.mes_api`.
- Produces: `coletar(mes: str, cliente=None) -> list[dict]` — `[{driverId, driverName, km, nota}]`, só quem tem atividade no mês pedido.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/gobrax/test_overview.py
"""driversOverview -> motoristas com km e nota. Sem CPF, sem Reward."""
from __future__ import annotations

from api.gobrax import overview

RESPOSTA = {"success": True, "data": [
    {"ID": 13, "Name": "3190 - JEAN LAURO", "DocumentNumber": "12345678901",
     "Err": "", "Overview": [
         {"Date": "03-2026", "Reward": 0, "TotalKM": 2922, "Score": 93, "Err": ""},
         {"Date": "04-2026", "Reward": 0, "TotalKM": 5200, "Score": 99, "Err": ""}]},
    {"ID": 14, "Name": "3773 - AGNALDO", "DocumentNumber": "98765432100",
     "Err": "", "Overview": [
         {"Date": "03-2026", "Reward": 0, "TotalKM": 3094, "Score": 85, "Err": ""}]},
    {"ID": 15, "Name": "SEM ATIVIDADE", "DocumentNumber": "11111111111",
     "Err": "", "Overview": [
         {"Date": "03-2026", "Reward": 0, "TotalKM": 0, "Score": 0,
          "Err": "performance data not found"}]},
]}


class ClienteFalso:
    def __init__(self, resposta=None):
        self.resposta = resposta if resposta is not None else RESPOSTA
        self.chamadas = []

    def get(self, caminho, params=None, timeout=120):
        self.chamadas.append((caminho, params))
        return self.resposta


def test_traz_so_o_mes_pedido():
    """A API devolve o mês pedido E o seguinte, porque endDate tem de ser
    diferente. Só o mês pedido interessa."""
    c = ClienteFalso()
    linhas = overview.coletar("2026-03", cliente=c)
    assert {l["driverName"] for l in linhas} == {"3190 - JEAN LAURO", "3773 - AGNALDO"}
    assert [l["km"] for l in linhas if l["driverId"] == 13] == [2922]


def test_pede_o_periodo_no_formato_da_api():
    c = ClienteFalso()
    overview.coletar("2026-03", cliente=c)
    _caminho, params = c.chamadas[0]
    assert params["startDate"] == "03-2026"
    assert params["endDate"] == "04-2026"


def test_motorista_sem_atividade_fica_de_fora():
    c = ClienteFalso()
    linhas = overview.coletar("2026-03", cliente=c)
    assert all(l["driverName"] != "SEM ATIVIDADE" for l in linhas)


def test_nunca_devolve_documento_nem_reward():
    """CPF é PII e não tem uso aqui; Reward vem zerado da API e o cálculo é
    nosso — carregar os dois só cria chance de erro."""
    linhas = overview.coletar("2026-03", cliente=ClienteFalso())
    for l in linhas:
        assert "documento" not in l and "DocumentNumber" not in l
        assert "reward" not in l and "Reward" not in l
    assert "12345678901" not in repr(linhas)


def test_campos_do_retorno():
    l = overview.coletar("2026-03", cliente=ClienteFalso())[0]
    assert sorted(l.keys()) == ["driverId", "driverName", "km", "nota"]


def test_resposta_sem_data_devolve_lista_vazia():
    assert overview.coletar("2026-03", cliente=ClienteFalso({"success": True})) == []


def test_resposta_de_insucesso_devolve_lista_vazia():
    """Lista vazia sobe para quem chama decidir — e a regra da casa é que
    coleta vazia não sobrescreve snapshot bom."""
    c = ClienteFalso({"success": False, "data": None})
    assert overview.coletar("2026-03", cliente=c) == []
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/gobrax/test_overview.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar**

```python
# api/gobrax/overview.py
"""driversOverview — km e nota por motorista, por mês.

A API devolve o mês pedido E o seguinte (porque endDate tem de ser diferente de
startDate); filtramos aqui para o mês que interessa.

Dois campos da resposta são descartados de propósito: DocumentNumber, que é CPF
e não tem uso nosso, e Reward, que vem zerado — o prêmio é calculado por nós.
"""
from __future__ import annotations

from api.gobrax.cliente import Cliente, mes_api

CAMINHO = "/api/v2/driversOverview"


def coletar(mes: str, cliente=None) -> list[dict]:
    ini, fim = mes_api(mes)
    c = cliente or Cliente()
    corpo = c.get(CAMINHO, {"documentNumbers": "", "startDate": ini,
                            "endDate": fim}, timeout=180)
    alvo = ini  # 'MM-AAAA', o mesmo formato que vem em Overview[].Date
    saida = []
    for m in (corpo.get("data") or []):
        for o in (m.get("Overview") or []):
            if (o.get("Date") or "") != alvo:
                continue
            km = float(o.get("TotalKM") or 0)
            nota = float(o.get("Score") or 0)
            if km <= 0 and nota <= 0:
                continue      # sem atividade no mês
            saida.append({"driverId": m.get("ID"),
                          "driverName": (m.get("Name") or "").strip(),
                          "km": km, "nota": nota})
    return saida
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/gobrax/test_overview.py -v`
Expected: PASS, 7 testes.

- [ ] **Step 5: Provar contra a API real**

```bash
uv run python -c "
import os
from pathlib import Path
for l in Path('.env').read_text().splitlines():
    if l.strip() and not l.startswith('#') and '=' in l:
        k,v=l.split('=',1); os.environ.setdefault(k.strip(), v.strip())
from api.gobrax import overview
linhas = overview.coletar('2026-04')
print('motoristas com atividade:', len(linhas))
for l in sorted(linhas, key=lambda x: -x['km'])[:3]:
    print('  ', l['driverName'][:26], 'km', round(l['km']), 'nota', l['nota'])
"
```

Expected: 46 motoristas em abril/2026, e JEAN LAURO com ~5.200 km e nota 99.

- [ ] **Step 6: Commit**

```bash
git add api/gobrax/overview.py tests/gobrax/test_overview.py
git commit -m "feat(gobrax): coleta de km e nota por motorista"
```

---

### Task 3: A regra nova de premiação

**Files:**
- Modify: `api/premiacao/calculo.py`, `api/premiacao/params.py`
- Test: `tests/premiacao/test_calculo_nota_km.py`

**Interfaces:**
- Produces:
  - `REGRA = "nota_km"`
  - `calcular(motoristas: list[dict], params: dict) -> dict` — mesma assinatura de antes; `params` agora é `{valor_por_km, nota_minima, km_minimo}`.
  - `params.DEFAULTS = {"valor_por_km": 0.10, "nota_minima": 70.0, "km_minimo": 1500.0}`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/premiacao/test_calculo_nota_km.py
"""Regra nova: premio = km × valor_por_km × (nota/100), com cortes.

Os números de conferência são reais, medidos na API em 19/08/2026 (abril/2026).
"""
from __future__ import annotations

from api.premiacao import calculo

PARAMS = {"valor_por_km": 0.10, "nota_minima": 70.0, "km_minimo": 1500.0}


def _m(nome="FULANO", km=5200.0, nota=99.0, **kw):
    return {"driverId": 1, "driverName": nome, "km": km, "nota": nota, **kw}


def test_formula_confere_com_o_exemplo_aprovado():
    """JEAN LAURO, abril/2026: 5.200 km, nota 99, a R$ 0,10/km = R$ 514,80."""
    r = calculo.calcular([_m(km=5200.0, nota=99.0)], PARAMS)
    assert r["linhas"][0]["premio"] == 514.80


def test_outros_dois_exemplos_aprovados():
    r = calculo.calcular([_m(nome="AGNALDO", km=2840.0, nota=81.0),
                          _m(nome="ANGELA", km=2595.0, nota=73.0)], PARAMS)
    premios = {l["driverName"]: l["premio"] for l in r["linhas"]}
    assert premios["AGNALDO"] == 230.04
    assert premios["ANGELA"] == 189.44


def test_nota_abaixo_da_minima_nao_premia_mas_continua_visivel():
    r = calculo.calcular([_m(nota=69.0)], PARAMS)
    linha = r["linhas"][0]
    assert linha["premio"] == 0
    assert linha["elegivel"] is False
    assert linha["motivo"] == "nota abaixo da mínima"


def test_km_abaixo_do_minimo_nao_premia():
    r = calculo.calcular([_m(km=1499.0)], PARAMS)
    assert r["linhas"][0]["premio"] == 0
    assert r["linhas"][0]["motivo"] == "km abaixo do mínimo"


def test_totais_contam_so_os_elegiveis():
    r = calculo.calcular([_m(nome="OK", km=5200.0, nota=99.0),
                          _m(nome="NOTA BAIXA", km=5200.0, nota=50.0),
                          _m(nome="POUCO KM", km=100.0, nota=99.0)], PARAMS)
    assert r["premiados"] == 1
    assert r["premio_total"] == 514.80
    assert r["motoristas"] == 3


def test_km_ou_nota_negativos_nao_geram_premio():
    """Leitura implausível de telemetria não pode virar dinheiro."""
    for ruim in (_m(km=-100.0), _m(nota=-5.0)):
        r = calculo.calcular([ruim], PARAMS)
        assert r["linhas"][0]["premio"] == 0


def test_nota_acima_de_cem_e_tratada_como_cem():
    """Score é uma nota de 0 a 100; acima disso é defeito da origem e não pode
    inflar o prêmio."""
    r = calculo.calcular([_m(km=1000.0, nota=150.0)], PARAMS)
    assert r["linhas"][0]["premio"] == 100.00


def test_lista_vazia_nao_quebra():
    r = calculo.calcular([], PARAMS)
    assert r["premio_total"] == 0 and r["premiados"] == 0


def test_a_regra_e_identificada_no_resultado():
    """O snapshot grava qual regra gerou o valor: mês antigo continua exibindo
    o valor com que foi pago."""
    r = calculo.calcular([_m()], PARAMS)
    assert r["regra"] == "nota_km"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/premiacao/test_calculo_nota_km.py -v`
Expected: FAIL — a `calcular` atual espera `media` e devolve outras chaves.

- [ ] **Step 3: Reescrever `calculo.py`**

```python
# api/premiacao/calculo.py
"""Regra de premiação por nota × km. Módulo PURO.

    elegível = nota >= nota_minima E km >= km_minimo
    premio   = km × valor_por_km × (nota / 100)

Substitui a regra anterior (litros economizados), que dependia da média de
consumo por motorista — dado que a API pública da Gobrax não fornece. Decisão do
usuário em 19/08/2026.

Snapshot antigo NÃO é recalculado: ele registra a regra que o gerou, e mês já
pago continua exibindo o valor com que foi pago.

Linha não elegível continua VISÍVEL na lista, com o motivo, e fica fora dos
totais — mesmo tratamento que a regra anterior dava a leitura implausível.
"""
from __future__ import annotations

REGRA = "nota_km"
NOTA_MAXIMA = 100.0


def calcular(motoristas: list[dict], params: dict) -> dict:
    valor_km = float(params["valor_por_km"])
    nota_min = float(params["nota_minima"])
    km_min = float(params["km_minimo"])

    linhas: list[dict] = []
    for m in motoristas:
        km = float(m.get("km") or 0)
        nota = float(m.get("nota") or 0)
        motivo = None
        if km < 0 or nota < 0:
            motivo = "leitura inválida"
        elif nota < nota_min:
            motivo = "nota abaixo da mínima"
        elif km < km_min:
            motivo = "km abaixo do mínimo"
        elegivel = motivo is None
        # nota acima de 100 é defeito da origem: limitar evita inflar o prêmio
        nota_efetiva = min(nota, NOTA_MAXIMA)
        premio = round(km * valor_km * (nota_efetiva / 100.0), 2) if elegivel else 0
        linhas.append({**m, "elegivel": elegivel, "motivo": motivo,
                       "premio": premio})

    premiados = [l for l in linhas if l["elegivel"] and l["premio"] > 0]
    return {
        "regra": REGRA,
        "linhas": sorted(linhas, key=lambda l: -l["premio"]),
        "motoristas": len(linhas),
        "premiados": len(premiados),
        "premio_total": round(sum(l["premio"] for l in premiados), 2),
        "km_total": round(sum(float(l.get("km") or 0) for l in linhas), 2),
        "params": {"valor_por_km": valor_km, "nota_minima": nota_min,
                   "km_minimo": km_min},
    }
```

- [ ] **Step 4: Trocar os parâmetros**

Em `api/premiacao/params.py`, troque `DEFAULTS` e `_valida`:

```python
DEFAULTS = {"valor_por_km": 0.10, "nota_minima": 70.0, "km_minimo": 1500.0}


def _valida(p: dict) -> None:
    if p["valor_por_km"] <= 0:
        raise ValueError("O valor por km tem de ser maior que zero.")
    if not (0 <= p["nota_minima"] <= 100):
        raise ValueError("A nota mínima vai de 0 a 100.")
    if p["km_minimo"] < 0:
        raise ValueError("O km mínimo não pode ser negativo.")
```

O resto do arquivo (leitura, gravação, fallback para defaults) não muda.

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `uv run pytest tests/premiacao/ -v`
Expected: os testes novos passam. **Os testes antigos da regra de litros vão falhar** — eles cobrem uma regra que não existe mais. Apague `tests/premiacao/test_calculo.py` (ou o arquivo equivalente da regra antiga) e registre no commit que a regra mudou; não adapte teste de regra extinta.

- [ ] **Step 6: Commit**

```bash
git add api/premiacao/calculo.py api/premiacao/params.py tests/premiacao/
git commit -m "feat(premiacao): regra passa a ser nota da Gobrax x km rodado"
```

---

### Task 4: Ligar a coleta nova ao serviço

**Files:**
- Modify: `api/premiacao/coleta.py`, `api/premiacao/servico.py`
- Test: `tests/premiacao/test_coleta_overview.py`

**Interfaces:**
- Produces: `coleta.coletar_mes(mes: str, cliente=None, agora=None) -> dict` — snapshot `{month, source, regra_fonte, coletado_em, parcial, drivers[]}`, com `drivers` no formato `{driverId, driverName, km, nota}`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/premiacao/test_coleta_overview.py
"""A coleta passa a vir do driversOverview, não do login Kratos."""
from __future__ import annotations

from datetime import datetime

import pytest

from api.premiacao import coleta

LINHAS = [{"driverId": 13, "driverName": "JEAN", "km": 5200.0, "nota": 99.0},
          {"driverId": 14, "driverName": "AGNALDO", "km": 2840.0, "nota": 81.0}]


def test_snapshot_registra_a_fonte_e_a_regra():
    snap = coleta.coletar_mes("2026-04", coletor=lambda mes, cliente=None: LINHAS,
                              agora=datetime(2026, 5, 2, 10, 0))
    assert snap["source"] == "gobrax-api-overview"
    assert snap["regra_fonte"] == "nota_km"
    assert len(snap["drivers"]) == 2


def test_mes_corrente_e_marcado_como_parcial():
    snap = coleta.coletar_mes("2026-05", coletor=lambda mes, cliente=None: LINHAS,
                              agora=datetime(2026, 5, 15, 10, 0))
    assert snap["parcial"] is True


def test_mes_fechado_nao_e_parcial():
    snap = coleta.coletar_mes("2026-04", coletor=lambda mes, cliente=None: LINHAS,
                              agora=datetime(2026, 5, 2, 10, 0))
    assert snap["parcial"] is False


def test_coleta_vazia_levanta_erro_em_vez_de_gravar_nada():
    """A regra que já custou um mês de dados: coleta vazia não pode virar
    snapshot, senão sobrescreve o mês bom com zero."""
    with pytest.raises(coleta.ColetaVazia):
        coleta.coletar_mes("2026-04", coletor=lambda mes, cliente=None: [],
                           agora=datetime(2026, 5, 2, 10, 0))
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/premiacao/test_coleta_overview.py -v`
Expected: FAIL — `coletar_mes` tem outra assinatura e não existe `ColetaVazia`.

- [ ] **Step 3: Reescrever a coleta**

Substitua o corpo de `coletar_mes` em `api/premiacao/coleta.py`. O que sai: o
`fetch_bonds`, o XLSX de vínculos, os lotes de 10, o casamento por nome
normalizado e tudo que dependia do login. O que fica: `gravar_snapshot`,
`ler_snapshot`, `ler_index`, `_reescrever_index`, `_escrever_atomico`.

```python
class ColetaVazia(Exception):
    """A coleta não trouxe motorista nenhum. Nunca vira snapshot: já aconteceu
    de uma coleta vazia sobrescrever um mês inteiro de dados bons."""


def coletar_mes(mes: str, cliente=None, agora=None, coletor=None) -> dict:
    from api.gobrax import overview

    agora = agora or datetime.now()
    linhas = (coletor or overview.coletar)(mes, cliente=cliente)
    if not linhas:
        raise ColetaVazia(f"driversOverview não trouxe motoristas para {mes}")
    return {
        "month": mes,
        "source": "gobrax-api-overview",
        "regra_fonte": "nota_km",
        "coletado_em": agora.isoformat(timespec="seconds"),
        "parcial": mes == agora.strftime("%Y-%m"),
        "drivers": linhas,
    }
```

Em `api/premiacao/servico.py`, a chamada a `coletar_mes` passa a tratar
`ColetaVazia` como "manter o snapshot que já existe", no mesmo lugar onde hoje
trata `GobraxIndisponivel`. Procure por `_novo_cliente` e `obter` e siga a
estrutura que já está lá; o cliente agora vem de `api.gobrax.cliente.Cliente`.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/premiacao/ -v`
Expected: PASS.

- [ ] **Step 5: Provar contra a API real, sem gravar por cima**

```bash
uv run python -c "
import os
from pathlib import Path
for l in Path('.env').read_text().splitlines():
    if l.strip() and not l.startswith('#') and '=' in l:
        k,v=l.split('=',1); os.environ.setdefault(k.strip(), v.strip())
from api.premiacao import coleta, calculo, params
snap = coleta.coletar_mes('2026-04')
r = calculo.calcular(snap['drivers'], params.ler_params())
print('motoristas:', r['motoristas'], '| premiados:', r['premiados'])
print('premio total: R\$', r['premio_total'])
for l in r['linhas'][:3]:
    print('  ', l['driverName'][:26], 'km', round(l['km']), 'nota', l['nota'], '-> R\$', l['premio'])
"
```

Expected: abril/2026 com 46 motoristas e os três valores conferidos
(514,80 / 230,04 / 189,44). **Confira o total antes de seguir** — é o número que
vira pagamento.

- [ ] **Step 6: Commit**

```bash
git add api/premiacao tests/premiacao
git commit -m "feat(premiacao): coleta pela API publica, sem login Kratos"
```

---

### Task 5: Grupo Telemetria no menu

**Files:**
- Modify: `api/static/index.html`, `api/auth.py`
- Test: `tests/premiacao/test_menu_telemetria.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/premiacao/test_menu_telemetria.py
"""A Premiação sai de Frota e passa a viver em Telemetria."""
from __future__ import annotations

from pathlib import Path

from api import auth

HTML = Path(__file__).resolve().parent.parent.parent / "api" / "static" / "index.html"
S = HTML.read_text(encoding="utf-8")


def test_grupo_telemetria_existe_no_menu():
    assert 'id="grpTel"' in S
    assert "Telemetria" in S


def test_premiacao_esta_dentro_do_grupo_telemetria():
    bloco = S.split('id="subsTel"', 1)[1].split("</div>", 1)[0]
    assert 'data-view="prem"' in bloco


def test_premiacao_saiu_do_grupo_frota():
    bloco = S.split('id="subsFro"', 1)[1].split("</div>", 1)[0]
    assert 'data-view="prem"' not in bloco


def test_rbac_move_a_tela_de_grupo():
    assert auth.TELAS["prem"] == ("Premiação de Motoristas", "Telemetria")
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/premiacao/test_menu_telemetria.py -v`
Expected: FAIL — `id="grpTel"` não existe.

- [ ] **Step 3: Criar o grupo e mover a tela**

Em `api/static/index.html`, remova a linha de `#prem` de dentro de `subsFro` e
crie o grupo novo antes de `grpAntt`:

```html
      <button class="group" id="grpTel" aria-expanded="false" aria-controls="subsTel" onclick="toggleGroup('grpTel','subsTel','cs.telGroup')" title="Telemetria">
        <span class="ic" data-ic="sinal"></span><span>Telemetria</span><span class="ic chev" data-ic="chev"></span>
      </button>
      <div class="subs closed" id="subsTel">
        <a href="#prem" class="sub" data-view="prem" title="Premiação de Motoristas — nota da Gobrax e km rodado"><span class="ic" data-ic="prem"></span><span>Premiação de Motoristas</span></a>
      </div>
```

Faça o mesmo movimento na gaveta mobile: tirar de Frota, criar o grupo
Telemetria. Em `api/auth.py`, mude a linha de `prem` em `TELAS` para o grupo
`"Telemetria"` e acrescente `prem` ao perfil Diretoria em `_PERFIS_MODELO`, com
seed incremental v24 (espelhe o bloco v23), porque a tela hoje é do perfil Frota
e a Diretoria é quem tem usuário real.

- [ ] **Step 4: Ajustar a tela ao novo vocabulário**

Em `renderPrem`, os KPIs e a tabela falam de "litros economizados" e "média
km/l", que não existem mais. Passe a mostrar nota e km:

- KPI "Prêmio total" — inalterado.
- KPI "Premiados" — `premiados de motoristas`.
- KPI "Km rodado" — `km_total`.
- Onde havia média/litros, mostre a **nota** e o **motivo** de não elegível.

Os campos do formulário de parâmetros mudam de `meta`/`preco_litro`/
`pct_premiacao` para `valor_por_km`/`nota_minima`/`km_minimo` — procure por
`fPrem` no HTML e ajuste os três campos e o `salvarParams`.

- [ ] **Step 5: Rodar tudo**

Run: `uv run pytest -q`
Expected: verde. Suba a API, abra `#prem` e confira: a tela está sob Telemetria,
os parâmetros salvam, e o prêmio recalcula ao mudar o valor por km.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(telemetria): grupo no menu e premiacao movida para dentro"
```

---

### Task 6: Versão e documentação

- [ ] **Step 1: Subir para 0.7.0**

`pyproject.toml` e topo de `docs/versoes.yaml`:

```yaml
- versao: "0.7.0"
  data: "2026-08-19"
  adicionado:
    - >-
      Grupo Telemetria no menu, reunindo o que vem da plataforma Gobrax.
    - >-
      A Premiação passou a usar a nota da Gobrax e o km rodado, com valor por km
      configurável na própria tela.
  alterado:
    - >-
      A premiação deixou de ser calculada por litros economizados: a API pública
      da Gobrax não fornece a média de consumo por motorista. Meses já pagos
      continuam exibindo o valor com que foram pagos.
    - >-
      A coleta deixou de fazer login na plataforma e passou a usar a API oficial
      com token, o que elimina o bloqueio por excesso de logins.
```

- [ ] **Step 2: Gerar o CHANGELOG**

Run: `uv run python scripts/gerar_changelog.py`

- [ ] **Step 3: Documentação**

Em `docs/manual.yaml`, crie o grupo Telemetria com `telas: [prem]` e atualize o
verbete de premiação para a regra nova. Em `CLAUDE.md`, seção 3, acrescente o
módulo `telemetria`. **O teste `test_toda_tela_do_painel_esta_em_algum_grupo`
falha se a tela ficar fora de grupo.**

- [ ] **Step 4: Rodar a suíte e commitar**

```bash
uv run pytest -q
git add -A
git commit -m "feat(telemetria): versao 0.7.0 e documentacao"
```

---

## Fora do escopo desta entrega

As três telas novas (Consumo e Estatísticas, Condução Econômica, Hodômetro e
Rastro) ficam para a entrega B, que depende da arquitetura de coleta em segundo
plano — `vehicle-statistics` leva 73 s para a frota e `vehicle-performance` exige
uma chamada por veículo.

O `api/premiacao/gobrax.py` antigo (login Kratos) só é removido quando a coleta
nova estiver validada em produção; até lá fica no repositório, sem uso.
