# api/milkrun/copiloto.py
"""Copiloto do Milk Run — conversa restrita ao roteiro do dia.

POR QUE ESTE MODULO EXISTE SEPARADO DO COPILOTO GERAL
=====================================================
O Copiloto geral manda para o modelo APENAS KPIs escalares (`_compacto`), sem
placa, cliente, motorista ou CNPJ, porque ele pode cair num modelo EXTERNO
(OpenRouter) quando o Ollama local nao responde.

Para o Milk Run isso deixaria o chat inutil: ninguem pergunta "quantas
coletas" — pergunta "qual coleta esta atrasada e de quem". A resposta util
exige placa, fornecedor e horario, que sao exatamente o que nao pode sair da
maquina.

Entao aqui a regra e outra, e mais estrita: o contexto detalhado so' e' montado
quando o modelo LOCAL esta servindo. Sem Ollama, o chat NAO responde com dado
externo nem degrada calado para escalares — ele diz que esta indisponivel e
por que. Degradar calado seria pior que recusar: a resposta pareceria boa e
seria pior, e ninguem saberia.

Ver CLAUDE.md secao 8, regra 3: dado sensivel so' vai para o Gemma local.

O QUE NAO ENTRA MESMO NO LOCAL
------------------------------
O NOME DO MOTORISTA. Placa, fornecedor e horario respondem tudo que a tela
pergunta; o nome nao acrescenta analise nenhuma e e o dado mais pessoal do
conjunto. Minimizar vale tambem para o modelo que roda aqui dentro.
"""
from __future__ import annotations

import json
import logging
import statistics
from datetime import date

from api import copiloto as cop
from api.milkrun import respostas
from api.milkrun.servico import get_milkrun

log = logging.getLogger("cortex.milkrun.copiloto")

# Teto do contexto. O roteiro de um dia tem ~14 solicitacoes e ~40 pontos; uma
# semana cheia passaria do que cabe em `num_ctx` do Ollama e a conversa
# comecaria a esquecer o comeco do proprio contexto sem avisar.
MAX_COLETAS = 60
MAX_PONTOS_POR_COLETA = 12

# Teto do contexto em CARACTERES. `num_ctx` do Ollama e 16.384 tokens; a ~4
# chars por token isso da ~65 mil, e o prompt + a conversa tambem ocupam.
# 34 mil deixa folga confortavel para as duas coisas.
MAX_CHARS_CONTEXTO = 34_000

# Acima disto a parada e "demorada" e vale detalhar mesmo num contexto apertado.
PERMANENCIA_NOTAVEL_MIN = 60.0


class LocalIndisponivel(RuntimeError):
    """Ollama fora: o chat do milk run nao tem para onde ir."""


def _ponto(p: dict) -> dict:
    """Um ponto do roteiro, sem nada que identifique pessoa.

    Os nomes seguem EXATAMENTE o servico (`estado`, `rotulo`, `atraso_min`,
    `pontualidade`, `permanencia_min`): inventar apelido aqui produzia um
    contexto com tudo nulo e o modelo respondendo "não consta" sobre dado que
    existe — foi o que aconteceu na primeira versao.
    """
    return {
        "seq": p.get("sequencia"),
        "local": p.get("ponto"),
        "cidade": p.get("cidade"),
        "uf": p.get("uf"),
        "previsto": p.get("previsto"),
        # chegada/saida vem do RASTRO, nao do apontamento manual
        "chegada": p.get("chegada"),
        "saida": p.get("saida"),
        "permanencia_min": p.get("permanencia_min"),
        "atraso_min": p.get("atraso_min"),
        "pontualidade": p.get("pontualidade"),
        "estado": p.get("estado"),
        "rotulo": p.get("rotulo"),
    }


