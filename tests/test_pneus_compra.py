# -*- coding: utf-8 -*-
"""Marcas, funil e compras de pneus (v0.202.0). A sabotagem central: a venda
de pneu com o veículo NÃO é fim de vida, e com ela no denominador o ranking
de marcas INVERTE (medido: STRADA 39.853 → 99.261 km)."""
from __future__ import annotations

from api.pneus import analise as an
from api.pneus.compras_erp import _serie_meses
from datetime import date


def _pneu(status="DISPOSAL", marca="STRADA", km_vidas=(50000, 49000),
          motivo="SEPARACAO DE LONAS", custo=1500.0, vida=2,
          sulco=None, recap=None, recap_max=None):
    return {"status": status, "marca": marca, "modelo": "X", "vida": vida,
            "sucata_motivo": motivo, "custo_compra": custo,
            "cpk": 0.02 if status == "INSTALLED" else None,
            "cpk_por_vida": [{"vida": i + 1, "km": k, "cpk": None}
                             for i, k in enumerate(km_vidas)],
            "sulco_menor": sulco, "recapagens": recap,
            "recapagens_max": recap_max}


def test_venda_com_veiculo_fica_fora_e_muda_o_veredito():
    """20 descartes reais de 99 mil km + 30 vendas de 20 mil: com a venda
    dentro, a mediana desaba — a exclusão é o que sustenta o ranking."""
    reais = [_pneu(km_vidas=(50000, 49261)) for _ in range(20)]
    vendas = [_pneu(km_vidas=(20000,), motivo="VENDA DE PNEU COM O VEICULO")
              for _ in range(30)]
    m = an.marcas(reais + vendas)
    assert m["excluidas_venda"] == 30
    assert m["descartes_uteis"] == 20
    assert m["itens"][0]["km_mediano"] == 99261.0


def test_marca_com_pouca_amostra_e_atenuada_ou_some():
    poucos = [_pneu(marca="RARA") for _ in range(an.MARCA_N_MIN - 1)]
    medios = [_pneu(marca="MEDIA") for _ in range(15)]
    m = an.marcas(poucos + medios)
    nomes = {x["marca"]: x for x in m["itens"]}
    assert "RARA" not in nomes                       # < 10: nem entra
    assert nomes["MEDIA"]["base_pequena"] is True    # 10-29: entra com badge


def test_funil_separa_recapagem_de_compra_nova():
    rodando = (
        [_pneu(status="INSTALLED", sulco=1.0, recap=1, recap_max=3)] +      # ilegal, recapável
        [_pneu(status="INSTALLED", sulco=4.0, recap=3, recap_max=3)] * 2 +  # 3-5 no limite → compra
        [_pneu(status="INSTALLED", sulco=4.0, recap=1, recap_max=3)] * 5 +  # 3-5 → recapagem
        [_pneu(status="INSTALLED", sulco=8.0, recap=3, recap_max=3)]        # bom, mas fim de vida
    )
    f = an.funil(rodando + [_pneu(status="INVENTORY")])
    assert f["ilegal"] == 1
    assert f["f3_5"] == 7 and f["f3_5_no_limite"] == 2
    assert f["compra_nova"] == 2                     # gastos NO limite
    assert f["recap_candidatos"] == 6                # gastos fora do limite
    assert f["fim_de_vida"] == 3                     # independe do sulco
    assert f["estoque"] == 1


def test_sucata_motivos_nunca_mistura_a_venda():
    ps = [_pneu(motivo="QUEBRA POR IMPACTO")] * 3 + \
         [_pneu(motivo="VENDA DE PNEU COM O VEICULO")] * 9
    ms = an.sucata_motivos(ps)
    assert ms == [{"motivo": "QUEBRA POR IMPACTO", "n": 3}]


def test_serie_de_meses_e_gerada_e_nao_colhida():
    """nov/25–jan/26 tiveram ZERO compra de pneu novo — o mês vazio é a
    informação, e o GROUP BY o engoliria."""
    eixo = _serie_meses(24, date(2026, 9, 1))
    assert len(eixo) == 24
    assert eixo[-1] == "2026-09" and eixo[0] == "2024-10"
    assert "2025-12" in eixo
