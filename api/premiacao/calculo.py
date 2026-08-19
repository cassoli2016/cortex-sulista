"""Regra de premiação por nota × km. Módulo PURO.

    elegível = nota >= nota_minima E km >= km_minimo
    premio   = km × valor_por_km × (nota / 100)

Substitui a regra anterior (litros economizados), que dependia da média de
consumo por motorista — dado que a API pública da Gobrax não fornece. Decisão do
usuário em 19/08/2026.

Snapshot antigo NÃO é recalculado: ele registra a regra que o gerou, e mês já
pago continua exibindo o valor com que foi pago.

Linha não elegível continua VISÍVEL na lista, com o motivo, e fica fora dos
totais — mesmo tratamento que a regra anterior dava a leitura implausível.
"""
from __future__ import annotations

REGRA = "nota_km"
NOTA_MAXIMA = 100.0


def calcular(motoristas: list[dict], params: dict) -> dict:
    valor_km = float(params["valor_por_km"])
    nota_min = float(params["nota_minima"])
    km_min = float(params["km_minimo"])

    linhas: list[dict] = []
    for m in motoristas:
        km = float(m.get("km") or 0)
        nota = float(m.get("nota") or 0)
        motivo = None
        if km < 0 or nota < 0:
            motivo = "leitura inválida"
        elif nota < nota_min:
            motivo = "nota abaixo da mínima"
        elif km < km_min:
            motivo = "km abaixo do mínimo"
        elegivel = motivo is None
        # nota acima de 100 é defeito da origem: limitar evita inflar o prêmio
        nota_efetiva = min(nota, NOTA_MAXIMA)
        premio = round(km * valor_km * (nota_efetiva / 100.0), 2) if elegivel else 0
        linhas.append({**m, "elegivel": elegivel, "motivo": motivo,
                       "premio": premio})

    premiados = [l for l in linhas if l["elegivel"] and l["premio"] > 0]
    return {
        "regra": REGRA,
        "linhas": sorted(linhas, key=lambda l: -l["premio"]),
        "motoristas": len(linhas),
        "premiados": len(premiados),
        "premio_total": round(sum(l["premio"] for l in premiados), 2),
        "km_total": round(sum(float(l.get("km") or 0) for l in linhas), 2),
        "params": {"valor_por_km": valor_km, "nota_minima": nota_min,
                   "km_minimo": km_min},
    }