def _agrega(pontos: list[dict], chave: str) -> list[dict]:
    """Agrupa por fornecedor (ou placa) o que o modelo erraria somando sozinho.

    Devolve MEDIANA e media lado a lado: a mediana e a regra da casa (uma
    parada de 4 h entre paradas de 20 min move a media e nao move a mediana),
    mas quem pergunta costuma pedir "tempo medio" - dar as duas, rotuladas,
    evita que o modelo escolha uma e chame de outra.
    """
    por: dict[str, list[dict]] = {}
    for p in pontos:
        k = p.get(chave)
        if k:
            por.setdefault(k, []).append(p)
    saida = []
    for k, ps in por.items():
        perm = [p["permanencia_min"] for p in ps
                if p.get("permanencia_min") is not None]
        atr = [p["atraso_min"] for p in ps if p.get("atraso_min") is not None]
        if not perm:
            continue
        saida.append({
            chave: k,
            "paradas": len(ps),
            "paradas_com_medida": len(perm),
            "permanencia_mediana_min": round(statistics.median(perm), 1),
            "permanencia_media_min": round(statistics.mean(perm), 1),
            "permanencia_max_min": round(max(perm), 1),
            "atraso_mediano_min": round(statistics.median(atr), 1) if atr else None,
        })
    return sorted(saida, key=lambda x: -x["permanencia_mediana_min"])


def contexto(de: str | None = None, ate: str | None = None,
             tomador: str = "02162259", tipo: str = "milk") -> dict:
    """Retrato do roteiro para o modelo. SEM nome de motorista."""
    d = get_milkrun(de, ate, tomador, "", "", "", tipo)
    coletas = []
    for c in (d.get("coletas") or [])[:MAX_COLETAS]:
        pontos = [_ponto(p) for p in (c.get("pontos") or [])[:MAX_PONTOS_POR_COLETA]]
        coletas.append({
            "coleta": c.get("coleta"),
            "placa": c.get("placa"),
            "situacao": c.get("situacao"),
            "cancelada": c.get("cancelada"),
            "paradas": len(c.get("pontos") or []),
            "pontos": pontos,
        })
    kpis = d.get("kpis") or {}
    # TABELAS PRONTAS. O modelo nao agrupa 163 pontos de JSON sem errar - e
    # nao precisa: o ranking sai daqui ordenado e ele so le.
    # a placa vive na COLETA; sem propagar, _agrega(..., "placa") devolve
    # sempre vazio e a pergunta "qual placa fica mais parada" morre calada
    todos = [dict(p, placa=c["placa"]) for c in coletas for p in c["pontos"]]
    por_forn = _agrega(todos, "local")
    por_placa = _agrega(todos, "placa") if any(p.get("placa") for p in todos) else []
    medidos = [p for p in todos if p.get("permanencia_min") is not None]
    # PIORES ATRASOS, tabela pronta. Sem ela o modelo tem de varrer os pontos
    # para achar o maximo - e nao acha: medido em 26/08, gemma4 devolveu
    # resposta VAZIA e qwen2.5 respondeu com a maior PERMANENCIA achando que
    # era o maior atraso. Todo "top N"/"maior" precisa de tabela pronta; a de
    # permanencia ja existia e a de atraso faltava.
    _atr = [{"coleta": c["coleta"], "placa": c["placa"], "local": p["local"],
             "atraso_min": p["atraso_min"], "previsto": p["previsto"],
             "chegada": p["chegada"], "pontualidade": p.get("pontualidade")}
            for c in coletas for p in c["pontos"]
            if p.get("atraso_min") is not None]
    piores = sorted(_atr, key=lambda x: -x["atraso_min"])[:15]
    saida = {
        "hoje": date.today().isoformat(),
        "periodo": {"de": d.get("de"), "ate": d.get("ate")},
        "tipo": tipo,
        "kpis": {k: v for k, v in kpis.items()
                 if isinstance(v, (int, float, str, bool)) or v is None},
        "por_data": [{k: v for k, v in x.items() if k != "coletas"}
                     for x in (d.get("por_data") or [])],
        "coletas": coletas,
        "ranking_fornecedores_por_permanencia": por_forn[:15],
        "ranking_placas_por_permanencia": por_placa[:15],
        "piores_atrasos": piores,
        "pontos_com_atraso_medido": len(_atr),
        # Sem isto o modelo responde "nao esta no contexto" e o leitor nao
        # descobre que basta abrir o periodo: no recorte de HOJE os pontos
        # costumam estar todos pendentes, sem permanencia medida ainda.
        "pontos_com_permanencia_medida": len(medidos),
        "pontos_no_periodo": len(todos),
        "truncado": len(d.get("coletas") or []) > MAX_COLETAS,
        "fonte": d.get("fonte"),
        "atualizado_em": d.get("atualizado_em"),
    }
    return _cabe(saida)


