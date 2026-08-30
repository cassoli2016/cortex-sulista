"""vehicle-performance — os 14 indicadores de condução por veículo.

O QUE MUDOU AQUI, E POR QUE IMPORTA
===================================
A resposta sempre trouxe **14 indicadores** e este módulo lia **3**
(faixa econômica, piloto automático, eco-roll). Os outros 11 eram descartados
em silêncio — inclusive os dois que a premiação mais precisa: `idle` (motor
ligado parado) e `greenRange` (faixa verde). Não há chamada nova: é a MESMA
requisição, lendo o corpo inteiro.

O CUSTO REAL, MEDIDO
====================
A versão anterior deste arquivo dizia "cada chamada leva ~17 s, varrer a frota
seriam mais de 20 minutos". **Medido em 30/08/2026 sobre as 108 placas com km
na competência: 0,79 s por placa, 86 s a frota inteira.** A premissa que
impedia a varredura não existe mais — por isso a coleta em lote passou a ser
possível, e com ela a premiação por indicador.

O ENDPOINT EXIGE PLACA: sem `vehicleIdentification` responde 404 "Veículo não
identificado". Daí a varredura ser placa a placa.

O QUE A NOTA DO FORNECEDOR VALE
===============================
Cada indicador vem com `score`, e ele é guardado — mas NÃO é o que pontua.
Medido na mesma varredura: `greenRange`, `economicRange`, `engineBrake`,
`movement`, `pedalPressureOnLow` e `pedalPressureOnMid` vieram com nota **0 em
108 de 108 veículos**. Uma régua que zera a frota inteira não separa ninguém e
não teria como ser explicada a um motorista que perguntasse por que perdeu o
prêmio. A régua da premiação é NOSSA e está em `api/premiacao/`; a nota deles
fica ao lado, como conferência, e a tela diz quando está zerada em toda a
frota — senão parece que a frota foi mal.
"""
from __future__ import annotations

from pathlib import Path

from api.gobrax import armazenamento
from api.gobrax.cliente import Cliente
from api.gobrax.periodo import mes_inteiro

CAMINHO = "/api/v1/vehicle-performance"
COLECAO = "performance"

# Os 14, agrupados pelo que respondem. O agrupamento não é enfeite: `idle` e
# `movement` somam 100% (é a mesma torta), as quatro faixas de rotação também,
# e as três pressões de pedal também. Ler um número dessas famílias sem os
# irmãos ao lado leva a conclusão errada.
FAMILIAS = [
    ("tempo", "Tempo do motor", ["idle", "movement"]),
    ("rotacao", "Faixa de rotação",
     ["greenRange", "economicRange", "extraEconomicRange", "powerRange"]),
    ("recursos", "Recursos do veículo",
     ["cruiseControl", "ecoRoll", "engineBrake", "leverage"]),
    ("conduta", "Conduta ao volante",
     ["speeding", "pedalPressureOnHig", "pedalPressureOnMid",
      "pedalPressureOnLow"]),
]

INDICADORES = {
    "idle": "Motor ligado parado",
    "movement": "Em movimento",
    "greenRange": "Faixa verde",
    "economicRange": "Faixa econômica",
    "extraEconomicRange": "Faixa extra-econômica",
    "powerRange": "Faixa de potência",
    "cruiseControl": "Piloto automático",
    "ecoRoll": "Eco-roll (embalo)",
    "engineBrake": "Freio motor",
    "leverage": "Aproveitamento de embalo",
    "speeding": "Excesso de velocidade",
    "pedalPressureOnHig": "Pedal — pressão alta",
    "pedalPressureOnMid": "Pedal — pressão média",
    "pedalPressureOnLow": "Pedal — pressão baixa",
}

# Onde MENOS é melhor. Sem isto a tela pintaria "motor ligado parado 60%" de
# verde por ser um número alto, que é o oposto da leitura.
MENOR_MELHOR = {"idle", "speeding", "pedalPressureOnHig", "powerRange"}

# Ordem canônica de leitura (as famílias, achatadas).
ORDEM = [c for _, _, chaves in FAMILIAS for c in chaves]
assert set(ORDEM) == set(INDICADORES), "família e catálogo divergiram"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ind(bruto: dict, chave: str) -> dict:
    d = (bruto or {}).get(chave) or {}
    return {"chave": chave,
            "rotulo": INDICADORES.get(chave, chave),
            "menor_melhor": chave in MENOR_MELHOR,
            "duracao_h": _num(d.get("duration")),
            "percentual": _num(d.get("percentage")),
            "nota_fornecedor": _num(d.get("score"))}


