# -*- coding: utf-8 -*-
"""A meta diária sazonal (01/09/2026): o TOTAL do mês é intocável, a
distribuição segue o realizado histórico, e o ERP continua decidindo QUAIS
dias têm meta (domingo e feriado ficam de fora porque ele os zera).

Os casos de sabotagem existem pela regra da casa: um verde que não ficaria
vermelho não conferiu nada.
"""
from __future__ import annotations

from api.queries import _meta_diaria_sazonal

# setembro/2026: dia 1 é terça; 5 sáb, 6 dom, 7 seg (feriado sem meta no ERP)
ANO, MES = 2026, 9


def _diario(metas: dict[int, float]) -> list[dict]:
    return [{"dia": d, "realizado": 0.0, "meta": m} for d, m in sorted(metas.items())]


def _celulas(por_dow: dict[int, float], dias: int = 10) -> list[dict]:
    """Histórico sintético: mesmo peso do dow nas três décadas."""
    out = []
    for dow, media in por_dow.items():
        for dec in (0, 1, 2):
            out.append({"dow": dow, "dec": dec, "total": media * dias, "dias": dias})
    return out


def test_o_total_do_mes_nao_muda_um_centavo():
    metas = {d: 100.0 for d in (1, 2, 3, 4, 8, 9, 10, 11)}
    cel = _celulas({2: 500.0, 3: 700.0, 4: 400.0, 5: 300.0, 1: 450.0})
    diario, fonte = _meta_diaria_sazonal(_diario(metas), cel, ANO, MES)
    assert fonte == "sazonal"
    assert round(sum(r["meta"] for r in diario), 2) == 800.00


def test_o_dia_forte_do_historico_ganha_mais_meta():
    """Sabotagem dirigida: só a QUARTA é forte no histórico — a meta dela tem
    de sair maior que a das vizinhas, senão a sazonalidade não está ligada."""
    metas = {1: 100.0, 2: 100.0, 3: 100.0}          # ter, qua, qui iguais no ERP
    cel = _celulas({2: 100.0, 3: 900.0, 4: 100.0})   # quarta (dow 3) 9x
    diario, fonte = _meta_diaria_sazonal(_diario(metas), cel, ANO, MES)
    assert fonte == "sazonal"
    por_dia = {r["dia"]: r["meta"] for r in diario}
    assert por_dia[2] > por_dia[1] * 3
    assert por_dia[2] > por_dia[3] * 3


def test_dia_sem_meta_do_erp_continua_sem_meta():
    """O ERP zera domingo E feriado (7 de setembro não tem linha), e essa
    escolha é informação: redistribuir para lá cobraria meta de quem não
    trabalha."""
    metas = {4: 100.0, 8: 100.0}                     # sex e ter; 5-7 sem meta
    diario = _diario(metas) + [{"dia": 6, "realizado": 50.0, "meta": 0.0}]
    cel = _celulas({0: 400.0, 2: 400.0, 5: 400.0, 6: 400.0})
    out, fonte = _meta_diaria_sazonal(diario, cel, ANO, MES)
    assert fonte == "sazonal"
    assert next(r for r in out if r["dia"] == 6)["meta"] == 0.0
    assert round(sum(r["meta"] for r in out), 2) == 200.00


def test_sem_historico_a_meta_do_erp_fica_como_esta():
    metas = {1: 111.0, 2: 222.0}
    out, fonte = _meta_diaria_sazonal(_diario(metas), [], ANO, MES)
    assert fonte == "erp"
    assert {r["dia"]: r["meta"] for r in out} == metas


def test_celula_rala_cai_na_media_do_dia_da_semana():
    """Célula com menos de 4 dias de amostra é ruído — o peso vem da média
    marginal do dow, e o resultado tem de continuar somando o total."""
    metas = {1: 100.0, 8: 100.0, 15: 100.0}          # três terças (dow 2), uma por década
    cel = [
        {"dow": 2, "dec": 0, "total": 500.0 * 8, "dias": 8},
        {"dow": 2, "dec": 1, "total": 9999.0 * 2, "dias": 2},   # rala: ignorada
        {"dow": 2, "dec": 2, "total": 500.0 * 8, "dias": 8},
    ]
    out, fonte = _meta_diaria_sazonal(_diario(metas), cel, ANO, MES)
    assert fonte == "sazonal"
    por_dia = {r["dia"]: r["meta"] for r in out}
    # a terça da década do meio NÃO herda o 9999 da célula rala
    assert abs(por_dia[8] - por_dia[1]) < 0.01
    assert round(sum(por_dia.values()), 2) == 300.00


def test_residuo_de_arredondamento_vai_para_o_dia_de_maior_peso():
    metas = {1: 100.0, 2: 100.0, 3: 100.0}
    cel = _celulas({2: 333.0, 3: 333.0, 4: 334.0})
    out, _ = _meta_diaria_sazonal(_diario(metas), cel, ANO, MES)
    assert round(sum(r["meta"] for r in out), 2) == 300.00


def test_a_sql_do_mes_anterior_tem_limite_superior_em_toda_fonte():
    """VG_DIARIO_ANT_SQL é derivada da VG_DIARIO_SQL por substituição. As
    fontes de realizado só tinham limite inferior (no mês corrente não há
    emissão futura); deslocadas um mês SEM o teto, trariam o mês corrente
    junto — e o fechamento de agosto somaria setembro em silêncio."""
    from api.queries import VG_DIARIO_ANT_SQL as ant, VG_DIARIO_SQL as cur
    assert ant != cur
    assert ant.count("- interval '1 month'") == 4        # 3 realizado + 1 meta
    assert ant.count("dtemissao < date_trunc('month', current_date)") == 3
    assert "dt < date_trunc('month', current_date)" in ant
    assert "dt < date_trunc('month', current_date) + interval" not in ant
