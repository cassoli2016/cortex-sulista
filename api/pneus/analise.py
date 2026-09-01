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


# Piso de amostra do ranking de marcas: abaixo de 10 descartes a linha nem
# entra; entre 10 e 29 entra ATENUADA com badge "base pequena" (regra da DRE
# por Cliente). Morte prematura = carcaça descartada com menos de 40 mil km.
MARCA_N_MIN = 10
MARCA_N_SOLIDO = 30
KM_PREMATURO = 40_000.0


def _mediana(vals):
    vs = sorted(vals)
    n = len(vs)
    if not n:
        return None
    return vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2.0


def marcas(todos: list[dict]) -> dict:
    """O que decide a MARCA da próxima compra: km de carcaça ao descarte.

    A ARMADILHA MEDIDA PRIMEIRO (01/09/2026): 2.354 dos 5.012 descartes são
    "VENDA DE PNEU COM O VEICULO" — não é fim de vida. Com eles no
    denominador a STRADA "rendia" 39.853 km; sem eles, 99.261. A exclusão
    MUDA O VEREDITO e por isso é a primeira linha daqui, com teste.

    VIÉS DE SOBREVIVÊNCIA, dito no ⓘ da tela: o km de carcaça sai só de quem
    MORREU — é rendimento observado nos descartes, não previsão do lote
    atual (o mix de descarte é de compras antigas).
    """
    base, excluidas_venda = [], 0
    for p0 in todos:
        if p0.get("status") != "DISPOSAL":
            continue
        if "VENDA" in (p0.get("sucata_motivo") or "").upper():
            excluidas_venda += 1
            continue
        km = sum((v.get("km") or 0) for v in (p0.get("cpk_por_vida") or []))
        if km <= 0:
            continue
        base.append((p0, float(km)))

    cpk_inst: dict[str, list[float]] = {}
    for p0 in todos:
        if p0.get("status") == "INSTALLED" and p0.get("cpk"):
            cpk_inst.setdefault(p0.get("marca") or "(sem marca)", []).append(p0["cpk"])

    grupos: dict[str, dict] = {}
    for p0, km in base:
        g = grupos.setdefault(p0.get("marca") or "(sem marca)",
                              {"kms": [], "rskm": [], "vidas": [], "prem": 0})
        g["kms"].append(km)
        if p0.get("custo_compra"):
            g["rskm"].append(p0["custo_compra"] / km)
        if p0.get("vida") is not None:
            g["vidas"].append(p0["vida"])
        if km < KM_PREMATURO:
            g["prem"] += 1

    itens = []
    for marca, g in grupos.items():
        n = len(g["kms"])
        if n < MARCA_N_MIN:
            continue
        cs = cpk_inst.get(marca) or []
        itens.append({
            "marca": marca, "n": n,
            "km_mediano": _mediana(g["kms"]),
            "rskm": _mediana(g["rskm"]),
            "vidas_mediana": _mediana(g["vidas"]),
            "prematuro_pct": 100.0 * g["prem"] / n,
            "cpk_mediano": _mediana(cs), "cpk_n": len(cs),
            "base_pequena": n < MARCA_N_SOLIDO,
        })
    itens.sort(key=lambda x: -(x["km_mediano"] or 0))
    return {"itens": itens, "excluidas_venda": excluidas_venda,
            "descartes_uteis": len(base)}


