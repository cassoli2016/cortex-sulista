# Premiação de Motoristas (Fase 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tela `prem` "Premiação de Motoristas" no Cortex: coleta média/nota da API Gobrax v3 (customer 1), aplica a regra de litros economizados com parâmetros editáveis e mostra ranking, indicadores e comparativo mensal.

**Architecture:** Novo subpacote `api/premiacao/` (cliente Gobrax em stdlib, coleta → snapshots mensais em `data/premiacao/`, cálculo puro, params em JSON), 3 endpoints em `api/main.py`, RBAC seed v18 e uma vista nova na SPA `api/static/index.html`.

**Tech Stack:** Python 3 (stdlib `urllib.request` — SEM requests/httpx), FastAPI, SQLite não é usado aqui (JSON), vanilla JS na SPA, pytest, Playwright para validação.

## Global Constraints

- **Branch:** todo o trabalho em `feat/premiacao-motoristas` (criar a partir de `main` na Task 1). NÃO fazer push/merge — isso é decisão do usuário no fim.
- **Spec:** `docs/superpowers/specs/2026-07-27-premiacao-motoristas-design.md` governa. Divergência = perguntar.
- **ERP AVA é réplica somente-leitura** (PG 9.3). Este módulo só faz UMA leitura nele (preço do diesel interno, §Task 5) — read-only como tudo.
- **HTTP só com `urllib.request`** (stdlib). O venv NÃO tem `requests`/`httpx`; um import de `requests` já derrubou a aplicação em produção uma vez.
- **Gateway Gobrax rejeita `%3A`**: todo datetime em query string vai com `:` literal — `urllib.parse.urlencode(params, safe=":,")`.
- **Credenciais** só em `GOBRAX_EMAIL`/`GOBRAX_SENHA` (os.environ; o `.env` é carregado por `api/db.py` no import). Valores NUNCA aparecem em print, log, teste, commit ou resposta HTTP.
- **CPF nunca cru**: mascarar com `api.queries._mask_doc` ANTES de gravar snapshot. Nenhum CPF cru em disco, payload ou HTML.
- **Front:** campo numérico decimal = `type="text" inputmode="decimal"` + `numBR()` (nunca `type="number"`, nunca `parseFloat` cru). Validar `.py` com `ast.parse` antes de gravar; validar o `<script>` do `index.html` com `node --check` depois de cada edição. Edições no `index.html` por substituição literal de trecho conhecido (NUNCA regex em massa).
- **Cálculo sem arredondamento intermediário**: só o prêmio final arredonda a 2 casas. Exemplo canônico: km 5.000 · meta 1,90 · média 2,10 · R$ 6/l · 20% → **R$ 300,75**.
- **Suíte atual tem 132 testes** — todos continuam passando após cada task. Rodar: `uv run --with pytest python -m pytest tests/ -q`.
- Commits pequenos ao fim de cada task, mensagem em pt-BR (padrão do repo).

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `api/premiacao/__init__.py` | vazio (marca o pacote) |
| `api/premiacao/calculo.py` | PURO: regra de litros economizados + KPIs |
| `api/premiacao/params.py` | ler/gravar `data/premiacao_params.json` com validação |
| `api/premiacao/gobrax.py` | cliente mínimo da API v3 (login Kratos + headers + retry 401) |
| `api/premiacao/coleta.py` | coleta 1 mês → snapshot JSON + índice em `data/premiacao/` |
| `api/premiacao/servico.py` | orquestra: snapshot (TTL/lock/fallback) + cálculo + referências |
| `api/main.py` | 3 endpoints `/api/frota/premiacao*` |
| `api/auth.py` | tela `prem` + rota + perfis + migração `perfis_modelo_v18` |
| `api/static/index.html` | vista `prem` (sidebar, gaveta, loaders, cards) |
| `tests/premiacao/*.py` | testes por módulo |

---

### Task 1: Cálculo puro da premiação

**Files:**
- Create: `api/premiacao/__init__.py` (vazio)
- Create: `api/premiacao/calculo.py`
- Test: `tests/premiacao/__init__.py` (vazio), `tests/premiacao/test_calculo.py`

**Interfaces:**
- Consumes: nada (puro).
- Produces: `calcular(motoristas: list[dict], params: dict) -> dict` com
  `{"linhas": [...], "kpis": {...}, "sem_media": int}`.
  - Entrada `motoristas`: itens com `driverId, driverName, documento, vehicles,
    nota, media, km, indicators` (media/km podem ser None/0).
  - Cada linha de saída = o dict do motorista **+** `litros_meta, litros_consumidos,
    litros_economizados, premio, elegivel` (floats; premio com 2 casas).
  - `kpis`: `premio_total, litros_economizados_total, premiados, elegiveis,
    com_media, total_motoristas, media_frota, meta`.
  - `params`: `{"meta": float, "preco_litro": float, "pct_premiacao": float, "km_minimo": float}`.

- [ ] **Step 1: Criar branch e escrever os testes**

```bash
git checkout -b feat/premiacao-motoristas
mkdir -p api/premiacao tests/premiacao
touch api/premiacao/__init__.py tests/premiacao/__init__.py
```

`tests/premiacao/test_calculo.py`:

```python
"""Regra de premiação por litros economizados (spec §1). Módulo puro."""
from __future__ import annotations

from api.premiacao.calculo import calcular

PARAMS = {"meta": 1.90, "preco_litro": 6.0, "pct_premiacao": 0.20, "km_minimo": 500.0}


def _mot(**kw):
    base = {"driverId": 1, "driverName": "3797 - GABRIEL", "documento": "18•••••05",
            "vehicles": [{"plate": "FQJ8H55", "model": "DAF"}],
            "nota": 80, "media": 2.10, "km": 5000.0, "indicators": {}}
    base.update(kw)
    return base


def test_exemplo_canonico_da_spec_sem_arredondamento_intermediario():
    """km 5.000 · meta 1,90 · média 2,10 · R$6/l · 20% → R$ 300,75.

    O doc do MVP mostra 300,60 porque arredonda o valor economizado para 1.503
    ANTES do percentual — a spec manda NÃO reproduzir esse arredondamento."""
    r = calcular([_mot()], PARAMS)
    l = r["linhas"][0]
    assert l["premio"] == 300.75
    assert round(l["litros_economizados"], 2) == 250.63
    assert l["elegivel"] is True


def test_media_abaixo_da_meta_da_premio_zero_mas_linha_aparece():
    r = calcular([_mot(media=1.70)], PARAMS)
    l = r["linhas"][0]
    assert l["premio"] == 0.0
    assert l["litros_economizados"] == 0.0
    assert len(r["linhas"]) == 1          # desempenho abaixo da meta é informação


def test_km_abaixo_do_minimo_nao_e_elegivel_nem_soma_no_premio_total():
    r = calcular([_mot(km=300.0)], PARAMS)
    l = r["linhas"][0]
    assert l["elegivel"] is False
    assert r["kpis"]["premio_total"] == 0.0   # não elegível não entra no total
    assert l["premio"] > 0                    # mas a linha mostra quanto SERIA


def test_km_minimo_zero_desliga_o_corte():
    r = calcular([_mot(km=10.0)], {**PARAMS, "km_minimo": 0})
    assert r["linhas"][0]["elegivel"] is True


def test_sem_media_fica_fora_das_linhas_e_e_contado():
    r = calcular([_mot(), _mot(driverId=2, media=None), _mot(driverId=3, media=0)], PARAMS)
    assert len(r["linhas"]) == 1
    assert r["sem_media"] == 2
    assert r["kpis"]["total_motoristas"] == 3
    assert r["kpis"]["com_media"] == 1


def test_kpis_agregados_e_media_da_frota_ponderada():
    """media_frota = km total ÷ litros consumidos totais (ponderada por km)."""
    r = calcular([_mot(), _mot(driverId=2, media=1.90, km=1900.0)], PARAMS)
    k = r["kpis"]
    # litros: 5000/2.1=2380.95 + 1900/1.9=1000 → media_frota = 6900/3380.95 = 2.0409...
    assert round(k["media_frota"], 4) == round(6900.0 / (5000.0 / 2.1 + 1000.0), 4)
    assert k["premiados"] == 1                # o 2º tem prêmio 0
    assert k["elegiveis"] == 2
    assert k["premio_total"] == 300.75
    assert k["meta"] == 1.90


def test_ordena_por_premio_depois_km():
    r = calcular([_mot(driverId=1, media=1.95, km=8000.0),
                  _mot(driverId=2, media=2.30, km=3000.0),
                  _mot(driverId=3, media=1.70, km=9000.0)], PARAMS)
    assert [l["driverId"] for l in r["linhas"]] == [2, 1, 3]
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run --with pytest python -m pytest tests/premiacao/ -q` → FAIL (módulo não existe).

- [ ] **Step 3: Implementar `api/premiacao/calculo.py`**

```python
"""Regra de premiação por litros economizados (spec §1). Módulo PURO.

premio = max(0, km/meta - km/media) × preco_litro × pct_premiacao
Sem arredondamento intermediário: só o prêmio final arredonda a 2 casas
(o exemplo do MVP dava 300,60 por arredondar o valor economizado antes do
percentual; aqui o canônico é 300,75).
"""
from __future__ import annotations


def calcular(motoristas: list[dict], params: dict) -> dict:
    meta = float(params["meta"])
    preco = float(params["preco_litro"])
    pct = float(params["pct_premiacao"])
    km_min = float(params.get("km_minimo") or 0)

    linhas: list[dict] = []
    sem_media = 0
    for m in motoristas:
        media = m.get("media") or 0
        if media <= 0:
            sem_media += 1
            continue
        km = float(m.get("km") or 0)
        litros_meta = km / meta
        litros_cons = km / media
        econ = max(0.0, litros_meta - litros_cons)
        linhas.append({
            **m,
            "litros_meta": litros_meta,
            "litros_consumidos": litros_cons,
            "litros_economizados": econ,
            "premio": round(econ * preco * pct, 2),
            "elegivel": km >= km_min,
        })

    linhas.sort(key=lambda l: (-l["premio"], -float(l.get("km") or 0)))
    eleg = [l for l in linhas if l["elegivel"]]
    litros_cons_total = sum(l["litros_consumidos"] for l in linhas)
    km_total = sum(float(l.get("km") or 0) for l in linhas)
    kpis = {
        "premio_total": round(sum(l["premio"] for l in eleg), 2),
        "litros_economizados_total": round(sum(l["litros_economizados"] for l in eleg), 2),
        "premiados": sum(1 for l in eleg if l["premio"] > 0),
        "elegiveis": len(eleg),
        "com_media": len(linhas),
        "total_motoristas": len(motoristas),
        "media_frota": (km_total / litros_cons_total) if litros_cons_total else None,
        "meta": meta,
    }
    return {"linhas": linhas, "kpis": kpis, "sem_media": sem_media}
```

- [ ] **Step 4: Rodar tudo** — `uv run --with pytest python -m pytest tests/ -q` → 132 + 7 novos passando.
- [ ] **Step 5: Commit** — `git add api/premiacao tests/premiacao && git commit -m "Premiação: cálculo puro da regra de litros economizados"`

---

### Task 2: Parâmetros persistidos

**Files:**
- Create: `api/premiacao/params.py`
- Test: `tests/premiacao/test_params.py`

**Interfaces:**
- Produces: `DEFAULTS` (dict), `ler_params(path: Path | None = None) -> dict`,
  `salvar_params(novos: dict, path: Path | None = None) -> dict` (ValueError com
  mensagem pt-BR se inválido; grava e devolve o efetivo).
- `PARAMS_PATH = ROOT / "data" / "premiacao_params.json"` (ROOT = raiz do repo,
  mesmo padrão de `api/orcamento/armazenamento.py`).

- [ ] **Step 1: Testes** — `tests/premiacao/test_params.py`:

```python
from __future__ import annotations

import json

import pytest

from api.premiacao.params import DEFAULTS, ler_params, salvar_params


def test_arquivo_ausente_devolve_defaults(tmp_path):
    p = ler_params(tmp_path / "nao_existe.json")
    assert p == DEFAULTS
    assert p["meta"] == 2.0 and p["preco_litro"] == 4.93
    assert p["pct_premiacao"] == 0.20 and p["km_minimo"] == 500.0


def test_round_trip_e_merge_com_defaults(tmp_path):
    f = tmp_path / "params.json"
    salvar_params({"meta": 2.2}, f)
    p = ler_params(f)
    assert p["meta"] == 2.2
    assert p["pct_premiacao"] == 0.20          # não informado mantém default
    salvar_params({"pct_premiacao": 0.25}, f)
    p2 = ler_params(f)
    assert p2["meta"] == 2.2 and p2["pct_premiacao"] == 0.25


def test_validacao_rejeita_valores_impossiveis(tmp_path):
    f = tmp_path / "params.json"
    for ruim in ({"meta": 0}, {"meta": -1}, {"preco_litro": 0},
                 {"pct_premiacao": 1.5}, {"pct_premiacao": -0.1}, {"km_minimo": -5}):
        with pytest.raises(ValueError):
            salvar_params(ruim, f)
    assert not f.exists()                       # inválido não grava


def test_chave_desconhecida_e_ignorada(tmp_path):
    f = tmp_path / "params.json"
    salvar_params({"meta": 2.1, "hacker": "x"}, f)
    assert "hacker" not in json.loads(f.read_text())
```

- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar `api/premiacao/params.py`**

```python
"""Parâmetros da premiação — data/premiacao_params.json, editáveis pela tela."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_PATH = ROOT / "data" / "premiacao_params.json"

DEFAULTS = {"meta": 2.0, "preco_litro": 4.93, "pct_premiacao": 0.20, "km_minimo": 500.0}


def _valida(p: dict) -> None:
    if p["meta"] <= 0:
        raise ValueError("A meta (km/l) tem de ser maior que zero.")
    if p["preco_litro"] <= 0:
        raise ValueError("O preço do litro tem de ser maior que zero.")
    if not (0 <= p["pct_premiacao"] <= 1):
        raise ValueError("O percentual de premiação vai de 0 a 1 (ex.: 0,20 = 20%).")
    if p["km_minimo"] < 0:
        raise ValueError("O km mínimo não pode ser negativo.")


def ler_params(path: Path | None = None) -> dict:
    path = Path(path or PARAMS_PATH)
    atual = dict(DEFAULTS)
    if path.exists():
        try:
            gravado = json.loads(path.read_text(encoding="utf-8"))
            atual.update({k: float(gravado[k]) for k in DEFAULTS if k in gravado})
        except (json.JSONDecodeError, TypeError, ValueError):
            pass  # arquivo corrompido não derruba a tela: volta aos defaults
    return atual


def salvar_params(novos: dict, path: Path | None = None) -> dict:
    path = Path(path or PARAMS_PATH)
    efetivo = ler_params(path)
    efetivo.update({k: float(novos[k]) for k in DEFAULTS if k in novos})
    _valida(efetivo)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(efetivo, ensure_ascii=False, indent=2), encoding="utf-8")
    return efetivo
```

- [ ] **Step 4: Rodar tudo.**
- [ ] **Step 5: Commit** — `git commit -m "Premiação: parâmetros persistidos com validação"`

---

### Task 3: Cliente Gobrax v3 (stdlib)

**Files:**
- Create: `api/premiacao/gobrax.py`
- Test: `tests/premiacao/test_gobrax.py`

**Interfaces:**
- Produces:
  - `configurado() -> bool` — True se `GOBRAX_EMAIL` e `GOBRAX_SENHA` estão no ambiente.
  - `class GobraxNaoConfigurado(RuntimeError)` / `class GobraxIndisponivel(RuntimeError)`.
  - `class ClienteGobrax(email=None, senha=None, http=None)` com `get(path: str, params: dict | None = None) -> dict`.
    `http` é injetável para teste: `http(url, method, headers, body_dict|None) -> (status:int, body:dict)`.
- Constantes: `GATEWAY = "https://gateway-v3-waf.gobrax.com.br"`,
  `KRATOS_LOGIN = "https://v3.gobrax.com.br/safekratos/self-service/login/api"`,
  `ORIGIN_VERSION = "WEB 3.1"`.

**Fluxo de login (portado de `Endpoints_v3/gobrax_auth.py`, confirmado funcional):**
1. `GET KRATOS_LOGIN` → JSON com `methods.password.config.action` (+ `fields` com `csrf_token`, normalmente vazio no fluxo api).
2. `POST <action>` com `{"identifier": email, "password": senha, "method": "password"}` (+ csrf se veio) → JSON com `session`.
3. Token = `base64(json.dumps(session, separators=(",",":"), ensure_ascii=False))`.
4. `GET {GATEWAY}/user/{email}` com `Authorization: Bearer <token>` + `OriginVersion` → `data.token` = header `Credentials`.
5. Toda chamada leva os 3 headers; **401 → refaz login UMA vez** e repete.

- [ ] **Step 1: Testes** — `tests/premiacao/test_gobrax.py`:

```python
from __future__ import annotations

import base64
import json

import pytest

from api.premiacao import gobrax
from api.premiacao.gobrax import ClienteGobrax, GobraxIndisponivel


def _http_fabrica(respostas: list, chamadas: list):
    """Stub: cada item de `respostas` é (status, body); registra as chamadas."""
    def http(url, method, headers, body):
        chamadas.append({"url": url, "method": method, "headers": dict(headers), "body": body})
        st, bd = respostas.pop(0)
        return st, bd
    return http


def _fluxo_login():
    sess = {"id": "abc", "identity": {"id": "u1"}}
    tok = base64.b64encode(json.dumps(sess, separators=(",", ":")).encode()).decode()
    return [
        (200, {"methods": {"password": {"config": {"action": "https://v3.gobrax.com.br/login-action", "fields": []}}}}),
        (200, {"session": sess}),
        (200, {"data": {"token": "jwt-cred"}}),
    ], tok


def test_query_mantem_dois_pontos_literal_e_headers_completos():
    respostas, tok = _fluxo_login()
    respostas.append((200, {"ok": True}))
    chamadas = []
    c = ClienteGobrax(email="e@x.com", senha="s3nh4-de-teste", http=_http_fabrica(respostas, chamadas))
    c.get("/web/v2/performance/drivers/analysis",
          {"drivers": "1,2", "startDate": "2026-07-01T00:00:00Z"})
    ultima = chamadas[-1]
    assert "startDate=2026-07-01T00:00:00Z" in ultima["url"]      # ':' literal
    assert "%3A" not in ultima["url"]
    assert ultima["headers"]["Authorization"] == f"Bearer {tok}"
    assert ultima["headers"]["Credentials"] == "jwt-cred"
    assert ultima["headers"]["OriginVersion"] == "WEB 3.1"


def test_401_renova_o_login_uma_vez_e_repete():
    respostas, _ = _fluxo_login()
    respostas.append((401, {}))          # 1ª tentativa
    r2, _ = _fluxo_login()
    respostas += r2                      # relogin
    respostas.append((200, {"ok": 1}))   # repetição
    chamadas = []
    c = ClienteGobrax(email="e@x.com", senha="s", http=_http_fabrica(respostas, chamadas))
    assert c.get("/drivers", {"customers": 1}) == {"ok": 1}
    assert len(chamadas) == 8            # 3 login + 1 falha + 3 relogin + 1 ok


def test_falha_de_login_vira_gobrax_indisponivel():
    c = ClienteGobrax(email="e@x.com", senha="s",
                      http=_http_fabrica([(500, {})], []))
    with pytest.raises(GobraxIndisponivel):
        c.get("/drivers")


def test_sem_credenciais_no_ambiente(monkeypatch):
    monkeypatch.delenv("GOBRAX_EMAIL", raising=False)
    monkeypatch.delenv("GOBRAX_SENHA", raising=False)
    assert gobrax.configurado() is False
    monkeypatch.setenv("GOBRAX_EMAIL", "e@x.com")
    monkeypatch.setenv("GOBRAX_SENHA", "s")
    assert gobrax.configurado() is True
```

- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar `api/premiacao/gobrax.py`** (usar `urllib.request`; o `http`
  default monta `Request(url, headers=headers, method=method)`, timeout 30 s,
  `json.loads` do corpo; capturar `HTTPError` para devolver `(e.code, {})` e
  `URLError` → `GobraxIndisponivel`). Estrutura:

```python
"""Cliente mínimo da API Gobrax v3 (stdlib) — login Kratos + 3 headers do gateway.

Credenciais SÓ via GOBRAX_EMAIL/GOBRAX_SENHA (os.environ; o .env é carregado por
api.db no import). Valores nunca aparecem em log ou erro. HTTP com urllib.request
porque o venv não tem requests/httpx (import de requests já derrubou a app).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlencode

GATEWAY = "https://gateway-v3-waf.gobrax.com.br"
KRATOS_LOGIN = "https://v3.gobrax.com.br/safekratos/self-service/login/api"
ORIGIN_VERSION = "WEB 3.1"


class GobraxNaoConfigurado(RuntimeError):
    pass


class GobraxIndisponivel(RuntimeError):
    pass


def configurado() -> bool:
    return bool(os.environ.get("GOBRAX_EMAIL") and os.environ.get("GOBRAX_SENHA"))


def _http_urllib(url: str, method: str, headers: dict, body: dict | None):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = dict(headers)
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            corpo = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            corpo = {}
        return e.code, corpo
    except urllib.error.URLError as e:
        raise GobraxIndisponivel(f"Sem conexão com a API Gobrax: {e.reason}") from e


class ClienteGobrax:
    def __init__(self, email: str | None = None, senha: str | None = None, http=None):
        self.email = email or os.environ.get("GOBRAX_EMAIL", "")
        self._senha = senha or os.environ.get("GOBRAX_SENHA", "")
        if not (self.email and self._senha):
            raise GobraxNaoConfigurado(
                "Defina GOBRAX_EMAIL e GOBRAX_SENHA no .env para habilitar a coleta.")
        self._http = http or _http_urllib
        self._token: str | None = None
        self._cred: str | None = None

    # -- autenticação ------------------------------------------------------
    def _login(self) -> None:
        st, flow = self._http(KRATOS_LOGIN, "GET", {"Accept": "application/json"}, None)
        if st >= 400:
            raise GobraxIndisponivel(f"Login Gobrax falhou no flow (HTTP {st}).")
        cfg = (flow.get("methods") or {}).get("password", {}).get("config", {})
        action = cfg.get("action")
        payload = {"identifier": self.email, "password": self._senha, "method": "password"}
        csrf = next((f.get("value") for f in cfg.get("fields", [])
                     if f.get("name") == "csrf_token" and f.get("value")), None)
        if csrf:
            payload["csrf_token"] = csrf
        st, data = self._http(action, "POST", {"Accept": "application/json"}, payload)
        sess = (data or {}).get("session")
        if st >= 400 or not sess:
            # nunca ecoar a resposta: pode conter dados da conta
            raise GobraxIndisponivel(f"Login Gobrax recusado (HTTP {st}). Confira as credenciais no .env.")
        tok_json = json.dumps(sess, separators=(",", ":"), ensure_ascii=False)
        self._token = base64.b64encode(tok_json.encode("utf-8")).decode("ascii")
        st, user = self._http(f"{GATEWAY}/user/{self.email}", "GET",
                              self._headers(sem_cred=True), None)
        self._cred = ((user or {}).get("data") or {}).get("token")
        if st >= 400 or not self._cred:
            raise GobraxIndisponivel(f"Não obtive o header Credentials (HTTP {st}).")

    def _headers(self, sem_cred: bool = False) -> dict:
        h = {"Accept": "application/json", "Authorization": f"Bearer {self._token}",
             "OriginVersion": ORIGIN_VERSION}
        if not sem_cred and self._cred:
            h["Credentials"] = self._cred
        return h

    # -- chamadas ----------------------------------------------------------
    def get(self, path: str, params: dict | None = None) -> dict:
        if self._token is None:
            self._login()
        url = f"{GATEWAY}{path}"
        if params:
            url += "?" + urlencode(params, safe=":,")   # gateway rejeita %3A
        st, body = self._http(url, "GET", self._headers(), None)
        if st == 401:                                    # token expirou (~24h)
            self._login()
            st, body = self._http(url, "GET", self._headers(), None)
        if st >= 400:
            raise GobraxIndisponivel(f"API Gobrax devolveu HTTP {st} em {path}.")
        return body
```

- [ ] **Step 4: Rodar tudo** (`ast.parse` antes de gravar; suíte completa verde).
- [ ] **Step 5: Commit** — `git commit -m "Premiação: cliente Gobrax v3 em stdlib com login Kratos e retry em 401"`

