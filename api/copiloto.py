"""Copiloto Cortex — chat sobre os dados do painel via IA LOCAL (Ollama).

Motor principal: Ollama rodando na própria máquina (modelo gemma4) —
nenhum dado sai do servidor. Fallback: se o Ollama estiver fora do ar e
houver OPENROUTER_API_KEY no .env, cai para os modelos FREE do OpenRouter
(catálogo ao vivo + cadeia de fallback), enviando apenas o snapshot de
KPIs agregados (escalares) — nenhuma lista com nomes, placas, CNPJs ou
motoristas sai daqui.

Config no .env: OLLAMA_URL (padrão http://127.0.0.1:11434) e
OLLAMA_MODEL (padrão gemma4). Chaves nunca no código.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta

import json as _json
import urllib.error
import urllib.request

from . import queries

log = logging.getLogger("cortex.copiloto")

OR_BASE = "https://openrouter.ai/api/v1"

# ---- IA local (Ollama) ------------------------------------------------------
# gemma4 tem janela maior, mas o Ollama corta em num_ctx: 16k cobre o snapshot
# de KPIs + histórico sem estourar a RAM da máquina. num_predict = teto de saída
# (2048 evita cortar respostas mais longas no meio; ainda cabe folgado no ctx).
_OLLAMA_OPTS = {"temperature": 0.3, "num_predict": 2048, "num_ctx": 16384}
_OLLAMA_KEEP = "2h"          # mantém o modelo carregado entre perguntas
_OLLAMA_ST = {"ts": 0.0, "ok": False, "modelo": ""}


def ollama_url() -> str:
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def ollama_modelo() -> str:
    return os.environ.get("OLLAMA_MODEL", "gemma4").strip()


def ollama_status(max_age: float = 60.0) -> dict:
    """Verifica se o Ollama responde e se o modelo configurado existe (cache)."""
    if time.time() - _OLLAMA_ST["ts"] < max_age:
        return dict(_OLLAMA_ST)
    ok, modelo = False, ollama_modelo()
    try:
        st, corpo = _http(f"{ollama_url()}/api/tags", timeout=5)
        nomes = [m.get("name", "") for m in (corpo.get("models") or [])] if st == 200 else []
        ok = any(n == modelo or n.split(":")[0] == modelo for n in nomes)
        if st == 200 and not ok:
            log.warning("ollama ativo mas sem o modelo %s (tem: %s)", modelo, nomes)
    except Exception as exc:  # noqa: BLE001
        log.info("ollama indisponível: %s", exc)
    _OLLAMA_ST.update(ts=time.time(), ok=ok, modelo=modelo)
    return dict(_OLLAMA_ST)

# Topo curado da fila. O catalogo :free do OpenRouter ROTACIONA: em 19/08/2026
# quatro dos seis nomes que estavam aqui ja nao existiam. Nome que sumiu e
# simplesmente ignorado (ver modelos_free), entao a lista envelhecer nao derruba
# nada -- mas tambem ninguem percebe, por isso existe
# test_preferidos_ainda_existem_no_catalogo_real, que reclama quando envelhece.
# Mantida CURTA de proposito: o resto do catalogo entra logo atras.
PREFERIDOS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
]

_CATALOGO = {"ts": 0.0, "lista": []}
_SNAP: dict = {"ts": 0.0, "texto": "", "falhas": []}
_SNAP_TTL = 600      # 10 min: o snapshot custa ~12 consultas no ERP

# Telas do painel que compõem o snapshot enviado ao modelo, no rótulo que o
# usuário conhece. O front mostra essa lista no ⓘ de procedência — quem lê a
# resposta precisa saber o que a IA viu (e o que ela NÃO viu).
_FONTES_ROTULO = {
    "visao_geral": "Visão Geral",
    "financeiro_caixa": "Fluxo de Caixa e Bancos",
    "analise_km_ano": "Análise de KM",
    "agregados_terceiros_ano": "Agregados e Terceiros",
    "make_vs_buy_12m": "Make vs Buy",
    "comercial_ano": "Clientes e RKM",
    "combustivel_ano": "Combustível",
    "manutencao_ano": "Manutenção",
    "multas_ano": "Multas",
    "torre_seguranca": "Torre de Segurança",
    "programacao_disponibilidade": "Programação Inteligente",
    "frota": "Veículos",
    "antt_piso": "ANTT — Piso Mínimo de Frete",
    "antt_rntrc": "ANTT — RNTRC dos Transportadores",
    "telemetria_consumo": "Telemetria — Consumo e Estatísticas",
    "premiacao": "Premiação de Motoristas",
    "dre_fechamento": "Fechamento do Mês",
    "pneus": "Pneus",
    "people": "People Analytics",
    "ferias": "Férias — Vencimento",
    "cnh_motoristas": "CNH dos Motoristas",
}


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

    def _porte(ident: str) -> float:
        """Bilhoes de parametros lidos do proprio id ('...-550b-a55b' -> 550).

        Antes o desempate era por context_length, que mede quanto o modelo LE,
        nao quanto ele ACERTA: um modelo pequeno de janela grande subia na fila
        na frente de um grande. Porte e uma proxy melhor para qualidade; quem
        nao declara o tamanho no id cai para o criterio antigo.
        """
        import re as _re
        achados = _re.findall(r"(\d+(?:\.\d+)?)b(?:\b|-)", ident.lower())
        if achados:
            return max(float(a) for a in achados)
        return 0.0

    resto = sorted(
        (i for i in todos if i not in ordem),
        key=lambda i: (-_porte(i), -(todos[i].get("context_length") or 0)))
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


def _e_falha_de_banco(exc: Exception) -> bool:
    """A exceção indica banco inacessível (e não erro daquela consulta)?

    Só o que é claramente de conexão conta: erro de uma query específica não
    pode fazer o snapshot desistir das outras fontes.
    """
    try:
        import psycopg
        if isinstance(exc, psycopg.OperationalError):
            return True
    except Exception:  # noqa: BLE001
        pass
    texto = f"{type(exc).__name__}: {exc}".lower()
    return any(m in texto for m in ("connection", "conexao", "conexão", "timeout",
                                    "could not connect", "pool", "refused"))


def _fontes_do_snapshot() -> dict:
    """Como cada tela vira uma entrada do snapshot.

    Regra para acrescentar fonte aqui: tem de ser LEITURA BARATA. A premiação
    entra sem force -- obter(force=True) sairia para a API da Gobrax e travaria
    o chat por ~18 s; o consumo da telemetria lê o cache local, nunca a API.
    """
    hoje = date.today()
    fim = hoje.isoformat()
    ini_ano = hoje.replace(month=1, day=1).isoformat()
    ini_12m = (hoje - timedelta(days=365)).isoformat()
    comp_ate = hoje.strftime("%Y-%m")
    comp_de = (hoje.replace(day=1) - timedelta(days=330)).strftime("%Y-%m")
    mes_passado = (hoje.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    def _antt_piso():
        from api.antt.servico import get_piso_minimo
        return get_piso_minimo(None, ini_ano, fim)

    def _antt_rntrc():
        from api.antt.rntrc_servico import get_rntrc
        return get_rntrc(ini_12m, fim)

    def _telemetria():
        from api.gobrax.consumo import get_consumo
        return get_consumo(mes_passado)   # o mês corrente pode não ter coleta

    def _premiacao():
        from api.premiacao import servico as prem
        return prem.obter(mes_passado)    # SEM force: nao chamar a Gobrax aqui

    def _fechamento():
        from api.previsao import get_previsao_fechamento
        return get_previsao_fechamento(None)

    def _pneus():
        # LE O INSTANTANEO, nunca a API da Prolog: ela tem cota de ~10
        # requisicoes por janela e uma volta completa custa 86. Abrir o chat
        # nao pode consumir a cota que a coleta agendada precisa.
        from api.pneus import servico as pn
        return pn.obter()

    def _people():
        from api.people import get_people
        return get_people()

    def _ferias():
        from api.queries_folha import get_ferias
        return get_ferias()

    def _cnh():
        from api.queries_folha import get_cnh
        return get_cnh()

    return {
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
        "antt_piso": _antt_piso,
        "antt_rntrc": _antt_rntrc,
        "telemetria_consumo": _telemetria,
        "premiacao": _premiacao,
        "dre_fechamento": _fechamento,
        "pneus": _pneus,
        "people": _people,
        "ferias": _ferias,
        "cnh_motoristas": _cnh,
    }


def _snapshot() -> str:
    """Snapshot de KPIs de todas as telas (cache _SNAP_TTL). Falhas viram nota
    no prompt E ficam registradas para o ⓘ de procedência do front."""
    if _SNAP["texto"] and time.time() - _SNAP["ts"] < _SNAP_TTL:
        return _SNAP["texto"]
    hoje = date.today()
    fim = hoje.isoformat()
    ini_ano = hoje.replace(month=1, day=1).isoformat()
    fontes = _fontes_do_snapshot()
    snap: dict = {"hoje": fim, "periodo_padrao": f"{ini_ano} a {fim} (ano corrente)"}
    falhas = []
    banco_fora = False
    for nome, fn in fontes.items():
        if banco_fora:
            # FAIL-FAST: com o banco inacessivel, cada fonte espera o timeout de
            # conexao. Medido em 19/08/2026: 16 fontes em sequencia = 240 s de
            # chat travado antes da primeira palavra. Se a primeira ja falhou por
            # conexao, as outras vao falhar igual -- nao ha por que pagar o
            # timeout de todas.
            falhas.append(nome)
            continue
        try:
            snap[nome] = _compacto(fn())
        except Exception as exc:  # noqa: BLE001
            falhas.append(nome)
            log.warning("snapshot %s falhou: %s", nome, exc)
            if _e_falha_de_banco(exc):
                banco_fora = True
                log.warning("banco inacessivel: pulando as fontes restantes")
    if falhas:
        snap["fontes_indisponiveis"] = falhas
    import json
    _SNAP.update(ts=time.time(), texto=json.dumps(snap, ensure_ascii=False),
                 falhas=falhas)
    return _SNAP["texto"]


def contexto() -> dict:
    """Procedência do que o modelo enxerga — some no /status para o front.

    Antes a falha de uma fonte ia só para o log e para o prompt: o gestor lia
    uma resposta sem saber que faltava uma tela dentro dela.
    """
    ts = _SNAP["ts"]
    return {
        "telas": len(_FONTES_ROTULO),
        "fontes": list(_FONTES_ROTULO.values()),
        "snapshot_em": (datetime.fromtimestamp(ts).isoformat(timespec="seconds")
                        if ts else None),
        "idade_s": int(time.time() - ts) if ts else None,
        "ttl_s": _SNAP_TTL,
        "indisponiveis": [_FONTES_ROTULO.get(f, f) for f in _SNAP.get("falhas", [])],
        "so_escalares": True,
    }


def _telas_do_painel() -> list[str]:
    """Rótulos das telas, lidos do RBAC.

    Antes essa lista era escrita à mão dentro do prompt e envelheceu: quem
    perguntava sobre ANTT, Telemetria, Orçamento ou Extrato ouvia que a tela não
    existia. api.auth.TELAS é a fonte real do que o painel tem.
    """
    try:
        from api.auth import TELAS
        return sorted({rotulo for rotulo, _grupo in TELAS.values()})
    except Exception:  # noqa: BLE001
        return []


_SISTEMA_BASE = """Você é o Copiloto Cortex, assistente de gestão do painel Cortex Sulista \
(Transportadora Sulista S/A, frota mista própria + agregados, modalidade lotação/FTL). \
Você responde perguntas de gestores usando o snapshot de indicadores abaixo, extraído \
do ERP e da telemetria.

