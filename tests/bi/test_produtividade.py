"""Painel de Produtividade de Veículos (Business Intelligence).

O que se protege aqui são as três decisões que vieram do DADO, não do desenho —
todas medidas contra o AVA antes de existir tela, e todas do mesmo gênero: um
número que parece desempenho e é ausência de registro.
"""
from __future__ import annotations

from api import queries as q


# ------------------------------------------------- vazio de terceiro é n/d

def test_vazio_de_terceiro_vira_nd_e_nao_zero():
    """O ERP não recebe o deslocamento vazio do terceiro: 0 km em 256 viagens.
    Zero ali, pintado como percentual, faria o terceiro parecer o MAIS
    eficiente da frota — é a mesma armadilha do "0% de retorno vazio em verde"
    da Análise de KM."""
    linha = q._prod_enrich({"modalidade": "TERCEIROS", "km_carregado": 143096.0,
                            "km_vazio": 0.0, "receita": 1268567.0})
    assert linha["retorno_vazio"] is None
    assert linha["vazio_nao_lancado"] is True


def test_zero_de_quem_LANCA_vazio_continua_sendo_zero():
    """A regra vale só para quem sabidamente não lança. Um agregado com zero
    vazio no período é zero de verdade, e esconder isso seria o erro oposto."""
    linha = q._prod_enrich({"modalidade": "AGREGADOS", "km_carregado": 48737.0,
                            "km_vazio": 0.0, "receita": 481223.0})
    assert linha["retorno_vazio"] == 0.0
    assert linha["vazio_nao_lancado"] is False


def test_retorno_vazio_normal():
    linha = q._prod_enrich({"modalidade": "FROTA", "km_carregado": 80.0,
                            "km_vazio": 20.0, "receita": 1000.0})
    assert linha["retorno_vazio"] == 0.2
    assert linha["km_total"] == 100.0


# ------------------------------------------------ produtividade por DIA ATIVO

def test_km_por_dia_usa_o_dia_com_viagem_nao_o_calendario():
    """10 mil km em 90 dias e 10 mil km em 12 dias são veículos diferentes. O
    denominador é o dia em que houve viagem: assim um veículo que passou dois
    meses na oficina não é comparado como se tivesse rodado o período todo."""
    a = q._prod_enrich({"modalidade": "FROTA", "km_carregado": 10000.0,
                        "km_vazio": 0.0, "receita": 1.0, "dias_ativos": 90})
    b = q._prod_enrich({"modalidade": "FROTA", "km_carregado": 10000.0,
                        "km_vazio": 0.0, "receita": 1.0, "dias_ativos": 12})
    assert round(a["km_por_dia_ativo"]) == 111
    assert round(b["km_por_dia_ativo"]) == 833


def test_sem_dia_ativo_nao_divide_por_zero():
    linha = q._prod_enrich({"modalidade": "FROTA", "km_carregado": 0.0,
                            "km_vazio": 0.0, "receita": 0.0, "dias_ativos": 0})
    assert linha["km_por_dia_ativo"] is None
    assert linha["rkm"] is None


# --------------------------------------------------- o recorte da frota base

def test_o_denominador_exclui_quem_nao_puxa_frete():
    """Medido no AVA: carreta, empilhadeira, gerador e AUTOMÓVEL têm zero
    viagem em 12 meses, contra 19/20 dos caminhões truck. Sem estas exclusões
    o painel acusaria 643 implementos "parados" e 12 carros da administração
    como frota ociosa."""
    for sql in (q.PROD_PARADOS_SQL, q.PROD_FROTA_SQL, q._PROD_BASE):
        alto = sql.upper()
        for tipo in ("CARRETA", "EMPILHADEIRA", "GERADOR", "AUTOM"):
            assert tipo in alto, f"{tipo} não está excluído em {sql[:40]!r}"


def test_ociosidade_so_conta_frota_propria_e_locada():
    """Agregado e terceiro parados não custam nada à Sulista. Contá-los seria o
    erro de denominador do painel de rastreadores, que acusava 664 sem sinal
    quando 341 eram veículos de terceiro."""
    assert "'FROTA','LOCACAO'" in q.PROD_PARADOS_SQL.replace(" ", "")
    assert "'FROTA','LOCACAO'" in q.PROD_FROTA_SQL.replace(" ", "")


def test_a_consulta_ignora_viagem_cancelada():
    """`dtcancelamento IS NULL` e `semaforo = 1` são a regra da casa para
    viagem válida; sem eles o km cresce com o que não aconteceu."""
    for sql in (q._PROD_BASE, q.PROD_PARADOS_SQL):
        assert "dtcancelamento IS NULL" in sql
        assert "semaforo = 1" in sql
