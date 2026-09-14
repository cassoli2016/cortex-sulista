"""Telemetria resumida para os cartões da Torre de Controle.

LÊ SÓ O CACHE LOCAL (`data/telemetria.db`), nunca chama a Gobrax. A Torre
recarrega sozinha a cada 2 minutos: disparar coleta nesse ritmo bombardearia
a API do fornecedor — e a coleta leva 73 s, o que penduraria a tela. Mesma
regra que já vale para o snapshot do Copiloto.

Consequência assumida: o dado é da última coleta, não de agora. A Torre
mostra posição ao vivo, então misturar um agregado de dias atrás sem avisar
faria o operador ler telemetria velha como se fosse do momento — por isso
`coletado_em` e `dias_atras` voltam no payload e a tela os exibe.
"""
from __future__ import annotations

import re
from datetime import datetime

from api.gobrax import armazenamento as arm
from api.gobrax.consumo import plausivel

# Frota pesada roda de 1,5 a 4 km/l; fora disso a LEITURA é que está furada,
# não o consumo (mesma régua da tela de Combustível, ver CLAUDE.md).
ALVO_KM_L = 2.5

# Velocidade média de caminhão não passa disso. A coleta trouxe uma linha com
# 5.210 km/h; sem o teto ela sozinha subia a média da frota para 101,8 km/h.
VEL_MAX_PLAUSIVEL = 130.0


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def placa_norm(s) -> str:
    """A placa como chave de comparação.

    AS DUAS COLETAS DA GOBRAX NÃO ESCREVEM A PLACA IGUAL: `estatisticas` grava
    "AAA1A11", e `performance` grava "AAA1A11 - FR1234" (placa e número de
    frota juntos, no campo de identificação do veículo). Medido em 13/09/2026:
    comparando o campo cru, 47 dos 49 veículos da performance ficavam "fora do
    ERP" — só casavam os dois agregados, que vêm sem o número.
    """
    return re.sub(r"[^A-Z0-9]", "", str(s or "").split(" - ")[0].upper())


def _dias_atras(quando):
    if not quando:
        return None
    try:
        return (datetime.now() - datetime.strptime(quando, "%Y-%m-%d %H:%M:%S")).days
    except ValueError:
        return None


# A torta de pedal: as três pressões somam 100% do tempo de pedal.
PEDAL = ("pedalPressureOnHig", "pedalPressureOnMid", "pedalPressureOnLow")


def conducao(frota: set[str] | None = None) -> dict:
    """Três indicadores de condução da frota, da coleta DIÁRIA de performance.

    Cada um é uma RAZÃO DE TEMPO somada na frota — Σ numerador ÷ Σ base —, e
    não a média dos percentuais: veículo que rodou 10 h pesaria igual a um que
    rodou 200 h. A base de cada um foi conferida contra o percentual que o
    próprio fornecedor dá por veículo (diferença 0,0 nos 46 da frota, em
    13/09/2026):

      motor ligado parado  = idle ÷ (idle + movement)     — do tempo de motor
      faixa extra-econômica = extraEconomicRange ÷ movement — do tempo andando
      pedal crítico         = pressão alta ÷ as três pressões — do tempo de pedal

    A DURAÇÃO NÃO VAI PARA A TELA: o campo se chama `h`, mas um veículo soma
    6.649 dele em treze dias, o que não é hora. Na razão a unidade se cancela;
    como número absoluto seria um valor sem unidade conhecida.
    """
    try:
        log = arm.competencia_atual("performance")
        linhas = arm.ler("performance", log["competencia"]) if log else []
    except Exception:  # noqa: BLE001
        log, linhas = None, []
    if frota is not None:
        linhas = [l for l in linhas if placa_norm(l.get("placa")) in frota]

    def dur(l, chave):
        d = l.get(chave)
        return _num(d.get("h")) if isinstance(d, dict) else None

    def razao(numerador: str, base: tuple, casas: int = 1) -> tuple:
        n = d = 0.0
        veic = 0
        for l in linhas:
            partes = [dur(l, k) for k in base]
            num = dur(l, numerador)
            if num is None or any(p is None for p in partes) or sum(partes) <= 0:
                continue
            n += num
            d += sum(partes)
            veic += 1
        return (round(100 * n / d, casas) if d > 0 else None), veic

    # DUAS CASAS no motor parado e no pedal critico (quem opera, 14/09/2026):
    # com uma, os dois deram 14,3% no mesmo dia (14,29 x 14,34) e pareciam o
    # mesmo numero repetido. A faixa extra-economica segue com uma.
    parado, v1 = razao("idle", ("idle", "movement"), casas=2)
    extra, v2 = razao("extraEconomicRange", ("movement",))
    pedal, v3 = razao("pedalPressureOnHig", PEDAL, casas=2)
    quando = (log or {}).get("quando")
    return {
        "motor_parado_pct": parado,
        "faixa_extra_eco_pct": extra,
        "pedal_critico_pct": pedal,
        "conducao_veiculos": max(v1, v2, v3),
        "conducao_coletado_em": quando,
        "conducao_dias_atras": _dias_atras(quando),
    }


