"""Camada de banco (fetch do AVA) da DRE por cliente.

ATENCAO: escrito reusando padroes JA validados (RENT_CLI_SQL, HEUR_SEMCLI_SQL,
_COM_BASE, DRE_AG_SQL / get_dre), mas AINDA NAO VALIDADO contra dados reais -
o tunel SSH ao AVA estava fora do ar no desenvolvimento. Revisar query a query
com o tunel no ar (Task 10/14): PKs completas, semantica de campos, LATIN-1,
merge-join do PG 9.3. Os pontos incertos estao marcados com "VALIDAR".

Convencao: fetch_* retornam dados no formato consumido pelas funcoes puras de
custeio/agregacao. Nenhuma regra de negocio aqui alem do shaping.
"""
from __future__ import annotations

from typing import Any

from .. import queries
from ..queries import _comp_bounds

# Codigos de utilizacao considerados frota propria (make): FROTA + LOCACAO.
PROPRIO = ("TRA", "LOC")

# id da viagem = PK da programacaoembarque (grupo, empresa, filial, dif, numero).
_PK = "p.grupo, p.empresa, p.filial, p.diferenciadornumero, p.numero"
# competencia = mes de termino da viagem (fallback saida/emissao).
_COMPET = "coalesce(p.dtchegada, p.dtsaida, p.dtemissao)"

# Viagens (carregadas E vazias: SEM o filtro p.tipo<>3, pois o vazio e atribuido
# ao cliente originador em Python). DISTINCT ON dedupa o fan-out da coleta.
VIAGENS_SQL = f"""
SELECT DISTINCT ON ({_PK})
       p.grupo, p.empresa, p.filial, p.diferenciadornumero, p.numero,
       p.veiculo AS placa,
       p.dtsaida, p.dtchegada, p.tipo,
       coalesce(p.kmfretecompra,0)::float8 AS km,
       coalesce(p.valorfrete,0)::float8 AS valorfrete,
       coalesce(p.valorfretecompra,0)::float8 AS valorfretecompra,
       v.utilizacaoveiculo AS utilizacao,
       coalesce('AG'||ag.codigo::text, co.cnpjcpfcodigopagadorfrete) AS cliente_codigo,
       coalesce(nullif(trim(ag.descricao),''), nullif(trim(cp.nomefantasia),''),
                nullif(trim(cp.razaosocial),'')) AS cliente_nome
FROM programacaoembarque p
LEFT JOIN veiculo v ON v.placa = p.veiculo
LEFT JOIN coleta co ON co.grupo=p.grupo AND co.empresa=p.empresa
  AND co.filial=p.filialdocumentoorigem AND co.unidade=p.unidadedocumentoorigem
  AND co.diferenciadornumero=p.diferenciadornumerodocumentoorigem
  AND co.numero=p.numerodocumentoorigem
LEFT JOIN agrupamentocliente_cnpjcpfcodigo av ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
LEFT JOIN agrupamentocliente ag ON ag.codigo = av.codigo
LEFT JOIN cadastro cp ON cp.codigo = co.cnpjcpfcodigopagadorfrete
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1
  AND {_COMPET} >= %(de)s::date AND {_COMPET} < %(ate)s::date
  AND (p.filial = %(filial)s OR %(filial)s::int IS NULL)
ORDER BY {_PK}
"""

# Combustivel proprio por placa (CTA Plus). So frota propria (TRA/LOC); o
# combustivel de AGR/TER esta no repasse. VALIDAR: ARLA entra no custo do razao?
ABASTEC_SQL = """
SELECT a.veiculo_placa AS placa, sum(coalesce(a.custo,0))::float8 AS custo
FROM sulista.ctaplus_abastecimentos a
JOIN veiculo v ON v.placa = a.veiculo_placa AND v.utilizacaoveiculo IN ('TRA','LOC')
WHERE a.data_inicio_abastecimento >= %(de)s::date
  AND a.data_inicio_abastecimento < %(ate)s::date
GROUP BY a.veiculo_placa
"""

# Custo de manutencao/pneus por placa na janela rolling (ordemservico; placa = o.veiculo).
OS_CUSTO_SQL = """
SELECT o.veiculo AS placa, sum(coalesce(o.valortotal,0))::float8 AS custo
FROM ordemservico o
WHERE o.dtemissao >= %(de)s::date AND o.dtemissao < %(ate)s::date
GROUP BY o.veiculo
"""

