"""driversOverview — km e nota por motorista, por mês.

A API devolve o mês pedido E o seguinte (porque endDate tem de ser diferente de
startDate); filtramos aqui para o mês que interessa.

Dois campos da resposta são descartados de propósito: DocumentNumber, que é CPF
e não tem uso nosso, e Reward, que vem zerado — o prêmio é calculado por nós.
"""
from __future__ import annotations

from api.gobrax.cliente import Cliente, mes_api

CAMINHO = "/api/v2/driversOverview"


def coletar(mes: str, cliente=None) -> list[dict]:
    ini, fim = mes_api(mes)
    c = cliente or Cliente()
    corpo = c.get(CAMINHO, {"documentNumbers": "", "startDate": ini,
                            "endDate": fim}, timeout=180)
    alvo = ini  # 'MM-AAAA', o mesmo formato que vem em Overview[].Date
    saida = []
    for m in (corpo.get("data") or []):
        for o in (m.get("Overview") or []):
            if (o.get("Date") or "") != alvo:
                continue
            km = float(o.get("TotalKM") or 0)
            nota = float(o.get("Score") or 0)
            if km <= 0 and nota <= 0:
                continue      # sem atividade no mês
            saida.append({"driverId": m.get("ID"),
                          "driverName": (m.get("Name") or "").strip(),
                          "km": km, "nota": nota})
    return saida
