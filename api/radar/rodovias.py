# -*- coding: utf-8 -*-
"""Ocorrências AGORA nos corredores da operação, pela TomTom.

OS CORREDORES SÃO OS DO PAINEL DE TV, e não uma lista nova. O ticker da TV da
Operação (`TV_BBOXES` no `index.html`) já consultava estes quatro — Curitiba e
a BR-376, a Grande SP, a Dutra e o eixo Joinville–Itajaí da BR-101 —, e dois
recortes diferentes de "situação das rodovias" em duas telas dariam duas
respostas para a mesma pergunta.

A DIFERENÇA É QUEM PAGA A CONSULTA. Lá, cada TV aberta consulta a TomTom do
próprio navegador. Aqui a página inicial é aberta por TODO MUNDO, e uma
consulta por abertura multiplicaria o gasto pelo número de pessoas logadas —
contra um teto de plano que a TomTom não mostra em resposta nenhuma
(`api/tomtom/coleta.py`). Então a consulta é do SERVIDOR, no relógio do Radar:
quatro chamadas a cada 20 minutos (~290 por dia), contadas em `tt_chamadas`
como `radar_incidentes` e visíveis na Saúde junto com o resto do consumo.

O FILTRO É O MESMO CRITÉRIO DO TICKER, um pouco mais largo: só rodovia
NUMERADA (fechamento de rua domina a contagem bruta e não muda viagem de
caminhão) e, dela, o que bloqueia ou atrasa de forma moderada para cima.
"""
from __future__ import annotations

import logging

log = logging.getLogger("cortex.radar.rodovias")

#: (chave, rótulo, oeste, sul, leste, norte) — a ordem da TomTom é lon/lat, e
#: trocá-la devolve uma caixa no oceano com ZERO ocorrências, indistinguível
#: de "estrada livre". Os números são os do `TV_BBOXES`.
CORREDORES: tuple[tuple[str, str, float, float, float, float], ...] = (
    ("curitiba", "Curitiba · BR-116 / BR-376 · litoral do PR", -49.9, -26.1, -48.4, -24.8),
    ("grande_sp", "Grande SP · Anchieta / Imigrantes", -47.3, -24.1, -45.9, -23.1),
    ("dutra", "Vale do Paraíba · Dutra", -46.3, -23.5, -44.9, -22.6),
    ("joinville", "Joinville · Itajaí · BR-101 SC", -49.3, -27.0, -48.4, -26.0),
)

MAGNITUDES_QUE_CONTAM = {"moderada", "grande"}


def desligado() -> dict | None:
    """O trânsito da TomTom desligado POR DECISÃO (`cliente.TRAFEGO_DESLIGADO`),
    ou None. Não é o mesmo que "sem TomTom": a chave existe e quem opera
    decidiu não pagar pelo produto — e a tela diz isso, não "não configurada"."""
    try:
        from ..tomtom import cliente
        return cliente.trafego_desligado()
    except Exception:  # noqa: BLE001
        return None


def ativo() -> bool:
    """TomTom configurada E trânsito ligado? Sem ela não é falha — é
    instalação sem o recurso, e a tela fica só com as notícias de rodovia.
    Desligada por decisão dá no mesmo para a coleta: a fonte nem entra no
    plano."""
    try:
        from ..tomtom import cliente
        return cliente.configurado() and not cliente.trafego_desligado()
    except Exception:  # noqa: BLE001
        return False


def _consultar_tomtom(oeste: float, sul: float, leste: float, norte: float) -> dict:
    from ..tomtom import cliente
    return cliente.incidentes(sul=sul, oeste=oeste, norte=norte, leste=leste)


def relevante(item: dict) -> bool:
    return bool(item.get("rodovias")) and (
        item.get("bloqueia") or item.get("magnitude") in MAGNITUDES_QUE_CONTAM)


def consultar(consultar_tomtom=None, esquema: str | None = None) -> dict:
    """`{"itens": [...], "brutos": n, "falhas": n}` dos quatro corredores.

    Um corredor que falha não derruba os outros — mas se TODOS falharem, a
    exceção sobe, e quem grava não substitui o retrato velho por um vazio.

    O `esquema` vai até o contador de consumo da TomTom, e não é detalhe:
    sem ele o `registrar` cai no schema PADRÃO, e o teste desta coleta
    somaria chamadas falsas ao consumo de produção — a quarta vez que a suíte
    escreveria onde não devia.
    """
    from ..tomtom import coleta as tt_coleta
    from ..tomtom import transito
    consultar_tomtom = consultar_tomtom or _consultar_tomtom
    from ..tomtom import cliente as tt_cliente
    itens, brutos, falhas, freados, ultima = [], 0, 0, 0, None
    for chave, rotulo, oeste, sul, leste, norte in CORREDORES:
        try:
            lido = transito.ler_incidentes(consultar_tomtom(oeste, sul, leste, norte))
        except Exception as exc:  # noqa: BLE001
            falhas += 1
            # o corredor recusado pelo FREIO de crédito não saiu para a rede
            freados += isinstance(exc, tt_cliente.TomTomFreado)
            ultima = exc
            log.warning("radar: corredor %s falhou: %s", chave, type(exc).__name__)
            continue
        brutos += lido["total"]
        for i in lido["itens"]:
            if relevante(i):
                itens.append(dict(i, regiao=chave, regiao_rotulo=rotulo))
    tt_coleta.registrar("radar_incidentes", n=len(CORREDORES) - freados,
                        erros=falhas - freados, esquema=esquema, origem="radar",
                        barradas=1 if freados else 0)
    if falhas == len(CORREDORES) and ultima is not None:
        raise ultima
    return {"itens": itens, "brutos": brutos, "falhas": falhas}