Regras:
- Responda SEMPRE em português do Brasil, de forma executiva e direta.
- Use apenas números do snapshot; nunca invente valores. Se o dado não estiver no \
snapshot, diga em qual tela do painel está o detalhe.
- O snapshot é um RETRATO com até 10 minutos, não tempo real. Quando a pergunta for \
sobre "agora", diga que o número é do último retrato.
- NÃO afirme tendência (subiu, caiu, está melhorando) a partir de um retrato único: \
sem série histórica, compare apenas o que o próprio snapshot traz comparado.
- Número com cobertura parcial precisa vir com a ressalva: se o snapshot disser que \
uma medida foi apurada em parte dos registros, diga isso junto do valor.
- Valores em reais (R$), quilômetros e percentuais no padrão brasileiro.
- Seja curto: 1 parágrafo ou poucos bullets; destaque o que exige ação.
- Formatação: markdown simples (negrito e listas), sem tabelas grandes, sem títulos. \
Use emojis com moderação: 📈 melhora, 📉 queda, ⚠️ atenção, ✅ ok, 💰 dinheiro, 🚛 frota. \
Comece linhas de recomendação com "> " (viram destaque de ação).
- Encerre SEMPRE com uma última linha neste formato exato (vira botões, não texto): \
SUGESTOES: pergunta curta 1 | pergunta curta 2 | pergunta curta 3

