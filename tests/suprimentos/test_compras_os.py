# -*- coding: utf-8 -*-
"""Compras da OS — as duas exclusões que fazem a lista significar algo.

O valor destes testes não é a aritmética do percentil: é prender as decisões
que separam sinal de ruído, e que a próxima pessoa desfaria sem perceber.

- Um par da MESMA ordem de serviço não é recompra: é o mesmo reparo lançado em
  duas solicitações. Medido: 64 dos 355 pares, quase todos com UM dia de
  intervalo. Um piso de dias não separava isso (a distribuição por dias é lisa,
  sem degrau) — a OS separa.
- Consumível se recompra por natureza; o filtro é heurística DECLARADA, e a
  tela mostra os dois números.
- O prazo de uma OS é o da PRIMEIRA compra dela: contar todas puxa a mediana
  para cima por causa de complemento legítimo.
- Lançamento retroativo (compra datada antes da OS) não é prazo negativo, sai.
"""
from __future__ import annotations

from api import manutencao_compras as mc


def _item(produto="P1", veiculo="ABC1D23", data="2026-03-10", os_num=100,
          os_data="2026-03-08", tipooperacao=103, valor=100.0, filial=1,
          descricao="LONA DE FREIO", solicitacao=1):
    return {"filial": filial, "solicitacao": solicitacao, "data": data,
            "os": os_num, "os_data": os_data, "tipomanutencao": 2,
            "veiculo": veiculo, "tipooperacao": tipooperacao,
            "produto": produto, "descricao": descricao, "valor": valor}


# ---------------------------------------------------------------- percentil

def test_percentil_por_posicao():
    v = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert mc.percentil(v, 0.5) == 5
    assert mc.percentil(v, 0.9) == 9
    assert mc.percentil([], 0.5) == 0.0
    assert mc.percentil([7], 0.9) == 7


# ---------------------------------------------------------------- classes

def test_codigo_sem_domenio_conhecido_vira_outros():
    """Não se inventa rótulo para código que a casa não decodificou."""
    assert mc.classe_do_item(103) == "pecas"
    assert mc.classe_do_item(121) == "servicos"
    assert mc.classe_do_item(205) == "pneus"
    assert mc.classe_do_item(999) == "outros"
    assert mc.classe_do_item(None) == "outros"


# ---------------------------------------------------------------- prazo da OS

def test_prazo_da_os_usa_a_primeira_compra():
    """Uma OS com compra no dia 2 e complemento no dia 40 tem prazo 2, não 40
    nem a média dos dois."""
    itens = [_item(os_num=1, os_data="2026-03-01", data="2026-03-03"),
             _item(os_num=1, os_data="2026-03-01", data="2026-04-10", produto="P2")]
    linhas = mc.dias_ate_a_compra(itens)
    assert len(linhas) == 1
    assert linhas[0]["dias"] == 2


def test_lancamento_retroativo_nao_vira_prazo_negativo():
    itens = [_item(os_num=1, os_data="2026-03-10", data="2026-03-01"),   # antes da OS
             _item(os_num=2, os_data="2020-01-01", data="2026-03-01"),   # > 400 dias
             _item(os_num=3, os_data="2026-03-01", data="2026-03-05")]
    linhas = mc.dias_ate_a_compra(itens)
    assert [x["os"] for x in linhas] == [3]


def test_item_sem_os_fica_fora_do_prazo_mas_conta_no_gasto():
    """Compra sem vínculo de OS não tem prazo a medir; ainda assim é gasto da
    oficina e não pode sumir do total."""
    itens = [_item(os_num=None, os_data=None, valor=500.0),
             _item(os_num=7, os_data="2026-03-01", data="2026-03-04", valor=100.0)]
    linhas = mc.dias_ate_a_compra(itens)
    assert [x["os"] for x in linhas] == [7]
    r = mc.resumo(itens, linhas, [])
    assert r["itens"] == 2 and r["valor"] == 600.0
    assert r["cobertura_os"] == 1        # a tela mostra 1 de 2


def test_demoradas_conta_acima_do_corte():
    itens = [_item(os_num=i, os_data="2026-03-01",
                   data=f"2026-03-{d:02d}") for i, d in enumerate((2, 5, 20, 28), start=1)]
    r = mc._resumo_dias(mc.dias_ate_a_compra(itens))
    assert r["os"] == 4
    assert r["demoradas"] == 2           # 19 e 27 dias passam de 15