def coletar(placa: str, competencia: str, cliente=None) -> dict:
    """Uma placa. É o que a tela pede ao vivo (menos de 1 s)."""
    if not (placa or "").strip():
        raise ValueError("informe a placa: a API de performance exige veículo")
    ini, fim = mes_inteiro(competencia)
    c = cliente or Cliente()
    corpo = c.get(CAMINHO, {"startDate": ini, "endDate": fim,
                            "vehicleIdentification": placa.strip()}, timeout=120)
    registros = corpo.get("records") or []
    if not registros:
        return {"placa": placa, "competencia": competencia,
                "motoristas": [], "indicadores": []}
    r = registros[0]
    # O CPF VEM NO VÍNCULO E CONTINUA SENDO DESCARTADO AQUI. Foi decisão
    # anterior, com teste guardando, e nada nesta rodada a desfaz: a premiação
    # tem fonte própria de motorista (`api/premiacao/coleta.py`), então trazer
    # o documento seria ampliar exposição de PII sem uso provado.
    motoristas = [{"nome": (m.get("driverName") or "").strip(),
                   "de": m.get("startDate"), "ate": m.get("endDate")}
                  for m in (r.get("drivers") or [])]
    # SÓ OS INDICADORES QUE VIERAM. Devolver os 14 com valor nulo inventaria
    # uma medida que a API não fez — e a tela desenharia uma linha vazia como
    # se fosse desempenho zero.
    brutos = r.get("indicators") or {}
    return {
        "placa": (r.get("vehicleIdentification") or placa).strip(),
        "competencia": competencia,
        "motoristas": motoristas,
        "indicadores": [_ind(brutos, k) for k in ORDEM if k in brutos],
    }


def placas_da_competencia(competencia: str, path: Path | None = None) -> list[str]:
    """As placas que a Gobrax CONHECE no mês, tiradas do cache de estatísticas.

    Vem do cache e não de uma chamada nova de propósito: é a mesma lista que
    define o universo em toda a telemetria, e assim a varredura não inventa um
    universo próprio que discordaria do resto da tela.
    """
    linhas = armazenamento.ler("estatisticas", competencia, path)
    return sorted({(l.get("placa") or "").strip() for l in linhas
                   if (l.get("placa") or "").strip() and l.get("km")})


def coletar_frota(competencia: str, cliente=None, path: Path | None = None,
                  placas: list[str] | None = None) -> list[dict]:
    """A frota inteira, placa a placa (~0,8 s cada).

    UMA PLACA QUE FALHA NÃO DERRUBA A VARREDURA: são 108 chamadas e uma
    instabilidade no meio não pode custar as outras 107. A placa que falhou
    fica de fora e a próxima execução tenta de novo — como a coleta anterior
    continua válida, isso degrada, não quebra.
    """
    c = cliente or Cliente()
    alvos = placas if placas is not None else placas_da_competencia(competencia, path)
    saida: list[dict] = []
    for placa in alvos:
        try:
            d = coletar(placa, competencia, c)
        except Exception:  # noqa: BLE001
            continue
        if not d["indicadores"]:
            continue
        linha = {"placa": d["placa"], "motoristas": d["motoristas"]}
        for ind in d["indicadores"]:
            linha[ind["chave"]] = {"pct": ind["percentual"],
                                   "h": ind["duracao_h"],
                                   "nota": ind["nota_fornecedor"]}
        saida.append(linha)
    return saida


def sincronizar(competencia: str, cliente=None, path: Path | None = None) -> dict:
    linhas = coletar_frota(competencia, cliente, path)
    gravadas = armazenamento.gravar(COLECAO, competencia, linhas, path)
    return {"competencia": competencia, "gravadas": gravadas}


def ler(competencia: str, path: Path | None = None) -> list[dict]:
    return armazenamento.ler(COLECAO, competencia, path)


def resumo_frota(competencia: str, path: Path | None = None) -> dict:
    """Distribuição de cada indicador na frota, para a tela dar referência.

    UM NÚMERO SOZINHO NÃO DECIDE NADA: "motor ligado parado 18%" é muito? Só a
    mediana da frota responde. Mesma regra da ficha do motorista, onde o valor
    do indivíduo só significa algo ao lado do da filial e do da frota.

    Traz também `nota_zerada`: quantos indicadores vieram com nota 0 em TODA a
    frota. É o aviso que impede alguém de ler a nota do fornecedor como
    desempenho ruim generalizado.
    """
    linhas = ler(competencia, path)
    fora = {"competencia": competencia, "veiculos": len(linhas), "indicadores": []}
    for chave in ORDEM:
        vals = sorted(l[chave]["pct"] for l in linhas
                      if isinstance(l.get(chave), dict) and l[chave].get("pct") is not None)
        notas = [l[chave]["nota"] for l in linhas
                 if isinstance(l.get(chave), dict) and l[chave].get("nota") is not None]
        if not vals:
            continue
        q = lambda f: vals[min(len(vals) - 1, int(len(vals) * f))]  # noqa: E731
        fora["indicadores"].append({
            "chave": chave, "rotulo": INDICADORES[chave],
            "menor_melhor": chave in MENOR_MELHOR,
            "min": vals[0], "p25": q(0.25), "mediana": q(0.5),
            "p75": q(0.75), "max": vals[-1],
            "veiculos": len(vals),
            "nota_zerada": bool(notas) and not any(notas),
        })
    return fora