def _notavel(p: dict) -> bool:
    """Vale detalhar mesmo com o contexto apertado?"""
    if p.get("estado") in ("frustrado", "vencido"):
        return True
    if (p.get("atraso_min") or 0) > 0:
        return True
    perm = p.get("permanencia_min")
    return perm is not None and perm >= PERMANENCIA_NOTAVEL_MIN


def _cabe(ctx: dict) -> dict:
    """Poda o detalhe ponto a ponto ate o contexto caber no num_ctx.

    As tabelas agregadas NUNCA sao podadas: sao pequenas e sao o que responde
    "top N", que e a pergunta mais comum. Quem sai e o detalhe das paradas sem
    nada de notavel - e o que sai fica DECLARADO em `detalhe_podado`, para o
    modelo poder dizer que nao viu tudo em vez de afirmar sobre o que nao leu.
    """
    if len(json.dumps(ctx, ensure_ascii=False, default=str)) <= MAX_CHARS_CONTEXTO:
        return ctx
    antes = sum(len(c["pontos"]) for c in ctx["coletas"])
    for c in ctx["coletas"]:
        c["pontos"] = [p for p in c["pontos"] if _notavel(p)]
    depois = sum(len(c["pontos"]) for c in ctx["coletas"])
    ctx["detalhe_podado"] = {
        "motivo": "periodo grande demais para detalhar ponto a ponto",
        "pontos_detalhados": depois, "pontos_no_periodo": antes,
        "criterio": ("mantidos os pontos com atraso, frustrados, vencidos ou "
                     f"com permanencia >= {PERMANENCIA_NOTAVEL_MIN:.0f} min; "
                     "os rankings agregados cobrem TODOS os pontos"),
    }
    # ainda grande: corta as coletas mais antigas, que e o que menos se pergunta
    while (len(json.dumps(ctx, ensure_ascii=False, default=str)) > MAX_CHARS_CONTEXTO
           and len(ctx["coletas"]) > 5):
        ctx["coletas"] = ctx["coletas"][1:]
        ctx["detalhe_podado"]["coletas_detalhadas"] = len(ctx["coletas"])
    return ctx