# ---------------------------------------------------------------- recompra

def test_par_da_mesma_os_nao_e_recompra():
    """A exclusão que mais muda a lista: mesmo reparo em duas solicitações."""
    mesma = [_item(os_num=50, data="2026-03-10", solicitacao=1),
             _item(os_num=50, data="2026-03-11", solicitacao=2)]
    assert mc.recompras(mesma) == []

    outra = [_item(os_num=50, data="2026-03-10", solicitacao=1),
             _item(os_num=51, data="2026-03-11", solicitacao=2)]
    r = mc.recompras(outra)
    assert len(r) == 1 and r[0]["dias"] == 1
    assert r[0]["os_anterior"] == 50 and r[0]["os"] == 51


def test_recompra_fora_da_janela_nao_conta():
    itens = [_item(os_num=1, data="2026-01-01"), _item(os_num=2, data="2026-04-01")]
    assert mc.recompras(itens) == []
    assert len(mc.recompras(itens, dias=120)) == 1


def test_so_peca_entra_na_recompra():
    """Serviço e pneu se repetem por natureza; não são falha prematura."""
    servico = [_item(os_num=1, data="2026-03-01", tipooperacao=121),
               _item(os_num=2, data="2026-03-10", tipooperacao=121)]
    assert mc.recompras(servico) == []


def test_consumivel_e_marcado_e_nao_soma_no_kpi():
    """A heurística não ESCONDE o consumível — marca. O KPI usa a lista sem
    consumível; o número com ele fica ao lado, para a oficina calibrar."""
    peca = [_item(produto="A", os_num=1, data="2026-03-01", descricao="LONA DE FREIO"),
            _item(produto="A", os_num=2, data="2026-03-10", descricao="LONA DE FREIO")]
    cons = [_item(produto="B", os_num=3, data="2026-03-01", descricao="PARAFUSO GENERICO"),
            _item(produto="B", os_num=4, data="2026-03-10", descricao="PARAFUSO GENERICO")]
    r = mc.recompras(peca + cons)
    assert len(r) == 2
    assert {x["consumivel"] for x in r} == {True, False}

    k = mc.resumo(peca + cons, [], r)
    assert k["recompras"] == 1                     # só a peça
    assert k["recompras_com_consumivel"] == 2      # o total continua visível


def test_consumivel_reconhece_acento_e_caixa():
    assert mc.e_consumivel("ÓLEO MOTOR 15W40")
    assert mc.e_consumivel("parafuso sextavado")
    assert mc.e_consumivel("ABRAÇADEIRA 50MM")
    assert not mc.e_consumivel("LONA DE FREIO CA 33")
    assert not mc.e_consumivel("")


def test_recompra_pede_veiculo_e_valor():
    """Sem placa não há 'mesmo veículo' a afirmar; valor zero é lançamento
    incompleto, não compra."""
    sem_placa = [_item(veiculo=None, os_num=1, data="2026-03-01"),
                 _item(veiculo=None, os_num=2, data="2026-03-10")]
    assert mc.recompras(sem_placa) == []
    sem_valor = [_item(os_num=1, data="2026-03-01", valor=0.0),
                 _item(os_num=2, data="2026-03-10", valor=0.0)]
    assert mc.recompras(sem_valor) == []


# ---------------------------------------------------------------- mix

def test_mix_mensal_separa_classes_e_conta_solicitacoes():
    itens = [_item(data="2026-03-05", tipooperacao=103, valor=100.0, solicitacao=1),
             _item(data="2026-03-06", tipooperacao=121, valor=50.0, solicitacao=1),
             _item(data="2026-03-07", tipooperacao=999, valor=7.0, solicitacao=2),
             _item(data="2026-04-01", tipooperacao=103, valor=10.0, solicitacao=3)]
    mix = mc.mix_mensal(itens)
    assert [m["mes"] for m in mix] == ["2026-03", "2026-04"]
    mar = mix[0]
    assert mar["pecas"] == 100.0 and mar["servicos"] == 50.0 and mar["outros"] == 7.0
    assert mar["valor"] == 157.0 and mar["itens"] == 3
    assert mar["solicitacoes"] == 2        # duas solicitações distintas, três itens