# Km rodado por placa na janela rolling (base da taxa R$/km).
KM_PLACA_SQL = f"""
SELECT DISTINCT ON ({_PK}) p.veiculo AS placa, coalesce(p.kmfretecompra,0)::float8 AS km
FROM programacaoembarque p
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1
  AND {_COMPET} >= %(de)s::date AND {_COMPET} < %(ate)s::date
ORDER BY {_PK}
"""

# Linhas-folha do backbone que puxamos da DRE oficial (rotulos == DRE_MODELO).
_LEAF_OFICIAL = (
    "RECEITA BRUTA", "IMPOSTOS FEDERAIS", "IMPOSTOS ESTADUAIS",
    "IMPOSTOS MUNICIPAIS", "CONTRIBUICAO PREVIDENCIARIA", "ANULACOES",
    "DESCONTOS", "CUSTO VARIAVEL", "CREDITOS TRIBUTARIOS",
)


def viagem_id(r: dict) -> str:
    return f"{r['grupo']}-{r['empresa']}-{r['filial']}-{r['diferenciadornumero']}-{r['numero']}"


def fetch_viagens(cur, de: str, ate: str, filial: int | None) -> list[dict[str, Any]]:
    cur.execute(VIAGENS_SQL, {"de": de, "ate": ate, "filial": filial})
    out = []
    for r in cur.fetchall():
        util = r.get("utilizacao")
        out.append({
            "id": viagem_id(r),
            "placa": r["placa"],
            "dtsaida": r["dtsaida"] or r["dtchegada"],
            "dtchegada": r["dtchegada"] or r["dtsaida"],
            "tipo": r["tipo"],
            "km": r["km"],
            "valorfrete": r["valorfrete"],
            "valorfretecompra": r["valorfretecompra"],
            "is_proprio": util in PROPRIO,
            "tipo_operacao": util,
            "cliente_codigo": r.get("cliente_codigo"),
            "cliente_nome": r.get("cliente_nome"),
        })
    return out


def fetch_abastecimentos(cur, de: str, ate: str) -> dict[str, float]:
    cur.execute(ABASTEC_SQL, {"de": de, "ate": ate})
    return {r["placa"]: r["custo"] for r in cur.fetchall()}


def fetch_taxa_km(cur, de_janela: str, ate: str) -> dict[str, float]:
    """Taxa rolling R$/km por placa = custo de OS na janela / km na janela."""
    cur.execute(OS_CUSTO_SQL, {"de": de_janela, "ate": ate})
    custo = {r["placa"]: r["custo"] for r in cur.fetchall()}
    cur.execute(KM_PLACA_SQL, {"de": de_janela, "ate": ate})
    km: dict[str, float] = {}
    for r in cur.fetchall():
        km[r["placa"]] = km.get(r["placa"], 0.0) + r["km"]
    return {pl: (custo[pl] / km[pl]) for pl in custo if km.get(pl, 0.0) > 0}


def fetch_dre_oficial(comp_de: str, comp_ate: str) -> dict[str, float]:
    """Total por linha-folha do backbone, da DRE oficial (get_dre)."""
    dre = queries.get_dre(comp_de, comp_ate)
    por_rotulo = {l["rotulo"]: l["total"] for l in dre["linhas"]}
    return {rot: por_rotulo.get(rot, 0.0) for rot in _LEAF_OFICIAL}


def fetch_cv_detalhe(comp_de: str, comp_ate: str) -> list[dict[str, Any]]:
    """Detalhe por agrupador da linha CUSTO VARIAVEL (para separar manutencao/
    pneus e calcular a variacao de absorcao). get_dre e cacheado (reuso barato)."""
    dre = queries.get_dre(comp_de, comp_ate)
    for l in dre["linhas"]:
        if l["rotulo"] == "CUSTO VARIAVEL":
            return [{"agrupador": d["agrupador"], "total": d["total"]}
                    for d in l.get("detalhe", [])]
    return []


def janela_bounds(comp_ate: str, meses: int) -> tuple[str, str]:
    """[de, ate) para a janela rolling de N meses terminando em comp_ate."""
    _, ate = _comp_bounds(comp_ate, comp_ate)
    ano, mes = int(comp_ate[:4]), int(comp_ate[5:7])
    total = ano * 12 + (mes - 1) - (meses - 1)
    de = f"{total // 12}-{total % 12 + 1:02d}-01"
    return de, ate