---

### Task 4: Coleta mensal → snapshot

**Files:**
- Create: `api/premiacao/coleta.py`
- Test: `tests/premiacao/test_coleta.py`

**Interfaces:**
- Consumes: `ClienteGobrax.get` (Task 3), `api.queries._mask_doc`.
- Produces:
  - `SNAP_DIR = ROOT / "data" / "premiacao"`
  - `coletar_mes(cliente, mes: str, customer: int = 1, agora=None) -> dict` (snapshot).
  - `gravar_snapshot(snap: dict, dir_path=None) -> Path` (grava mensal + reescreve `index.json`).
  - `ler_snapshot(mes: str, dir_path=None) -> dict | None` · `ler_index(dir_path=None) -> list[dict]`.
- Shape do snapshot (o front e o serviço dependem DESTES nomes):

```json
{"source": "gobrax-v3", "customerId": 1, "month": "2026-07",
 "periodStart": "2026-07-01T00:00:00Z", "periodEnd": "2026-07-31T23:59:59Z",
 "coletado_em": "2026-07-27 08:10", "parcial": true,
 "frota_telemetria": {"veiculos": 9, "com_motorista": 3},
 "drivers": [{"driverId": 87798, "driverName": "3797 - GABRIEL ...",
   "documento": "18•••••05", "vehicles": [{"plate": "FQJ8H55", "model": "DAF/XF"}],
   "nota": 80, "media": 5.33, "km": 6756.61,
   "indicators": {"scores": {...}, "percentages": {...}, "extra": {...}}}]}
```

**Chamadas (shapes reais confirmados em 2026-07-27):**
1. `GET /vehicles` `{"customers": customer, "operation": "true"}` →
   `{"customers": [{"vehicles": [{"id", "plate", "truckModel"|"model"|"brand", "currentDriver": {"driverId", "driverName"}}]}]}`.
2. `GET /drivers` `{"customers": customer}` → `{"drivers": [{"id", "documentNumber", ...}]}`.
3. `GET /web/v2/performance/drivers/analysis`
   `{"drivers": "<ids do lote>", "vehicles": "<TODOS os ids>", "startDate": ..., "endDate": ...}`
   em **lotes de 10 motoristas** com `time.sleep(0.3)` entre lotes →
   `{"data": {"performances": [{"driverId", "driverName", "scores": {...generalScore},
   "percentages": {...}, "stats": {"totalMileage", "consumptionAverage",
   "totalConsumption", "averageSpeed", "odometer"}}]}`.

**Regras:**
- Motoristas consultados = os que têm `currentDriver` em algum veículo (piloto);
  `vehicles=` leva TODOS os veículos do cliente (a média casa por telemetria).
- `documento` = `_mask_doc(documentNumber)` — o CPF cru NÃO entra no snapshot.
- Motorista sem média (`consumptionAverage` 0/None) ENTRA no snapshot com
  `media: None` (o cálculo o exclui e conta) — o snapshot é dado bruto.
- Mês corrente (`mes == agora.strftime('%Y-%m')`): `periodEnd` = agora em ISO Z,
  `parcial: true`. Mês fechado: último dia 23:59:59Z, `parcial: false`.
- `index.json` = lista `[{"month", "label", "drivers", "parcial"}]` ordenada
  decrescente; `label` = "Julho / 2026" (usar a lista MESES pt-BR do coletor do MVP).

- [ ] **Step 1: Testes** — `tests/premiacao/test_coleta.py` com cliente FAKE:

```python
from __future__ import annotations

import json
from datetime import datetime

from api.premiacao.coleta import coletar_mes, gravar_snapshot, ler_index, ler_snapshot


class FakeCliente:
    """Devolve os shapes reais da API para 2 motoristas / 3 veículos."""
    def __init__(self):
        self.chamadas = []

    def get(self, path, params=None):
        self.chamadas.append((path, dict(params or {})))
        if path == "/vehicles":
            return {"customers": [{"vehicles": [
                {"id": 101, "plate": "AAA1A11", "truckModel": "DAF XF",
                 "currentDriver": {"driverId": 7, "driverName": "3797 - GABRIEL"}},
                {"id": 102, "plate": "BBB2B22", "truckModel": "SCANIA R",
                 "currentDriver": {"driverId": 8, "driverName": "3818 - EDUARDO"}},
                {"id": 103, "plate": "CCC3C33", "truckModel": "VOLVO FH"},
            ]}]}
        if path == "/drivers":
            return {"drivers": [{"id": 7, "documentNumber": "18399788805"},
                                {"id": 8, "documentNumber": "12345678901"}]}
        if path.endswith("/analysis"):
            return {"data": {"performances": [
                {"driverId": 7, "scores": {"generalScore": 80, "idleScore": 82},
                 "percentages": {"idle": {"percentage": 12}},
                 "stats": {"totalMileage": 6756.61, "consumptionAverage": 5.33,
                           "totalConsumption": 1200, "averageSpeed": 55, "odometer": 90000}},
                {"driverId": 8, "scores": {"generalScore": 74},
                 "percentages": {},
                 "stats": {"totalMileage": 1277.97, "consumptionAverage": 0}},
            ]}}
        raise AssertionError(f"chamada inesperada: {path}")


def test_snapshot_mascara_cpf_e_nunca_grava_cru(tmp_path):
    snap = coletar_mes(FakeCliente(), "2026-06", agora=datetime(2026, 7, 27, 8, 0))
    caminho = gravar_snapshot(snap, tmp_path)
    bruto = caminho.read_text(encoding="utf-8")
    assert "18399788805" not in bruto and "12345678901" not in bruto
    d = json.loads(bruto)["drivers"][0]
    assert d["documento"].startswith("18") and "•" in d["documento"]


def test_mes_fechado_e_corrente(tmp_path):
    agora = datetime(2026, 7, 27, 8, 0)
    fechado = coletar_mes(FakeCliente(), "2026-06", agora=agora)
    assert fechado["parcial"] is False
    assert fechado["periodEnd"] == "2026-06-30T23:59:59Z"
    corrente = coletar_mes(FakeCliente(), "2026-07", agora=agora)
    assert corrente["parcial"] is True
    assert corrente["periodEnd"].startswith("2026-07-27")


def test_analysis_recebe_todos_os_veiculos_e_lotes_de_10():
    cli = FakeCliente()
    coletar_mes(cli, "2026-06", agora=datetime(2026, 7, 27))
    path, params = next(c for c in cli.chamadas if c[0].endswith("/analysis"))
    assert params["vehicles"] == "101,102,103"      # TODOS, não só os com motorista
    assert set(params["drivers"].split(",")) == {"7", "8"}


def test_sem_media_entra_no_snapshot_com_media_none():
    snap = coletar_mes(FakeCliente(), "2026-06", agora=datetime(2026, 7, 27))
    por_id = {d["driverId"]: d for d in snap["drivers"]}
    assert por_id[7]["media"] == 5.33 and por_id[7]["nota"] == 80
    assert por_id[8]["media"] is None               # consumptionAverage 0 -> None
    assert por_id[7]["vehicles"] == [{"plate": "AAA1A11", "model": "DAF XF"}]
    assert snap["frota_telemetria"] == {"veiculos": 3, "com_motorista": 2}


def test_index_ordena_do_mais_recente(tmp_path):
    agora = datetime(2026, 7, 27)
    gravar_snapshot(coletar_mes(FakeCliente(), "2026-06", agora=agora), tmp_path)
    gravar_snapshot(coletar_mes(FakeCliente(), "2026-07", agora=agora), tmp_path)
    idx = ler_index(tmp_path)
    assert [i["month"] for i in idx] == ["2026-07", "2026-06"]
    assert idx[1]["label"] == "Junho / 2026"
    assert ler_snapshot("2026-06", tmp_path)["month"] == "2026-06"
    assert ler_snapshot("2099-01", tmp_path) is None
```

- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar `api/premiacao/coleta.py`** seguindo as regras acima
  (usar `calendar.monthrange` para o último dia; `from api.queries import _mask_doc`;
  lotes com uma função `_lotes(seq, n=10)`; `time.sleep(0.3)` entre lotes — no teste
  há 1 lote só, não atrasa). `coletado_em` = `agora.strftime("%Y-%m-%d %H:%M")`;
  `agora=None` → `datetime.now()`.
- [ ] **Step 4: Rodar tudo.**
- [ ] **Step 5: Commit** — `git commit -m "Premiação: coleta mensal da Gobrax com CPF mascarado e snapshot em data/premiacao"`

---

### Task 5: Serviço (TTL/lock/fallback) + endpoints + RBAC v18

**Files:**
- Create: `api/premiacao/servico.py`
- Modify: `api/main.py` (3 endpoints, junto dos endpoints de frota)
- Modify: `api/auth.py` (TELAS, ROTA_TELAS, `_PERFIS_MODELO`, migração v18)
- Test: `tests/premiacao/test_servico.py`; estender `tests/test_auth_migracao.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `servico.obter(mes: str | None = None, force: bool = False, agora=None) -> dict`:

```python
{"configurado": True, "month": "2026-07", "parcial": True,
 "coletado_em": "...", "aviso": None | "coletado em ... — não foi possível atualizar",
 "frota_telemetria": {...}, "index": [...],       # meses disponíveis
 "params": {...}, "referencias": {"preco_diesel_interno": 4.91, "media_frota": 2.04},
 "linhas": [...], "kpis": {...}, "sem_media": 0}
```

**Regras do `obter`:**
- `mes=None` → mês corrente. `gobrax.configurado()` False → `{"configurado": False,
  "variaveis": ["GOBRAX_EMAIL", "GOBRAX_SENHA"], "index": [...]}` (snapshots antigos
  ainda listáveis; NUNCA incluir valores de ambiente).
- Recoleta quando: `force`, OU snapshot inexistente, OU (mês corrente E
  `coletado_em` > 1h atrás). Coleta protegida por `threading.Lock` de módulo —
  quem chega segundo espera e lê o snapshot novo.
- `GobraxIndisponivel`/`GobraxNaoConfigurado` na recoleta: se existe snapshot antigo,
  serve com `aviso`; senão propaga (endpoint → 503).
- `referencias.preco_diesel_interno`: query no AVA (try/except → `None`; ERP fora
  não derruba a tela):

```sql
SELECT (CASE WHEN sum(a.volume) > 0 THEN sum(a.custo)/sum(a.volume) END)::float8 AS preco
FROM sulista.ctaplus_abastecimentos a
WHERE a.data_inicio_abastecimento >= %(de)s::date
  AND a.data_inicio_abastecimento <  %(ate)s::date
  AND a.posto_comercial IS NOT TRUE
  AND coalesce(a.combustivel_descricao,'') NOT ILIKE '%%arla%%'