def funil(todos: list[dict]) -> dict:
    """A fila de reposição: quem vira RECAPAGEM e quem vira COMPRA NOVA.

    Sulco baixo com carcaça DENTRO do limite de recapagens = recapagem;
    sulco baixo no limite = compra. Fim de vida (recapagens >= máximo do
    próprio modelo) vira compra independente do sulco.
    """
    rodando = [p0 for p0 in todos if p0.get("status") == "INSTALLED"]

    def _no_limite(p0):
        return (p0.get("recapagens") is not None and p0.get("recapagens_max")
                and p0["recapagens"] >= p0["recapagens_max"])

    ilegal = f16_3 = f3_5 = f3_5_lim = menos5_lim = 0
    for p0 in rodando:
        s0 = p0.get("sulco_menor")
        if s0 is None:
            continue
        lim = _no_limite(p0)
        if s0 < SULCO_MINIMO_LEGAL_MM:
            ilegal += 1
        elif s0 < 3.0:
            f16_3 += 1
        elif s0 < 5.0:
            f3_5 += 1
            if lim:
                f3_5_lim += 1
        if s0 < 5.0 and lim:
            menos5_lim += 1
    fim = sum(1 for p0 in rodando if _no_limite(p0))
    gastos = ilegal + f16_3 + f3_5
    return {
        "ilegal": ilegal, "f16_3": f16_3, "f3_5": f3_5,
        "f3_5_no_limite": f3_5_lim,
        # quem precisa de troca em breve (sulco < 5): recapagem × compra
        "recap_candidatos": gastos - menos5_lim,
        "compra_nova": menos5_lim,
        "fim_de_vida": fim,
        "estoque": sum(1 for p0 in todos if p0.get("status") == "INVENTORY"),
        "analise": sum(1 for p0 in todos if p0.get("status") == "ANALYSIS"),
    }


def sucata_motivos(todos: list[dict]) -> list[dict]:
    """Por que os pneus morrem — a venda com veículo fica FORA (não é morte)
    e aparece como linha própria na tela, nunca misturada."""
    cont: dict[str, int] = {}
    for p0 in todos:
        if p0.get("status") != "DISPOSAL":
            continue
        m = (p0.get("sucata_motivo") or "(sem motivo)").strip() or "(sem motivo)"
        if "VENDA" in m.upper():
            continue
        cont[m] = cont.get(m, 0) + 1
    return sorted(({"motivo": m, "n": n} for m, n in cont.items()),
                  key=lambda x: -x["n"])[:12]


def analisar(brutos: list[dict]) -> dict:
    """Indicadores a partir do BRUTO da Prolog."""
    return analisar_normalizados([pneu(r) for r in brutos])


def analisar_normalizados(todos: list[dict]) -> dict:
    """Mesmos indicadores, a partir de pneus JA normalizados.

    Existe porque o instantaneo guarda o normalizado: passar de novo por
    `pneu()` quebraria (os nomes de campo ja sao outros) e, pior, poderia
    silenciosamente produzir campos vazios em vez de erro.
    """
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

    # POR VIDA. A contagem sozinha ja mostra a estrutura do parque, mas o que
    # decide recapar e o CPK ao lado: cada vida a mais dilui o custo do pneu por
    # mais quilometro. Medido: R$ 0,021 na 2a vida, R$ 0,016 na 3a, R$ 0,013 na
    # 4a — a economia da recapagem em numero, e nao em opiniao.
    #
    # MEDIANA por vida, e com a contagem de quem TEM CPK junto: numa vida com
    # tres pneus medidos a mediana e frágil, e sem dizer quantos sao ela
    # passaria com o mesmo peso das outras.
    por_vida = []
    for v in sorted({p["vida"] for p in rodando if p["vida"] is not None}):
        na_vida = [p for p in rodando if p["vida"] == v]
        cs = sorted(p["cpk"] for p in na_vida if p["cpk"])
        por_vida.append({
            "vida": v,
            "n": len(na_vida),
            "cpk": cs[len(cs) // 2] if cs else None,
            "cpk_n": len(cs),
            # pneu que ja bateu o teto de recapagens do proprio modelo
            "no_limite": sum(1 for p in na_vida
                             if p["recapagens"] is not None and p["recapagens_max"]
                             and p["recapagens"] >= p["recapagens_max"]),
        })
    sem_vida = sum(1 for p in rodando if p["vida"] is None)

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
        "por_vida": por_vida,
        "sem_vida": sem_vida,
        "pneus": todos,
        "criticos": sorted(
            [p for p in rodando
             if p["estado_sulco"] == "abaixo do legal"
             or p["estado_pressao"] == "muito baixa"],
            key=_urgencia),
        "fim_de_vida": fim_de_vida,
    }
