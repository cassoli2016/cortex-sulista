"""A leitura do trânsito: de `currentSpeed` para "a estrada está livre?".

POR QUE UMA CAMADA SÓ PARA ISSO
===============================
A API devolve velocidade atual e velocidade de fluxo livre. Nenhuma das duas é
a pergunta que a operação faz — que é "meu caminhão vai chegar?". Traduzir isso
é regra de negócio, e regra de negócio separada da leitura é o que permite
mudar o fornecedor sem reescrever a decisão.

AS TRÊS DECISÕES QUE ESTÃO AQUI
===============================
1. **A razão, não a velocidade.** 40 km/h é bom numa serra e péssimo numa reta.
   O que separa é `atual ÷ livre`, que a própria TomTom já normaliza por
   trecho.
2. **Semáforo DISCRETO**, como todo gráfico da casa: ≥85% livre, 60–85% lento,
   <60% congestionado, e parado à parte. Degradê contínuo não diz em que
   estado o dado está — e aqui "estado" é literalmente a decisão.
3. **CONFIANÇA BAIXA NÃO VIRA ESTADO.** A TomTom devolve `confidence` de 0 a 1:
   abaixo de 0,5 ela própria diz que a medida é fraca (trecho sem sonda no
   momento). Pintar isso de verde ou de vermelho seria inventar; vira `n/d`,
   pelo mesmo motivo que o "0% de retorno vazio" do terceiro virou `n/d` em
   vez de melhor da tabela.

O QUE ESTE MÓDULO NÃO INVENTA
=============================
`roadClosure` é a única afirmação forte que a API faz, e ela é repassada como
está. Não há aqui nenhuma estimativa de "condição do asfalto": a TomTom mede
FLUXO, não pavimento, e derivar buraco de estrada a partir de velocidade seria
afirmar o que a fonte não disse — o mesmo erro de dizer há quantas horas sumiu
um veículo que a API nunca reportou.
"""
from __future__ import annotations

CONFIANCA_MINIMA = 0.5

# Fronteiras do semáforo, em fração da velocidade de fluxo livre.
LIVRE = 0.85
LENTO = 0.60
# Abaixo de 8 km/h com o motor andando não é "congestionado devagar": é fila
# parada, e a diferença importa para quem decide desviar.
PARADO_KMH = 8.0

_ROTULO = {
    "livre": "Fluxo livre",
    "lento": "Trânsito lento",
    "congestionado": "Congestionado",
    "parado": "Parado",
    "bloqueado": "Via bloqueada",
    "nd": "Sem medida confiável",
}


def classificar(atual, livre, confianca=None, fechada=False) -> dict:
    """De um trecho da TomTom para o estado que a tela mostra.

    `atual` e `livre` em km/h. Devolve `estado`, `razao` (0 a 1) e `rotulo`.
    """
    if fechada:
        return {"estado": "bloqueado", "razao": 0.0,
                "rotulo": _ROTULO["bloqueado"]}
    try:
        atual = float(atual)
        livre = float(livre)
    except (TypeError, ValueError):
        return {"estado": "nd", "razao": None, "rotulo": _ROTULO["nd"]}
    if livre <= 0:
        return {"estado": "nd", "razao": None, "rotulo": _ROTULO["nd"]}
    if confianca is not None:
        try:
            if float(confianca) < CONFIANCA_MINIMA:
                # A PRÓPRIA API diz que a medida é fraca. Pintar de verde ou de
                # vermelho seria inventar estado a partir de "não sei".
                return {"estado": "nd", "razao": None, "rotulo": _ROTULO["nd"],
                        "motivo": "confiança %.2f abaixo de %.2f"
                                  % (float(confianca), CONFIANCA_MINIMA)}
        except (TypeError, ValueError):
            pass
    razao = round(atual / livre, 3)
    if atual < PARADO_KMH:
        estado = "parado"
    elif razao >= LIVRE:
        estado = "livre"
    elif razao >= LENTO:
        estado = "lento"
    else:
        estado = "congestionado"
    return {"estado": estado, "razao": razao, "rotulo": _ROTULO[estado]}


def do_payload(bruto: dict) -> dict:
    """Lê o `flowSegmentData` e devolve o trecho já classificado.

    Campo ausente vira `None` e cai em `n/d` — a API omite `confidence` em
    alguns trechos, e tratar ausência como zero jogaria tudo para "sem medida".
    """
    d = (bruto or {}).get("flowSegmentData") or {}
    r = classificar(d.get("currentSpeed"), d.get("freeFlowSpeed"),
                    d.get("confidence"), bool(d.get("roadClosure")))
    atraso = None
    try:
        atraso = int(d["currentTravelTime"]) - int(d["freeFlowTravelTime"])
    except (KeyError, TypeError, ValueError):
        pass
    return {**r,
            "velocidade": d.get("currentSpeed"),
            "velocidade_livre": d.get("freeFlowSpeed"),
            "confianca": d.get("confidence"),
            # Segundos PERDIDOS neste trecho por causa do trânsito. É o número
            # que soma ao longo da rota e vira atraso — a velocidade sozinha
            # não soma.
            "atraso_s": atraso,
            "classe_via": d.get("frc"),
            "fechada": bool(d.get("roadClosure"))}


