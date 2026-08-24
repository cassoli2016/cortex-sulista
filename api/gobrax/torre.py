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


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def resumo() -> dict:
    """Agregado da última coleta. Nunca levanta: a Torre não pode cair porque
    a telemetria está indisponível — devolve `disponivel: False`."""
    try:
        log = arm.ultima("estatisticas")
        linhas = arm.ler("estatisticas", log["competencia"]) if log else []
    except Exception:  # noqa: BLE001
        log, linhas = None, []

    if not linhas:
        return {"disponivel": False, "motivo": "nenhuma coleta de telemetria gravada"}

    km_tot = lit_tot = 0.0
    freadas = freadas_alta = 0
    vels, consumos, abaixo, suspeitos = [], [], 0, 0

    for r in linhas:
        km, lit = _num(r.get("km")) or 0.0, _num(r.get("litros")) or 0.0
        km_l, vel = _num(r.get("km_l")), _num(r.get("vel_media"))
        km_tot += km
        lit_tot += lit
        freadas += int(_num(r.get("freadas")) or 0)
        freadas_alta += int(_num(r.get("freadas_alta")) or 0)
        if vel and vel > 0:
            vels.append(vel)
        if plausivel(km_l):
            consumos.append(km_l)
            if km_l < ALVO_KM_L:
                abaixo += 1
        elif km_l is not None:
            suspeitos += 1

    # km/l da FROTA é km total ÷ litros totais, não a média das médias: veículo
    # que rodou 200 km pesaria igual a um que rodou 20.000.
    km_l_frota = (km_tot / lit_tot) if lit_tot > 0 else None
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
        "km_total": round(km_tot, 1),
        "litros_total": round(lit_tot, 1),
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
        "freadas_alta_por_mil_km": (round(1000 * freadas_alta / km_tot, 2)
                                    if km_tot > 0 else None),
        "competencia": (log or {}).get("competencia"),
        "coletado_em": quando,
        "dias_atras": dias,
    }
