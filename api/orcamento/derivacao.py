"""Derivação do baseline orçamentário a partir do histórico.

Método: MÊS ESPELHO + fator de tendência. Cada mês do ano orçado parte do mesmo
mês-calendário da base, o que preserva a sazonalidade real (dezembro cai ~40% na
Sulista) em vez de achatá-la numa média.

Contas esporádicas quebram o espelho: 41 das 355 contas aparecem em 1 ou 2 meses,
e espelhar isso produziria orçamento errático com aparência de número. Abaixo do
corte de recorrência a conta sai pela mediana — SOMENTE nos meses-calendário cujo
espelho teve movimento — e nasce marcada para revisão. Gravar a mediana nos 12
meses (versão original desta regra) anualizava a conta em ~12x: as 91 contas
esporádicas da base somavam R$ 43,7 mi de baseline contra R$ 3,9 mi de histórico.
Preservar QUANDO o gasto acontece é também a informação que importa em provisão
e evento pontual.

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
                # mediana SÓ nos meses cujo espelho teve movimento: o total anual
                # fica ~= mediana x n, na ordem do histórico, e o valor cai no mês
                # em que a conta historicamente acontece
                if valor_espelho is None:
                    valor, origem = 0.0, "sem_base"
                else:
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


INDICE_MIN, INDICE_MAX = 0.0, 3.0


def indices_sazonais(serie_linha: dict[str, dict[str, float]],
                     meses24: list[str]) -> tuple[dict[str, dict[int, float]], list[str]]:
    """Índice sazonal por linha da DRE: média do mês-calendário ÷ média geral,
    renormalizado para média 1. Linha sem massa, com índice fora de [0,3] ou
    com menos de 24 meses de dado vira FLAT (índice 1) e entra em linhas_flat —
    forma sem sentido econômico não pode moldar orçamento."""
    flat_ = {m: 1.0 for m in range(1, 13)}
    indices: dict[str, dict[int, float]] = {}
    linhas_flat: list[str] = []
    for linha, serie in serie_linha.items():
        valores = [serie.get(m) for m in meses24]
        if any(v is None for v in valores):
            indices[linha] = dict(flat_)
            linhas_flat.append(linha)
            continue
        media_geral = sum(valores) / len(valores)
        if abs(media_geral) < 1e-9:
            indices[linha] = dict(flat_)
            linhas_flat.append(linha)
            continue
        soma_cal: dict[int, float] = {m: 0.0 for m in range(1, 13)}
        n_cal: dict[int, int] = {m: 0 for m in range(1, 13)}
        for m, v in zip(meses24, valores):
            cal = int(m[5:7])
            soma_cal[cal] += v
            n_cal[cal] += 1
        bruto = {m: (soma_cal[m] / n_cal[m]) / media_geral for m in range(1, 13)}
        media_idx = sum(bruto.values()) / 12
        norm = {m: v / media_idx for m, v in bruto.items()} if media_idx else bruto
        if any(not (INDICE_MIN <= v <= INDICE_MAX) for v in norm.values()):
            indices[linha] = dict(flat_)
            linhas_flat.append(linha)
            continue
        indices[linha] = norm
    return indices, sorted(linhas_flat)


def derivar_semestre(historico: dict[str, dict[str, float]],
                     meses_base: list[str],
                     indices: dict[str, dict[int, float]],
                     mapa_linha: dict[str, str | None],
                     fator: float) -> list[dict]:
    """Nível da janela base (soma/len(meses_base)) × índice sazonal da LINHA × (1+fator).
    Sem corte de recorrência: a média semestral já dilui a conta esporádica e a
    forma vem da linha, não da conta. Conta sem movimento -> sem_base 12×0."""
    linhas: list[dict] = []
    for conta, serie in sorted(historico.items()):
        com_dado = {m: v for m, v in serie.items() if m in meses_base and v}
        nivel = sum(com_dado.values()) / len(meses_base)
        rot = mapa_linha.get(conta)
        idx = indices.get(rot) if rot else None
        for mes in range(1, 13):
            if not com_dado:
                valor, origem = 0.0, "sem_base"
            else:
                fator_mes = idx.get(mes, 1.0) if idx else 1.0
                valor, origem = nivel * fator_mes * (1 + fator), "semestre"
            linhas.append({
                "conta": conta,
                "mes": mes,
                "valor_baseline": round(valor, 2),
                "origem": origem,
                "meses_com_dado": len(com_dado),
            })
    return linhas
