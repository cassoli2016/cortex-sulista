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


def resumo() -> dict:
    """Agregado da última coleta. Nunca levanta: a Torre não pode cair porque
    a telemetria está indisponível — devolve `disponivel: False`."""
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
    dias = None
    if quando:
        try:
            dias = (datetime.now() - datetime.strptime(quando, "%Y-%m-%d %H:%M:%S")).days
        except ValueError:
            pass

    return {
        "disponivel": True,
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
