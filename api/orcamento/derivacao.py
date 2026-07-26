"""Derivação do baseline orçamentário a partir do histórico.

Método: MÊS ESPELHO + fator de tendência. Cada mês do ano orçado parte do mesmo
mês-calendário da base, o que preserva a sazonalidade real (dezembro cai ~40% na
Sulista) em vez de achatá-la numa média.

Contas esporádicas quebram o espelho: 41 das 355 contas aparecem em 1 ou 2 meses,
e espelhar isso produziria orçamento errático com aparência de número. Abaixo do
corte de recorrência a conta sai pela mediana e nasce marcada para revisão.

Módulo PURO: não conhece banco nem HTTP, para poder ser testado isolado.
"""
from __future__ import annotations

from statistics import median

# 75% dos meses da base (9 de 12). Separa as 212 contas recorrentes das 41 esporádicas.
RECORRENCIA_MIN = 0.75


def derivar(historico: dict[str, dict[str, float]],
            meses_base: list[str],
            fator: float) -> list[dict]:
    """Gera o baseline de 12 meses para cada conta.

    historico:   {conta: {'YYYY-MM': valor}} — SOMENTE meses fechados.
    meses_base:  os 'YYYY-MM' da base, em ordem cronológica.
    fator:       tendência, ex.: -0.05 para orçar 5% abaixo do espelho.

    Devolve uma linha por conta × mês (1-12) com valor, origem e cobertura.
    """
    minimo = RECORRENCIA_MIN * len(meses_base)
    # mês-calendário -> 'YYYY-MM' da base (o mais recente, se a base tiver repetição)
    espelho_de: dict[int, str] = {}
    for m in meses_base:
        espelho_de[int(m[5:7])] = m

    linhas: list[dict] = []
    for conta, serie in sorted(historico.items()):
        # valor 0 não é movimento: conta lançada zerada não vira recorrente
        com_dado = {m: v for m, v in serie.items() if m in meses_base and v}
        n = len(com_dado)
        recorrente = n >= minimo
        med = median(com_dado.values()) if com_dado else 0.0

        for mes in range(1, 13):
            fonte = espelho_de.get(mes)
            valor_espelho = com_dado.get(fonte) if fonte else None

            if recorrente:
                # recorrente sem o mês espelho não inventa valor pela mediana
                if valor_espelho is None:
                    valor, origem = 0.0, "sem_base"
                else:
                    valor, origem = valor_espelho * (1 + fator), "espelho"
            elif com_dado:
                valor, origem = med * (1 + fator), "mediana"
            else:
                valor, origem = 0.0, "sem_base"

            linhas.append({
                "conta": conta,
                "mes": mes,
                "valor_baseline": round(valor, 2),
                "origem": origem,
                "meses_com_dado": n,
            })
    return linhas
