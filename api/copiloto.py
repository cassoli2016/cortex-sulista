"""Copiloto Cortex — chat sobre os dados do painel via OpenRouter.

Usa modelos FREE do OpenRouter com escolha automática: uma lista de
preferência (maiores/mais capazes) cruzada com o catálogo ao vivo, e
fallback em cadeia quando um modelo estoura rate limit ou falha.

O contexto enviado é um snapshot só de KPIs agregados (escalares) das
telas do painel — nenhuma lista com nomes, placas, CNPJs ou motoristas
sai daqui. A chave vem de OPENROUTER_API_KEY no .env (nunca no código).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta

import json as _json
import urllib.error
import urllib.request

from . import queries

log = logging.getLogger("cortex.copiloto")

OR_BASE = "https://openrouter.ai/api/v1"

# Ordem de preferência (melhores free primeiro); o que não existir mais
# no catálogo é ignorado e o resto do catálogo entra por contexto.
PREFERIDOS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-120b:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
]

_CATALOGO = {"ts": 0.0, "lista": []}
_SNAP = {"ts": 0.0, "texto": ""}


def api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def _http(url: str, payload: dict | None = None, headers: dict | None = None,
          timeout: int = 30) -> tuple[int, dict]:
    """GET/POST JSON com urllib (o venv não tem cliente HTTP de terceiros)."""
    dados = _json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=dados, method="POST" if dados else "GET")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            corpo = _json.loads(exc.read().decode())
        except Exception:  # noqa: BLE001
            corpo = {}
        return exc.code, corpo


def modelos_free() -> list[str]:
    """Modelos :free do catálogo, preferidos primeiro (cache 1h)."""
    if _CATALOGO["lista"] and time.time() - _CATALOGO["ts"] < 3600:
        return _CATALOGO["lista"]
    status, corpo = _http(f"{OR_BASE}/models", timeout=20)
    if status != 200:
        raise RuntimeError(f"catalogo openrouter HTTP {status}")
    todos = {m["id"]: m for m in corpo["data"] if m["id"].endswith(":free")}
    ordem = [m for m in PREFERIDOS if m in todos]
    resto = sorted((i for i in todos if i not in ordem),
                   key=lambda i: -(todos[i].get("context_length") or 0))
    _CATALOGO.update(ts=time.time(), lista=ordem + resto)
    return _CATALOGO["lista"]


def _compacto(d: dict) -> dict:
    """Só valores escalares (e dicts de escalares) — KPIs sem PII."""
    out = {}
    for k, v in d.items():
        if k in ("fonte", "atualizado_em"):
            continue
        if isinstance(v, bool) or isinstance(v, (int, str)):
            out[k] = v
        elif isinstance(v, float):
            out[k] = round(v, 2)
        elif isinstance(v, dict):
            sub = {kk: (round(vv, 2) if isinstance(vv, float) else vv)
                   for kk, vv in v.items()
                   if isinstance(vv, (int, float, str, bool))}
            if sub:
                out[k] = sub
    return out


def _snapshot() -> str:
    """Snapshot de KPIs de todas as telas (cache 120s). Falhas viram nota."""
    if _SNAP["texto"] and time.time() - _SNAP["ts"] < 600:
        return _SNAP["texto"]
    hoje = date.today()
    ini_ano = hoje.replace(month=1, day=1).isoformat()
    fim = hoje.isoformat()
    comp_ate = hoje.strftime("%Y-%m")
    comp_de = (hoje.replace(day=1) - timedelta(days=330)).strftime("%Y-%m")
    fontes = {
        "visao_geral": lambda: queries.get_visao_geral(),
        "financeiro_caixa": lambda: queries.get_overview(),
        "analise_km_ano": lambda: queries.get_analise_km(None, ini_ano, fim),
        "agregados_terceiros_ano": lambda: queries.get_agregados(None, ini_ano, fim),
        "make_vs_buy_12m": lambda: queries.get_make_vs_buy(comp_de, comp_ate),
        "comercial_ano": lambda: queries.get_comercial(None, ini_ano, fim),
        "combustivel_ano": lambda: queries.get_combustivel(ini_ano, fim),
        "manutencao_ano": lambda: queries.get_manutencao(None, ini_ano, fim),
        "multas_ano": lambda: queries.get_multas(ini_ano, fim),
        "torre_seguranca": lambda: queries.get_seguranca(),
        "programacao_disponibilidade": lambda: queries.get_programacao(),
        "frota": lambda: queries.get_veiculos(),
    }
    snap: dict = {"hoje": fim, "periodo_padrao": f"{ini_ano} a {fim} (ano corrente)"}
    falhas = []
    for nome, fn in fontes.items():
        try:
            snap[nome] = _compacto(fn())
        except Exception as exc:  # noqa: BLE001
            falhas.append(nome)
            log.warning("snapshot %s falhou: %s", nome, exc)
    if falhas:
        snap["fontes_indisponiveis"] = falhas
    import json
    _SNAP.update(ts=time.time(), texto=json.dumps(snap, ensure_ascii=False))
    return _SNAP["texto"]


_SISTEMA = """Você é o Copiloto Cortex, assistente de gestão do painel Cortex Sulista \
da Transportadora Sulista S/A (frota mista: própria, locação, agregados e terceiros; \
modalidade lotação/FTL). Você responde perguntas de gestores usando o snapshot de \
indicadores abaixo, extraído ao vivo do ERP.

