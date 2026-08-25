"""Do pneu da Prolog para os números que decidem — e a cobertura de cada um.

REGRA QUE ATRAVESSA A TELA INTEIRA: só pneu INSTALLED está rodando. Pressão de
pneu no estoque não é pressão baixa, sulco de pneu sucateado não é risco, e
misturar os quatro estados num denominador único produz exatamente o tipo de
alarme falso que já nos custou uma tela (a CNH contava motorista demitido).

CAMPO PODE VIR VAZIO E NÃO DÁ PARA SABER ANTES. Diferente do GLOBUS, aqui não
há como conferir a cobertura sem credencial. Então cada indicador que dependa
de campo preenchível carrega a sua: CPK e custo de compra são os mais expostos,
porque valem zero até alguém cadastrar a nota.
"""
from __future__ import annotations

# Sulco mínimo legal no Brasil (CONTRAN 558/80 e Res. 916/22): 1,6 mm. Abaixo
# disso o veículo não pode circular — é multa e é risco, não é "planejamento".
SULCO_MINIMO_LEGAL_MM = 1.6

# Faixa de atenção: ainda legal, mas é quando se agenda a troca ou a recapagem
# sem parar o veículo às pressas.
SULCO_ATENCAO_MM = 3.0

# Desvio de pressão que importa. Abaixo de -10% o consumo e o desgaste já
# sobem de forma mensurável; -20% é onde o risco de estouro cresce.
PRESSAO_ATENCAO_PCT = 10.0
PRESSAO_CRITICA_PCT = 20.0


