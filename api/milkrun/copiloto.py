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
from datetime import date

from api import copiloto as cop
from api.milkrun.servico import get_milkrun

log = logging.getLogger("cortex.milkrun.copiloto")

# Teto do contexto. O roteiro de um dia tem ~14 solicitacoes e ~40 pontos; uma
# semana cheia passaria do que cabe em `num_ctx` do Ollama e a conversa
# comecaria a esquecer o comeco do proprio contexto sem avisar.
MAX_COLETAS = 60
MAX_PONTOS_POR_COLETA = 12


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
    return {
        "hoje": date.today().isoformat(),
        "periodo": {"de": d.get("de"), "ate": d.get("ate")},
        "tipo": tipo,
        "kpis": {k: v for k, v in kpis.items()
                 if isinstance(v, (int, float, str, bool)) or v is None},
        "por_data": [{k: v for k, v in x.items() if k != "coletas"}
                     for x in (d.get("por_data") or [])],
        "coletas": coletas,
        "truncado": len(d.get("coletas") or []) > MAX_COLETAS,
        "fonte": d.get("fonte"),
        "atualizado_em": d.get("atualizado_em"),
    }


SISTEMA = """Você é o Copiloto do Milk Run do Cortex Sulista. \
Responda EXCLUSIVAMENTE sobre o milk run cujo roteiro está no contexto abaixo.

Regras:
- Se a pergunta for sobre qualquer outro assunto do painel (financeiro, frota, \
DRE, pneus, RH...), diga que este chat é só do Milk Run e aponte o Copiloto \
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