Regras:
- Responda SEMPRE em português do Brasil, de forma executiva e direta.
- Use apenas números do snapshot; nunca invente valores. Se o dado não estiver no \
snapshot, diga qual tela do painel tem o detalhe (Visão Geral, Fluxo de Caixa, \
Contas a Receber/Pagar, Comercial, Análise de KM, Programação Inteligente, Torre de \
Controle, Torre de Segurança, Agregados e Terceiros, Make vs Buy, Ordens de Compra, \
Combustível, Manutenção, Veículos, Multas).
- Valores em reais (R$), quilômetros e percentuais formatados no padrão brasileiro.
- Seja curto: 1 parágrafo ou poucos bullets; destaque o que exige ação.
- Formatação: markdown simples (negrito e listas), sem tabelas grandes, sem títulos. \
Use emojis com moderação para sinalizar: 📈 melhora, 📉 queda, ⚠️ atenção, ✅ ok, \
💰 dinheiro, 🚛 frota. Comece linhas de recomendação com "> " (viram destaque de ação).
- Encerre SEMPRE com uma última linha neste formato exato (vira botões, não texto): \
SUGESTOES: pergunta curta 1 | pergunta curta 2 | pergunta curta 3

Glossário: km vazio = deslocamento sem carga; % pago s/ frete peso = quanto do frete \
do cliente vai para o agregado/terceiro (margem retida = 100% - esse valor); RKM = \
receita por km carregado; make vs buy = custo do km próprio vs contratado; km evitável \
= km vazio saindo de cidade que tinha carga saindo no mesmo dia.