def _n(v) -> float | None:
    """Número ou None. Zero NÃO é convertido em None: zero de sulco é uma
    medição possível e grave; o que é ausência é o campo vazio."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _t(v) -> str:
    return "" if v is None else str(v).strip()


def pneu(r: dict) -> dict:
    """Um pneu da Prolog no formato que a tela usa."""
    inst = r.get("installed") or {}
    disp = r.get("disposal") or {}
    ana = r.get("analysis") or {}
    make = r.get("make") or {}
    model = r.get("model") or {}
    tam = r.get("tireSize") or {}
    recap = r.get("currentRetread") or {}

    sulcos = [_n(r.get(k)) for k in ("innerTreadDepth", "middleInnerTreadDepth",
                                     "middleOuterTreadDepth", "outerTreadDepth")]
    medidos = [x for x in sulcos if x is not None]
    menor = _n(r.get("smallestTreadDepth"))
    if menor is None and medidos:
        menor = min(medidos)

    pres = _n(r.get("currentPressure"))
    rec = _n(r.get("recommendedPressure"))
    # desvio só existe se houver os DOIS; com recomendada zerada a divisão
    # explodiria e um pneu sem cadastro viraria "-100%"
    desvio = round(100 * (pres - rec) / rec, 1) if pres is not None and rec else None

    vidas = r.get("tireLifecycles") or []
    return {
        "id": r.get("id"),
        "serie": _t(r.get("serialNumber")),
        "dot": _t(r.get("dot")),
        "status": _t(r.get("status")).upper(),
        "filial": _t(r.get("branchOfficeName")),
        "marca": _t(make.get("name") or make.get("description")),
        "modelo": _t(model.get("name") or model.get("description")),
        "medida": _t(tam.get("formatted") or tam.get("description")),
        "desenho": _t(r.get("currentTreadDesign")),
        # ---- vida
        "vida": r.get("currentLifeCycle"),
        "recapagens": r.get("timesRetreaded"),
        "recapagens_max": r.get("maxRetreadsExpected"),
        "vidas_max": r.get("maxLifeCycles"),
        "recapadora": _t(ana.get("recapperName")),
        "recap_custo": _n(recap.get("retreadCost")),
        "recap_data": _t(recap.get("lastRetreadDate"))[:10],
        # ---- dinheiro
        "custo_compra": _n(r.get("purchaseCost")),
        "cpk": _n(r.get("cpk")),
        "km_rodados": r.get("previousTotalKilometersDriven"),
        "cpk_por_vida": [{"vida": v.get("lifecycle"), "km": v.get("totalDistanceDriven"),
                          "cpk": _n(v.get("cpk"))} for v in vidas],
        # ---- medidas
        "pressao": pres,
        "pressao_rec": rec,
        "pressao_desvio": desvio,
        "sulco_menor": menor,
        "sulcos": sulcos,
        # ---- onde está
        "placa": _t(inst.get("licensePlate")),
        "frota": _t(inst.get("fleetId")),
        "posicao": _t(inst.get("installedPositionName")),
        "eixo": inst.get("installedAxle"),
        "direcional": bool(inst.get("onSteeringAxle")),
        "tipo_veiculo": _t(inst.get("vehicleTypeName")),
        # ---- baixa
        "sucata_motivo": _t(disp.get("disposalReasonDescription")),
    }


def _estado_sulco(p: dict) -> str:
    s = p["sulco_menor"]
    if s is None:
        return "sem medida"
    if s < SULCO_MINIMO_LEGAL_MM:
        return "abaixo do legal"
    if s < SULCO_ATENCAO_MM:
        return "atencao"
    return "ok"


def _estado_pressao(p: dict) -> str:
    d = p["pressao_desvio"]
    if d is None:
        return "sem medida"
    if d <= -PRESSAO_CRITICA_PCT:
        return "muito baixa"
    if d <= -PRESSAO_ATENCAO_PCT:
        return "baixa"
    if d >= PRESSAO_CRITICA_PCT:
        return "muito alta"
    if d >= PRESSAO_ATENCAO_PCT:
        return "alta"
    return "ok"


def _urgencia(p: dict) -> tuple:
    """Ordem da lista de ação imediata: GRAVIDADE antes de posição.

    Circular com sulco abaixo de 1,6 mm é ilegal; pressão baixa, por pior que
    seja, não é. Ordenar só pelo eixo direcional punha um pneu com sulco bom e
    pressão baixa acima de outro fora do limite legal — e o topo de uma lista
    chamada "ação imediata" precisa ser o que de fato para o veículo primeiro.

    Dentro de cada faixa de gravidade o direcional vem antes, e depois o de
    menor sulco.
    """
    ilegal = p["estado_sulco"] == "abaixo do legal"
    return (0 if ilegal else 1,
            not p["direcional"],
            p["sulco_menor"] if p["sulco_menor"] is not None else 99,
            p["pressao_desvio"] if p["pressao_desvio"] is not None else 99)


def analisar(brutos: list[dict]) -> dict:
    """Indicadores da frota de pneus, com a cobertura de cada campo."""
    todos = [pneu(r) for r in brutos]
    rodando = [p for p in todos if p["status"] == "INSTALLED"]
    for p in todos:
        p["estado_sulco"] = _estado_sulco(p)
        p["estado_pressao"] = _estado_pressao(p)

    def conta(lista, f):
        return sum(1 for x in lista if f(x))

    # COBERTURA. O que decide se o indicador ao lado vale alguma coisa.
    com_cpk = [p for p in todos if p["cpk"] is not None and p["cpk"] > 0]
    com_custo = [p for p in todos if p["custo_compra"] is not None
                 and p["custo_compra"] > 0]
    com_sulco = [p for p in rodando if p["sulco_menor"] is not None]
    com_pressao = [p for p in rodando if p["pressao_desvio"] is not None]

    por_status: dict[str, int] = {}
    for p in todos:
        por_status[p["status"] or "(sem status)"] = por_status.get(
            p["status"] or "(sem status)", 0) + 1

    abaixo_legal = [p for p in rodando if p["estado_sulco"] == "abaixo do legal"]
    # o direcional e o que tira o veiculo de circulacao na hora: pneu careca no
    # eixo de direcao nao e planejamento de troca, e parada imediata
    abaixo_direcional = [p for p in abaixo_legal if p["direcional"]]

    fim_de_vida = [p for p in rodando
                   if p["recapagens"] is not None and p["recapagens_max"]
                   and p["recapagens"] >= p["recapagens_max"]]

    cpks = sorted(p["cpk"] for p in com_cpk)
    return {
        "kpis": {
            "total": len(todos),
            "rodando": len(rodando),
            "por_status": por_status,
            # sulco
            "sulco_cobertura": len(com_sulco),
            "abaixo_legal": len(abaixo_legal),
            "abaixo_legal_direcional": len(abaixo_direcional),
            "sulco_atencao": conta(rodando, lambda p: p["estado_sulco"] == "atencao"),
            # pressao
            "pressao_cobertura": len(com_pressao),
            "pressao_baixa": conta(rodando, lambda p: p["estado_pressao"] in
                                   ("baixa", "muito baixa")),
            "pressao_muito_baixa": conta(rodando,
                                         lambda p: p["estado_pressao"] == "muito baixa"),
            "pressao_alta": conta(rodando, lambda p: p["estado_pressao"] in
                                  ("alta", "muito alta")),
            # dinheiro — os mais expostos a cadastro incompleto
            "cpk_cobertura": len(com_cpk),
            "cpk_mediana": cpks[len(cpks) // 2] if cpks else None,
            "custo_cobertura": len(com_custo),
            "investido": round(sum(p["custo_compra"] for p in com_custo), 2)
            if com_custo else None,
            # vida
            "fim_de_vida": len(fim_de_vida),
            "sucateados": por_status.get("DISPOSAL", 0),
            "em_analise": por_status.get("ANALYSIS", 0),
            "estoque": por_status.get("INVENTORY", 0),
            "veiculos": len({p["placa"] for p in rodando if p["placa"]}),
            "filiais": len({p["filial"] for p in todos if p["filial"]}),
        },
        "pneus": todos,
        "criticos": sorted(
            [p for p in rodando
             if p["estado_sulco"] == "abaixo do legal"
             or p["estado_pressao"] == "muito baixa"],
            key=_urgencia),
        "fim_de_vida": fim_de_vida,
    }
