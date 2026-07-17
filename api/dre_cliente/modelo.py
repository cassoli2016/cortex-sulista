"""Modelo de linhas da DRE por cliente (v1: ate Margem de Contribuicao).

O backbone ESPELHA a DRE oficial (api.queries.DRE_MODELO): mesmas linhas, mesma
ordem e nomenclatura, cortando apos MARGEM DE CONTRIBUICAO (custo fixo do ativo
e abaixo ficam para o v2). A linha MARGEM DE CONTRIBUICAO e nova (nao existe na
DRE oficial, que agrupa CV+CF+creditos em CSP e vai direto a LUCRO BRUTO).

`metodo_da_linha` diz COMO cada linha do backbone desce ao cliente.
`classificar_cv` diz como cada sub-agrupador de Custo Variavel (CV - ...) e
custeado por viagem (a de-para do spec), usada pela camada de custeio.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Linha:
    rotulo: str
    nivel: int
    metodo: str
    componentes: list[str] = field(default_factory=list)


# Backbone: subsequencia estrita da DRE_MODELO oficial + a linha MC ao final.
LINHAS_CLIENTE: list[Linha] = [
    Linha("RECEITA BRUTA", 0, "direto_viagem"),
    Linha("DEDUCOES DA RECEITA", 0, "formula",
          ["IMPOSTOS FEDERAIS", "IMPOSTOS ESTADUAIS", "IMPOSTOS MUNICIPAIS",
           "CONTRIBUICAO PREVIDENCIARIA", "ANULACOES", "DESCONTOS"]),
    Linha("IMPOSTOS FEDERAIS", 1, "deducao_pct"),
    Linha("IMPOSTOS ESTADUAIS", 1, "deducao_pct"),
    Linha("IMPOSTOS MUNICIPAIS", 1, "deducao_pct"),
    Linha("CONTRIBUICAO PREVIDENCIARIA", 1, "deducao_pct"),
    Linha("ANULACOES", 1, "direto_cte"),
    Linha("DESCONTOS", 1, "direto_cte"),
    Linha("RECEITA LIQUIDA", 0, "formula", ["RECEITA BRUTA", "DEDUCOES DA RECEITA"]),
    Linha("CUSTO VARIAVEL", 0, "custo_variavel"),
    Linha("CREDITOS TRIBUTARIOS", 0, "credito_pct"),
    Linha("MARGEM DE CONTRIBUICAO", 0, "formula",
          ["RECEITA LIQUIDA", "CUSTO VARIAVEL", "CREDITOS TRIBUTARIOS"]),
    # v2: custo fixo do ativo alocado por dia-veiculo -> Margem Direta
    Linha("CUSTO FIXO", 0, "fixo_dia_veiculo"),
    Linha("MARGEM DIRETA DO CLIENTE", 0, "formula",
          ["MARGEM DE CONTRIBUICAO", "CUSTO FIXO"]),
]

# imposto (rotulo da linha) -> chave em Params.deducoes_pct
IMPOSTO_PARAM = {
    "IMPOSTOS FEDERAIS": "federais",
    "IMPOSTOS ESTADUAIS": "estaduais",
    "IMPOSTOS MUNICIPAIS": "municipais",
    "CONTRIBUICAO PREVIDENCIARIA": "previdenciaria",
}

_POR_ROTULO = {l.rotulo: l for l in LINHAS_CLIENTE}


def rotulos() -> list[str]:
    return [l.rotulo for l in LINHAS_CLIENTE]


def metodo_da_linha(rotulo: str) -> str:
    return _POR_ROTULO[rotulo].metodo


def classificar_cf(agrupador: str) -> str:
    """Base de alocacao por dia-veiculo do agrupador de custo fixo (v2):
    'locado' (locacao), 'proprio' (depreciacao/juros), 'ativo' (demais CF do
    ativo rodante) ou 'nao_desce' (fixo de estrutura -> consolidado)."""
    a = agrupador.upper()
    if "PESSOAL OPERAC" in a or "DESPESAS ADM" in a or "PATRIMONIAL" in a:
        return "nao_desce"
    if "LOCA" in a:                       # LOCACAO DE EQUIPAMENTOS
        return "locado"
    if "DEPRECIA" in a or "JUROS" in a:   # deprec e juros do veiculo proprio/financiado
        return "proprio"
    if a.startswith("CF - "):             # folha mot, rastreamento, GR, IPVA, seguros veic/ambiental
        return "ativo"
    return "nao_desce"


def classificar_cv(agrupador: str) -> str:
    """De-para do spec: sub-agrupador de CV -> metodo de custeio por viagem."""
    a = agrupador.upper()
    if "AGREGAD" in a or "TERCEIR" in a:
        return "direto_viagem"          # repasse
    if "COMBUST" in a:
        return "combustivel_km"         # rateio por km do veiculo proprio
    if "MANUTEN" in a or "PNEU" in a:
        return "taxa_km"                # taxa rolling R$/km + variacao de absorcao
    return "direto_viagem"              # pedagio, diarias, carga/desc, seguro, px, outros