SNAPSHOT (JSON):
"""


def status_chave() -> dict:
    """Uso e limites da chave no OpenRouter (créditos; modelos :free não
    consomem crédito, mas têm teto diário de requisições)."""
    chave = api_key()
    if not chave:
        return {}
    try:
        st, d = _http(f"{OR_BASE}/key", headers={"Authorization": f"Bearer {chave}"},
                      timeout=15)
        if st != 200:
            return {}
        dados = d.get("data") or {}
        return {
            "free_tier": dados.get("is_free_tier"),
            "creditos_usados": dados.get("usage"),
            "creditos_limite": dados.get("limit"),
        }
    except Exception:  # noqa: BLE001
        return {}


def _montar(mensagens: list[dict], chave: str) -> tuple[list, dict]:
    msgs = [{"role": "system", "content": _SISTEMA + _snapshot()}]
    for m in mensagens[-12:]:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            msgs.append({"role": m["role"], "content": m["content"][:4000]})
    headers = {
        "Authorization": f"Bearer {chave}",
        "HTTP-Referer": "http://127.0.0.1:8000",
        "X-Title": "Cortex Sulista",
    }
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] += ("\n\n(Lembrete do sistema: termine a resposta com a linha "
                                "`SUGESTOES: p1 | p2 | p3` com 3 perguntas curtas de acompanhamento.)")
    return msgs, headers


def stream(mensagens: list[dict]):
    """Gera eventos {tipo: modelo|delta|fim|erro} com a resposta em streaming."""
    chave = api_key()
    if not chave:
        yield {"tipo": "erro", "erro": "sem_chave"}
        return
    if not (_SNAP["texto"] and time.time() - _SNAP["ts"] < 600):
        yield {"tipo": "status", "texto": "consultando o ERP para montar o contexto…"}
    msgs, headers = _montar(mensagens, chave)
    yield {"tipo": "status", "texto": "pensando…"}
    erros = []
    for modelo in modelos_free()[:6]:
        corpo = _json.dumps({
            "model": modelo, "messages": msgs, "max_tokens": 1200,
            "temperature": 0.3, "stream": True,
            "stream_options": {"include_usage": True},
        }).encode()
        req = urllib.request.Request(f"{OR_BASE}/chat/completions", data=corpo, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                yield {"tipo": "erro", "erro": "chave_invalida"}
                return
            erros.append(f"{modelo}: HTTP {exc.code}")
            continue
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{modelo}: {exc.__class__.__name__}")
            continue
        emitiu = False
        tokens = None
        try:
            yield {"tipo": "modelo", "modelo": modelo}
            for raw in resp:
                linha = raw.decode("utf-8", "ignore").strip()
                if not linha.startswith("data: "):
                    continue
                dado = linha[6:]
                if dado == "[DONE]":
                    break
                try:
                    d = _json.loads(dado)
                except ValueError:
                    continue
                uso = d.get("usage")
                if uso:
                    tokens = {"entrada": uso.get("prompt_tokens"),
                              "saida": uso.get("completion_tokens"),
                              "total": uso.get("total_tokens")}
                delta = ((d.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if delta:
                    emitiu = True
                    yield {"tipo": "delta", "texto": delta}
        except Exception as exc:  # noqa: BLE001
            if emitiu:                    # caiu no meio: entrega o que veio
                yield {"tipo": "fim", "tokens": tokens, "truncado": True}
                return
            erros.append(f"{modelo}: {exc.__class__.__name__}")
            continue
        if emitiu:
            yield {"tipo": "fim", "tokens": tokens}
            return
        erros.append(f"{modelo}: sem conteudo")
    yield {"tipo": "erro", "erro": "todos_falharam", "detalhe": "; ".join(erros[-6:])}


def chat(mensagens: list[dict]) -> dict:
    """Envia a conversa ao melhor modelo free disponível, com fallback."""
    chave = api_key()
    if not chave:
        return {"erro": "sem_chave"}
    msgs, headers = _montar(mensagens, chave)
    erros = []
    for modelo in modelos_free()[:6]:
        try:
            status, d = _http(
                f"{OR_BASE}/chat/completions", headers=headers, timeout=90,
                payload={"model": modelo, "messages": msgs,
                         "max_tokens": 1200, "temperature": 0.3})
            if status == 401:
                return {"erro": "chave_invalida"}
            if status != 200:
                erros.append(f"{modelo}: HTTP {status}")
                continue
            texto = (d.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if not texto.strip():
                erros.append(f"{modelo}: resposta vazia")
                continue
            uso = d.get("usage") or {}
            return {"resposta": texto.strip(), "modelo": modelo,
                    "tokens": {"entrada": uso.get("prompt_tokens"),
                               "saida": uso.get("completion_tokens"),
                               "total": uso.get("total_tokens")}}
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{modelo}: {exc.__class__.__name__}")
            continue
    return {"erro": "todos_falharam", "detalhe": "; ".join(erros[-6:])}