def resumo(frota: set[str] | None = None) -> dict:
    """Agregado da última coleta. Nunca levanta: a Torre não pode cair porque
    a telemetria está indisponível — devolve `disponivel: False`.

    `frota`: placas (já em `placa_norm`) da frota da casa — próprios e
    locados. Com ela, o agregado é SÓ da frota que está rodando (km no mês),
    pedido de quem opera em 13/09/2026: os agregados telemetrados são poucos
    (2 de 49 na medição do dia) e não têm alvo nosso de consumo. Sem ela, o
    comportamento antigo: tudo o que a Gobrax trouxe.
    """
    try:
        # competencia_atual e nao ultima(): `ultima` ordena por INSERCAO, e o
        # coletor agendado busca o mes corrente E o anterior — gravando o
        # anterior por ultimo, a Torre voltava a mostrar o mes passado.
        log = arm.competencia_atual("estatisticas")
        linhas = arm.ler("estatisticas", log["competencia"]) if log else []
    except Exception:  # noqa: BLE001
        log, linhas = None, []

    if not linhas:
        return {"disponivel": False, "motivo": "nenhuma coleta de telemetria gravada"}
    if frota is not None:
        linhas = [r for r in linhas if placa_norm(r.get("placa")) in frota
                  and (_num(r.get("km")) or 0) > 0]
        if not linhas:
            return {"disponivel": False,
                    "motivo": "nenhum veículo da frota rodando na coleta"}

    km_tot = lit_tot = 0.0
    km_ok = lit_ok = 0.0
    freadas = freadas_alta = freadas_alta_ok = 0
    vels, consumos, abaixo, suspeitos = [], [], 0, 0
    vel_fora = 0

    for r in linhas:
        km, lit = _num(r.get("km")) or 0.0, _num(r.get("litros")) or 0.0
        km_l, vel = _num(r.get("km_l")), _num(r.get("vel_media"))
        km_tot += km
        lit_tot += lit
        freadas += int(_num(r.get("freadas")) or 0)
        freadas_alta += int(_num(r.get("freadas_alta")) or 0)
        if plausivel(km_l):
            freadas_alta_ok += int(_num(r.get("freadas_alta")) or 0)
        if vel and vel > 0:
            if vel <= VEL_MAX_PLAUSIVEL:
                vels.append(vel)
            else:
                vel_fora += 1
        if plausivel(km_l):
            consumos.append(km_l)
            km_ok += km
            lit_ok += lit
            if km_l < ALVO_KM_L:
                abaixo += 1
        elif km_l is not None:
            suspeitos += 1

    # km/l da FROTA é km ÷ litros, não a média das médias: veículo que rodou
    # 200 km pesaria igual a um que rodou 20.000.
    #
    # SÓ SOBRE QUEM PASSA NA RÉGUA. Somar todas as linhas deixava 14 leituras
    # furadas de 105 envenenarem a frota inteira: uma delas trazia 66.762
    # LITROS num mês (tanque de caminhão tem 400 a 600) e outra 50.796 km em
    # dois dias. O painel de TV mostrava "0,7 km/l" em vermelho enquanto o
    # cartão ao lado dizia que 91 veículos tinham leitura válida e só 26
    # estavam abaixo do alvo — o número principal contradizia o próprio
    # subtítulo. Sobre os 91 plausíveis o resultado é 2,81 km/l.
    km_l_frota = (km_ok / lit_ok) if lit_ok > 0 else None
    # Cinto e suspensório: se ainda assim o agregado cair fora da faixa física,
    # é `n/d`. Número impossível some da tela, não é pintado de vermelho.
    if km_l_frota is not None and not plausivel(km_l_frota):
        km_l_frota = None
    quando = (log or {}).get("quando")
    dias = _dias_atras(quando)

    return {
        "disponivel": True,
        "escopo": "frota" if frota is not None else "todos",
        **conducao(frota),
        "veiculos": len(linhas),
        "km_total": round(km_ok, 1),
        "litros_total": round(lit_ok, 1),
        "km_total_bruto": round(km_tot, 1),
        "litros_total_bruto": round(lit_tot, 1),
        "vel_fora_da_faixa": vel_fora,
        "km_l_frota": round(km_l_frota, 2) if km_l_frota else None,
        "alvo_km_l": ALVO_KM_L,
        "abaixo_do_alvo": abaixo,
        "com_consumo_valido": len(consumos),
        "leitura_suspeita": suspeitos,
        "vel_media": round(sum(vels) / len(vels), 1) if vels else None,
        "freadas": freadas,
        "freadas_alta": freadas_alta,
        # freada brusca por 1.000 km normaliza frotas de tamanhos diferentes —
        # o total absoluto só diz quem rodou mais
        # RAZÃO SÓ SOBRE A INTERSEÇÃO: numerador e denominador do MESMO
        # conjunto de veículos. Um com 50 mil km espúrios diluía a taxa da
        # frota; contar as freadas dele sobre o km dos outros inflava. O total
        # absoluto de freadas continua acima, para o subtítulo do cartão.
        "freadas_alta_por_mil_km": (round(1000 * freadas_alta_ok / km_ok, 2)
                                    if km_ok > 0 else None),
        "freadas_alta_com_regua": freadas_alta_ok,
        "competencia": (log or {}).get("competencia"),
        "coletado_em": quando,
        "dias_atras": dias,
    }