def resumo(trechos: list[dict]) -> dict:
    """O panorama da frota: quantos em cada estado, e o pior primeiro.

    O DENOMINADOR SÃO OS TRECHOS MEDIDOS, não a frota inteira. Contar quem não
    tem posição como "livre" diria que está tudo bem por falta de dado — é o
    erro dos 664 rastreadores "sem sinal", de novo. Os sem medida aparecem em
    `nd`, contados à parte.
    """
    ordem = ["bloqueado", "parado", "congestionado", "lento", "livre", "nd"]
    contagem = {e: 0 for e in ordem}
    for t in trechos or []:
        contagem[t.get("estado", "nd")] = contagem.get(t.get("estado", "nd"), 0) + 1
    medidos = sum(v for e, v in contagem.items() if e != "nd")
    ruins = contagem["bloqueado"] + contagem["parado"] + contagem["congestionado"]
    atraso = sum(int(t.get("atraso_s") or 0) for t in trechos or [])
    return {
        "contagem": contagem,
        "medidos": medidos,
        "sem_medida": contagem["nd"],
        "com_problema": ruins,
        # Percentual SOBRE OS MEDIDOS. Sobre o total, um dia de pouca medição
        # faria o problema parecer menor exatamente quando se sabe menos.
        "pct_problema": round(100.0 * ruins / medidos, 1) if medidos else None,
        "atraso_total_min": round(atraso / 60.0, 1) if trechos else 0.0,
    }


# ── incidentes ───────────────────────────────────────────────────────────────
#
# MEDIDO em 30/08/2026, numa caixa cobrindo Joinville–Curitiba: **194
# incidentes**, e 173 deles (89%) de UMA categoria — "via fechada". Um cartão
# dizendo "194 ocorrências na malha" seria verdadeiro e inútil; "173 estradas
# fechadas" seria alarmante e enganoso, porque a maior parte é fechamento de
# rua urbana com `delay: null` e `magnitudeOfDelay: 4` (indefinido).
#
# É o mesmo formato dos "664 de 836 rastreadores sem sinal": o número grande
# tem de vir com a quebra que o desarma, e o recorte que decide é OUTRO — aqui,
# o que está na ROTA de um caminhão, não o que existe na caixa.

CATEGORIA = {
    0: "Desconhecido", 1: "Acidente", 2: "Neblina",
    3: "Condição perigosa", 4: "Chuva", 5: "Gelo", 6: "Congestionamento",
    7: "Faixa interditada", 8: "Via fechada", 9: "Obra", 10: "Vento",
    11: "Alagamento", 14: "Veículo quebrado",
}

# O que faz um caminhão parar ou desviar. Chuva e vento entram na lista da
# TomTom e NÃO entram aqui: são condição de tempo, não bloqueio — misturá-los
# faria um dia chuvoso parecer um dia de malha travada.
BLOQUEIA = {1, 8, 7, 11, 5}

MAGNITUDE = {0: "desconhecida", 1: "pequena", 2: "moderada", 3: "grande",
             4: "indefinida"}


def ler_incidentes(bruto: dict) -> dict:
    """Do payload da TomTom para a leitura da operação.

    A CONTAGEM POR CATEGORIA VEM SEMPRE. Sem ela o total é um número que não
    decide nada — e, pior, engana: 89% de "via fechada" numa amostra real são
    quase todos fechamento de rua, não interdição de rodovia.
    """
    itens = []
    for f in (bruto or {}).get("incidents") or []:
        p = f.get("properties") or {}
        cat = p.get("iconCategory")
        eventos = [e.get("description") for e in (p.get("events") or [])
                   if e.get("description")]
        itens.append({
            "categoria": cat,
            "categoria_rotulo": CATEGORIA.get(cat, "Categoria %s" % cat),
            "bloqueia": cat in BLOQUEIA,
            "descricao": " · ".join(eventos) or None,
            "de": p.get("from"), "para": p.get("to"),
            # `delay` vem NULO em boa parte dos fechamentos — a API não estima
            # atraso para algo sem previsão de reabertura. Zero ali seria dizer
            # "não atrasa nada", que é o oposto.
            "atraso_s": p.get("delay"),
            "magnitude": MAGNITUDE.get(p.get("magnitudeOfDelay"), "desconhecida"),
            "rodovias": p.get("roadNumbers") or [],
        })
    por_cat: dict[str, int] = {}
    for i in itens:
        por_cat[i["categoria_rotulo"]] = por_cat.get(i["categoria_rotulo"], 0) + 1
    bloqueios = [i for i in itens if i["bloqueia"]]
    return {
        "itens": itens,
        "total": len(itens),
        "por_categoria": dict(sorted(por_cat.items(), key=lambda x: -x[1])),
        "bloqueios": len(bloqueios),
        # Em RODOVIA é o recorte que decide: fechamento de rua não muda a
        # viagem de um caminhão, e é ele que domina a contagem bruta.
        "bloqueios_em_rodovia": sum(1 for i in bloqueios if i["rodovias"]),
    }