```

  (`de` = 1º dia do mês, `ate` = 1º dia do mês seguinte; `from api import db`.)
- `referencias.media_frota` = `kpis["media_frota"]` (atalho para o front).

**Endpoints em `api/main.py`** (padrão dos endpoints do orçamento — imports lazy
dentro da função, try/except com mensagens pt):

```python
@app.get("/api/frota/premiacao")
def premiacao(mes: str | None = None) -> JSONResponse:
    from api.premiacao import servico
    from api.premiacao.gobrax import GobraxIndisponivel, GobraxNaoConfigurado
    try:
        return JSONResponse(servico.obter(mes))
    except (GobraxIndisponivel, GobraxNaoConfigurado) as exc:
        return JSONResponse(status_code=503, content={
            "erro": "gobrax_indisponivel", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a premiação."})
```

`POST /api/frota/premiacao/atualizar` (body `{"mes": "2026-07"}` opcional) →
`servico.obter(mes, force=True)`, mesmos handlers.
`POST /api/frota/premiacao/params` → valida body dict, `salvar_params` (ValueError
→ 422 `{"erro": "parametro_invalido", "mensagem": str(exc)}`), devolve
`{"ok": True, "params": efetivo}`.

**RBAC (`api/auth.py`):**
- `TELAS["prem"] = ("Premiação de Motoristas", "Frota")` (junto das telas de Frota).
- `ROTA_TELAS`: `("/api/frota/premiacao", frozenset({"prem"}))` — inserir ANTES de
  qualquer rota `/api/frota/` mais curta que possa engolir o prefixo (conferir a
  ordem existente; seguir o padrão dos vizinhos).
- `_PERFIS_MODELO`: adicionar `"prem"` às listas dos perfis **Frota** e **Diretoria**.
- Migração `perfis_modelo_v18` copiando o bloco v17 (auth.py ~linha 405): para os
  perfis já semeados com nome `Frota` ou `Diretoria`, `INSERT OR IGNORE` da tela
  `prem`; grava a chave `perfis_modelo_v18` na config.

- [ ] **Step 1: Testes do serviço** — `tests/premiacao/test_servico.py`
  (monkeypatch em `servico.SNAP_DIR`→tmp, `servico._novo_cliente`→FakeCliente da
  Task 4 — expor `_novo_cliente()` no servico exatamente para isso —,
  `servico._preco_diesel`→lambda: 4.91, e `gobrax.configurado`):

```python
def test_sem_credenciais_devolve_configurado_false(monkeypatch, tmp_path): ...
    # obter() -> {"configurado": False, "variaveis": [...]}; nada de valores

def test_mes_fechado_com_snapshot_nao_recoleta(monkeypatch, tmp_path): ...
    # grava snapshot 2026-06; _novo_cliente = quebra se chamado; obter("2026-06") ok

def test_mes_corrente_com_snapshot_velho_recoleta(monkeypatch, tmp_path): ...
    # snapshot coletado_em 2h atrás -> FakeCliente é chamado; <1h -> não

def test_gobrax_fora_serve_snapshot_antigo_com_aviso(monkeypatch, tmp_path): ...
    # _novo_cliente lança GobraxIndisponivel; aviso preenchido; linhas vêm do antigo

def test_calculo_aplicado_com_params_atuais(monkeypatch, tmp_path): ...
    # snapshot com media 2.10/km 5000; params meta 1.9/6.0/0.2 -> premio 300.75
```

  (Escrever os 5 completos — os corpos seguem os padrões dos testes das Tasks 2–4.)
- [ ] **Step 2: Teste da migração v18** — em `tests/test_auth_migracao.py`, copiar o
  caso do v17 trocando: chave `perfis_modelo_v18`, tela `prem`, perfis Frota e
  Diretoria (ler o teste v17 antes; mesma mecânica de DB temporário).
- [ ] **Step 3: Ver falhar; implementar `servico.py`, endpoints e RBAC.**
  `ast.parse` em cada `.py` antes de gravar. Conferir
  `uv run python -c "from api import main"` (import não pode quebrar).
- [ ] **Step 4: Rodar a suíte inteira** — tudo verde (132 + novos).
- [ ] **Step 5: Commit** — `git commit -m "Premiação: serviço com TTL/lock/fallback, endpoints e RBAC v18"`

---

### Task 6: Tela `prem` na SPA

**Files:**
- Modify: `api/static/index.html` (todos os pontos de registro + vista + JS)

**Interfaces:**
- Consumes: `GET /api/frota/premiacao?mes=`, `POST .../atualizar`, `POST .../params`
  (shapes da Task 5); `numBR()`/`fmtNumBR` já existem; mini-lib `chartCols` existe.
- Produces: vista `prem` completa.

**Pontos de registro (todos obrigatórios — usar grep para achar cada âncora; são os
mesmos 10 pontos que a tela `orc` tocou):**

1. **Sidebar**: link no grupo Frota, logo após o link de Combustível
   (`grep -n 'comb' api/static/index.html` para achar o bloco `subsFro`).
   Ícone novo `prem` no objeto `ICONS` (24×24, stroke currentColor — um troféu
   simples: taça + base, 2 paths).
2. **Gaveta mobile** (drawer): mesmo link na seção Frota — manter a estrutura
   `h3 + <a>` irmãos (o `aplicarPermissoes` depende dela).
3. **`VIEWS`**: entrada `prem` com título "Premiação de Motoristas".
4. **`VIEW_GROUP`**: `prem:'Fro'`.
5. **`NAV_KW`**: premiação, prêmio, bônus, motorista, economia, km/l, telemetria, gobrax.
6. **`semFilterbar(v)`**: adicionar `'prem'` (a tela tem seletor de mês próprio).
7. **DOIS mapas de loader** (`grep -n 'orc:loadOrc' api/static/index.html` acha os
   dois): adicionar `prem:loadPrem,` em ambos.
8. **`DATAMAP`** (se existir para as demais telas — seguir o padrão de `orc`).
9. **Seção da vista** `<section class="view" id="view-prem">` com:
   - barra própria: `<select id="fPremMes">` + botão `id="btnPremColeta"`
     "Atualizar dados" + `<span id="premColetadoEm">`.
   - card "Parâmetros da regra": 4 inputs `type="text" inputmode="decimal"`
     (`fPremMeta`, `fPremPreco`, `fPremPct`, `fPremKmMin`) com as referências ao
     lado (`média da frota: X km/l` · `diesel interno no mês: R$ Y/l`), botão
     Salvar → `premSalvarParams()`; valores exibidos com vírgula (`fmtNumBR`),
     lidos com `numBR()` (NaN → banner de erro, não envia).
   - `<div class="kpis k4" id="kpis-prem">`.
   - card Ranking: tabela `id="prem-rank"` em `.tablewrap.tabroll` — colunas
     Motorista (nome + placas em mono na 2ª linha), Nota, Km, Média, Litros
     economizados, Prêmio R$. Linha clicável expansível (padrão `forn-row`/
     `forn-det` — grep para copiar a mecânica) mostrando os `indicators.scores`
     como lista nome+nota com semáforo DISCRETO (≥80 verde, 60–79 âmbar, <60
     vermelho — classes `ok/warn/bad` existentes). Não elegível: linha com
     `opacity:.55` + badge `b-warn` "não elegível (km < mínimo)".
   - card Comparativo mensal: `<svg id="chartPrem">` via `chartCols` com séries
     média × meta por mês (dados de `index` + fetch por mês NÃO: usar apenas os
     campos `media_frota`/`premio_total` que o endpoint devolve por mês no
     `index` — **ajuste na Task 5 se necessário**: o `index.json` deve carregar
     `media_frota` e `premio_total` calculados na gravação... **NÃO**: prêmio
     depende dos params atuais. Solução correta e simples: o card comparativo
     busca `GET /api/frota/premiacao?mes=` para cada mês do index (≤ 12 fetches
     de snapshot local, sem recoleta) e monta as colunas. Implementar
     `premComparativo()` async que faz isso após o render principal.
   - banner do piloto (usa `frota_telemetria`): "A telemetria Gobrax cobre N
     veículos e M motoristas — a premiação vale para os vinculados, não para a
     frota inteira."
   - estado `configurado:false`: esconder cards e mostrar instrução (padrão do
     Copiloto sem chave): "Defina GOBRAX_EMAIL e GOBRAX_SENHA no .env e reinicie
     a API." (nomes de variável, nunca valores).
   - `.ihelp` de procedência em TODO card: "API Gobrax v3 · customer 1 ·
     coletado em <coletado_em>". Mês parcial: sub dos KPIs = "mês parcial".
10. **JS**: `let premSeq=0, DATAPREM=null;` + `async function loadPrem()` (padrão
    `loadOrc`: seq guard, skelKpis, fetch com `cache:'no-store'`, popula
    `fPremMes` do `index` UMA vez com `dataset.pronto`, re-render em troca de
    mês), `renderPrem(d)`, `premSalvarParams()`, `premColetar()` (POST atualizar
    com rótulo "Coletando…" e re-load), `premComparativo()`.

**Validações da task:**
- `node --check` no `<script>` após CADA edição.
- Servidor local + Playwright: tela abre sem erro de console; com `.env` sem
  credenciais Gobrax deve mostrar a instrução (estado não configurado) — esta task
  NÃO exige credenciais.
- Smoke: adicionar `prem` à lista de views do validador estrutural do scratchpad
  (`estrutura.py`) e rodar as 33 telas.

- [ ] **Step 1: Registrar os 10 pontos** (sidebar, drawer, ICONS, VIEWS, VIEW_GROUP,
  NAV_KW, semFilterbar, 2 loaders, DATAMAP, seção).
- [ ] **Step 2: Implementar loadPrem/renderPrem + cards.**
- [ ] **Step 3: `node --check` + subir servidor + Playwright (estado não configurado
  e, se houver snapshot de teste local, estado com dados).**
- [ ] **Step 4: Rodar estrutura.py (33 telas) + suíte pytest.**
- [ ] **Step 5: Commit** — `git commit -m "Premiação: tela prem com ranking, parâmetros editáveis e comparativo"`

---

### Task 7: Validação ponta a ponta com a API real

**Files:**
- Modify: `.env` local (fora do git) — adicionar credenciais SEM ecoar valores
- Test: coleta real de jul/2026 + Playwright + screenshot

**Passos:**

- [ ] **Step 1: Credenciais no `.env` local sem expor valores.** O e-mail já está em
  `/Users/cristiancassoli/Projetos_VSCode/Endpoints_v3/.env` (`GOBRAX_EMAIL=...`) e a
  senha no Keychain (service `gobrax-v3`). Anexar ao `.env` do Cortex SEM imprimir:

```bash
cd /Users/cristiancassoli/Projetos_VSCode/Cortex-Sulista/cortex-sulista
grep '^GOBRAX_EMAIL=' /Users/cristiancassoli/Projetos_VSCode/Endpoints_v3/.env >> .env
EMAIL=$(grep '^GOBRAX_EMAIL=' .env | tail -1 | cut -d= -f2)
printf 'GOBRAX_SENHA=%s\n' "$(security find-generic-password -s gobrax-v3 -a "$EMAIL" -w)" >> .env
grep -c '^GOBRAX_' .env   # só a CONTAGEM (deve ser 2); jamais cat/echo dos valores
```

- [ ] **Step 2: Coleta real** — reiniciar o servidor local (`:8099`), abrir `#prem`
  via Playwright; a tela deve coletar jul/2026 (parcial) e mostrar os motoristas do
  piloto. Conferência de sanidade contra a medição do brainstorming (2026-07-27):
  GABRIEL nota 80 · média 5,33 · km 6.756; EDUARDO nota 74. (Valores podem ter
  mudado — o piloto está vivo; conferir ORDEM DE GRANDEZA, não igualdade.)
- [ ] **Step 3: Aceites 1–8 da spec**, um a um:
  1. coleta + ranking com prêmio; 2. editar % 20→25 recalcula sem recoletar
  (comparar `coletado_em` antes/depois); 3. exemplo canônico via teste unitário
  (já coberto); 4. badge não elegível; 5. estado sem credenciais (testado na
  Task 6); 6. Gobrax fora → simular com `GOBRAX_SENHA` errada em processo
  separado NÃO — usar o teste unitário do serviço (já coberto) e conferir o
  banner de aviso com snapshot antigo manualmente se viável; 7.
  `grep -RE '[0-9]{11}' data/premiacao/*.json` não encontra CPF cru (11 dígitos
  contíguos) e o HTML da tela idem via Playwright; 8. pytest + smoke +
  estrutura 33/33.
- [ ] **Step 4: Screenshot full-page para o usuário** (scratchpad).
- [ ] **Step 5: Commit final** — `git commit -m "Premiação: validação ponta a ponta com a API real"` (se houver ajustes).

---

## Self-review (do plano)

- **Cobertura da spec:** §1 regra→T1; params→T2; gobrax→T3; coleta/PII→T4;
  serviço/endpoints/erros/RBAC v18→T5; tela/10 registros/banner/ⓘ→T6;
  aceites/credenciais/produção→T7. Fora de escopo respeitado (sem carregado/vazio,
  sem folha, sem teto).
- **Placeholders:** T5 Step 1 lista os 5 testes por nome com comportamento definido
  (corpos seguem os padrões completos das Tasks 2–4 — decisão consciente para não
  duplicar 150 linhas; o implementer tem os shapes exatos no bloco Interfaces).
- **Consistência de tipos:** `obter()` devolve as chaves que `renderPrem` consome;
  snapshot da T4 alimenta `calcular` da T1 (media None tratado); nomes
  `fPremMes/btnPremColeta/kpis-prem/prem-rank/chartPrem` usados só na T6.
- **Nota ao comparativo (T6):** o prêmio por mês é recalculado com os params ATUAIS
  via GET por mês (snapshots locais, sem recoleta) — decisão registrada no card.