Glossário: km vazio = deslocamento sem carga; % pago s/ frete peso = quanto do frete \
do cliente vai para o agregado/terceiro (margem retida = 100% - esse valor); RKM = \
receita por km carregado; make vs buy = custo do km próprio vs contratado; km evitável \
= km vazio saindo de cidade que tinha carga saindo no mesmo dia; piso mínimo ANTT = \
valor legal mínimo do frete contratado; RNTRC = registro do transportador na ANTT.

Telas do painel: {telas}

SNAPSHOT (JSON):
"""


def prompt_sistema() -> str:
    """Prompt com a lista de telas montada na hora, a partir do RBAC."""
    telas = _telas_do_painel()
    return _SISTEMA_BASE.replace("{telas}", ", ".join(telas) if telas else "(indisponível)")


_CHAVE_ST: dict = {"ts": 0.0, "dados": {}}


def status_chave() -> dict:
    """Uso e limites da chave no OpenRouter (créditos; modelos :free não
    consomem crédito, mas têm teto diário de requisições).

    Cache de 120s: o /status passou a ser consultado a cada entrada na tela e
    depois de cada resposta (para mostrar a idade do snapshot) — sem cache isso
    viraria uma chamada externa por navegação.
    """
    chave = api_key()
    if not chave:
        return {}
    if _CHAVE_ST["dados"] and time.time() - _CHAVE_ST["ts"] < 120:
        return _CHAVE_ST["dados"]
    try:
        st, d = _http(f"{OR_BASE}/key", headers={"Authorization": f"Bearer {chave}"},
                      timeout=15)
        if st != 200:
            return {}
        dados = d.get("data") or {}
        out = {
            "free_tier": dados.get("is_free_tier"),
            "creditos_usados": dados.get("usage"),
            "creditos_limite": dados.get("limit"),
        }
        _CHAVE_ST.update(ts=time.time(), dados=out)
        return out
    except Exception:  # noqa: BLE001
        return {}


def _mensagens(mensagens: list[dict]) -> list[dict]:
    msgs = [{"role": "system", "content": prompt_sistema() + _snapshot()}]
    for m in mensagens[-12:]:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            msgs.append({"role": m["role"], "content": m["content"][:4000]})
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] += ("\n\n(Lembrete do sistema: termine a resposta com a linha "
                                "`SUGESTOES: p1 | p2 | p3` com 3 perguntas curtas de acompanhamento.)")
    return msgs


def _headers_or(chave: str) -> dict:
    return {
        "Authorization": f"Bearer {chave}",
        "HTTP-Referer": "http://127.0.0.1:8000",
        "X-Title": "Cortex Sulista",
    }


def _stream_ollama(msgs: list[dict]):
    """Deltas do Ollama local (NDJSON). Levanta exceção em falha."""
    corpo = _json.dumps({"model": ollama_modelo(), "messages": msgs, "stream": True,
                         "options": _OLLAMA_OPTS, "keep_alive": _OLLAMA_KEEP}).encode()
    req = urllib.request.Request(f"{ollama_url()}/api/chat", data=corpo, method="POST")
    req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req, timeout=300)
    for raw in resp:
        try:
            d = _json.loads(raw.decode("utf-8", "ignore"))
        except ValueError:
            continue
        if d.get("error"):
            raise RuntimeError(d["error"])
        delta = (d.get("message") or {}).get("content")
        if delta:
            yield {"tipo": "delta", "texto": delta}
        if d.get("done"):
            ent, sai = d.get("prompt_eval_count"), d.get("eval_count")
            tokens = ({"entrada": ent, "saida": sai, "total": (ent or 0) + (sai or 0)}
                      if (ent or sai) else None)
            yield {"tipo": "fim", "tokens": tokens}
            return


def _chat_ollama(msgs: list[dict]) -> dict:
    status, d = _http(f"{ollama_url()}/api/chat", timeout=300,
                      payload={"model": ollama_modelo(), "messages": msgs, "stream": False,
                               "options": _OLLAMA_OPTS, "keep_alive": _OLLAMA_KEEP})
    if status != 200 or d.get("error"):
        raise RuntimeError(f"ollama HTTP {status}: {d.get('error', '')}")
    texto = ((d.get("message") or {}).get("content") or "").strip()
    if not texto:
        raise RuntimeError("resposta vazia do ollama")
    ent, sai = d.get("prompt_eval_count"), d.get("eval_count")
    return {"resposta": texto, "modelo": f"{ollama_modelo()} (local)",
            "tokens": {"entrada": ent, "saida": sai, "total": (ent or 0) + (sai or 0)}}


def stream(mensagens: list[dict]):
    """Gera eventos {tipo: modelo|delta|fim|erro} com a resposta em streaming.

    Ordem: Ollama local (gemma4) primeiro; se indisponível/falhar sem emitir
    nada, cai para os modelos free do OpenRouter (se houver chave).
    """
    if not (_SNAP["texto"] and time.time() - _SNAP["ts"] < _SNAP_TTL):
        yield {"tipo": "status", "texto": "consultando o ERP para montar o contexto…"}
    msgs = _mensagens(mensagens)
    yield {"tipo": "status", "texto": "pensando…"}
    st = ollama_status()
    if st["ok"]:
        emitiu = False
        try:
            yield {"tipo": "modelo", "modelo": f"{st['modelo']} (local)"}
            for ev in _stream_ollama(msgs):
                emitiu = emitiu or ev["tipo"] == "delta"
                yield ev
                if ev["tipo"] == "fim":
                    return
        except Exception as exc:  # noqa: BLE001
            log.warning("ollama stream falhou: %s", exc)
            if emitiu:                # caiu no meio: entrega o que veio
                yield {"tipo": "fim", "truncado": True}
                return
        _OLLAMA_ST["ts"] = 0.0        # força rechecagem na próxima pergunta
        yield {"tipo": "status", "texto": "IA local indisponível — tentando a nuvem…"}
    chave = api_key()
    if not chave:
        yield {"tipo": "erro", "erro": "sem_backend"}
        return
    headers = _headers_or(chave)
    erros = []
    for modelo in modelos_free()[:6]:
        corpo = _json.dumps({
            "model": modelo, "messages": msgs, "max_tokens": 2048,
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
    """Resposta completa: Ollama local primeiro; fallback OpenRouter free."""
    msgs = _mensagens(mensagens)
    st = ollama_status()
    if st["ok"]:
        try:
            return _chat_ollama(msgs)
        except Exception as exc:  # noqa: BLE001
            log.warning("ollama chat falhou: %s", exc)
            _OLLAMA_ST["ts"] = 0.0
    chave = api_key()
    if not chave:
        return {"erro": "sem_backend"}
    headers = _headers_or(chave)
    erros = []
    for modelo in modelos_free()[:6]:
        try:
            status, d = _http(
                f"{OR_BASE}/chat/completions", headers=headers, timeout=90,
                payload={"model": modelo, "messages": msgs,
                         "max_tokens": 2048, "temperature": 0.3})
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