SISTEMA = """Você é o Copiloto da Operação MWM do Cortex Sulista. \
Responda EXCLUSIVAMENTE sobre o milk run cujo roteiro está no contexto abaixo.

Regras:
- Se a pergunta for sobre qualquer outro assunto do painel (financeiro, frota, \
DRE, pneus, RH...), diga que este chat é só da Operação MWM e aponte o Copiloto \
Cortex, que responde sobre o painel inteiro. Não tente responder.
- Só afirme o que estiver no contexto. Se o dado não estiver lá, diga que não \
está — não estime, não complete e não invente coleta, placa ou horário.
- Horário CHEGADA e SAÍDA vêm do RASTREADOR (detectados pela posição), não de \
digitação. É a razão de a tela existir: quando divergirem do apontamento \
manual, o rastro é a referência.
- Um "milk run" é a solicitação com MAIS DE UMA parada. Solicitação de uma \
parada só é frete simples e está fora deste recorte quando tipo=milk.
- "% realizado" tem no denominador o que JÁ DEVERIA estar resolvido \
(coletadas + frustradas + pendentes cujo horário já passou) — pendente que \
ainda não venceu não conta contra.
- Para "maior atraso" ou "quem atrasou mais", USE `piores_atrasos`, que já vem ordenada do maior para o menor e traz coleta, placa e local. Não varra os pontos: atraso e permanência são coisas DIFERENTES e confundir as duas é o erro mais comum aqui.
- Para ranking ou "top N" de tempo parado, USE as tabelas já prontas `ranking_fornecedores_por_permanencia` e `ranking_placas_por_permanencia`, que vêm ordenadas da maior para a menor permanência. Não recalcule ponto a ponto.
- Cada linha do ranking traz mediana E média: use a que foi pedida e diga qual está usando. Some `paradas_com_medida` para o leitor saber sobre quantas paradas o número foi tirado.
- Se `pontos_com_permanencia_medida` for 0, NÃO responda "não está no contexto": explique que nenhuma parada do período filtrado foi concluída ainda (as pendentes não têm permanência medida) e sugira ampliar o período no filtro da tela.
- Se existir `detalhe_podado`, o período é grande e você recebeu o detalhe ponto a ponto apenas das paradas notáveis — mas os RANKINGS agregados cobrem todas. Responda pelos rankings e diga que o detalhe está reduzido; não afirme "não houve" sobre parada que pode ter sido podada.
- Cite sempre o número da coleta e a placa quando falar de um caso concreto.
- Seja curto e direto. Valores em pt-BR.

Contexto (JSON do roteiro):
"""


def mensagens(historico: list[dict], ctx: dict) -> list[dict]:
    msgs = [{"role": "system",
             "content": SISTEMA + json.dumps(ctx, ensure_ascii=False, default=str)}]
    for m in (historico or [])[-12:]:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            msgs.append({"role": m["role"], "content": m["content"][:4000]})
    return msgs


def stream(historico: list[dict], de: str | None = None, ate: str | None = None,
           tomador: str = "02162259", tipo: str = "milk"):
    """Eventos {tipo: status|modelo|delta|fim|erro}, SEMPRE no modelo local.

    Nao existe caminho de fallback externo aqui, de proposito: o contexto
    carrega placa e fornecedor. Se o Ollama estiver fora, o chat diz isso.
    """
    st = cop.ollama_status()
    if not st.get("ok"):
        raise LocalIndisponivel(
            "O chat do Milk Run responde apenas pelo modelo local (Ollama), "
            "porque o roteiro leva placa e fornecedor e esse dado não sai da "
            "máquina. O modelo local não está respondendo agora."
        )
    yield {"tipo": "status", "texto": "lendo o roteiro do dia…"}
    ctx = contexto(de, ate, tomador, tipo)
    # RESPOSTA CALCULADA primeiro. Para "maior", "top N" e "resumo" o numero E
    # a resposta: nao ha o que interpretar, e deixar o modelo escolher so
    # acrescenta chance de errar (medido: os dois modelos testados davam
    # resposta confiante e errada com o dado a vista). Pergunta aberta cai no
    # `None` e segue para o modelo, que e onde ele e melhor.
    ultima = next((m.get("content", "") for m in reversed(historico or [])
                   if m.get("role") == "user"), "")
    pronta = respostas.responder(ultima, ctx)
    if pronta:
        yield {"tipo": "modelo", "modelo": "calculado"}
        yield {"tipo": "delta", "texto": pronta}
        yield {"tipo": "fim", "calculado": True}
        return
    yield {"tipo": "modelo", "modelo": f"{st['modelo']} (local)"}
    msgs = mensagens(historico, ctx)
    emitiu = False
    try:
        for ev in cop._stream_ollama(msgs):
            emitiu = emitiu or ev["tipo"] == "delta"
            yield ev
            if ev["tipo"] == "fim":
                return
    except Exception as exc:  # noqa: BLE001
        log.warning("milkrun copiloto stream falhou: %s", exc)
        # caiu no meio: entrega o que veio marcado como truncado, em vez de
        # apagar a resposta parcial que o usuario ja esta lendo
        yield {"tipo": "fim", "truncado": True} if emitiu else \
              {"tipo": "erro", "erro": "modelo_falhou"}
