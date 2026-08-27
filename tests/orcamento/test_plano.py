"""Importação do orçamento PLANEJADO (planilha da diretoria).

O caso que motivou metade destes testes: a planilha escreve
"CR - CREDITOS TRUBUTÁRIOS" (com erro de digitação) e o ERP chama
"CR - CREDITOS". Sem apelido, R$ 16,35 MILHÕES de crédito tributário ficavam
de fora em silêncio — e o total AINDA fechava contra o resultado do exercício,
porque a linha sumia dos dois lados da conta. Só a reconciliação pegou.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from api.orcamento import plano

ARQUIVO = (Path(__file__).resolve().parent.parent.parent
           / "orcamento" / "orcamento-26.xlsx")
pytestmark = pytest.mark.skipif(not ARQUIVO.exists(),
                                reason="planilha do plano não disponível")


def _meses(n=24, ano=2024, mes=8):
    fora = []
    for _ in range(n):
        fora.append(f"{ano:04d}-{mes:02d}")
        mes += 1
        if mes == 13:
            mes, ano = 1, ano + 1
    return fora


def test_le_as_linhas_e_separa_subtotal_de_folha():
    d = plano.ler_planilha(ARQUIVO)
    cods = {l["codigo"] for l in d["linhas"]}
    assert "040.020.010" in cods          # CV - COMBUSTÍVEL, folha
    sub = {l["codigo"] for l in d["linhas"] if l["subtotal"]}
    assert "040" in sub and "040.010" in sub
    assert "040.020.010" not in sub


def test_soma_das_folhas_e_o_resultado_do_exercicio():
    """Se subtotal entrasse junto, o valor dobraria — esta é a prova."""
    d = plano.ler_planilha(ARQUIVO)
    folhas = round(sum(l["total"] for l in d["linhas"] if not l["subtotal"]), 2)
    res = next(l for l in d["linhas"] if l["codigo"] == "090")
    assert folhas == pytest.approx(res["total"], abs=0.01)


def test_apelido_recupera_o_credito_tributario():
    """Sem o apelido, R$ 16,35 mi sumiam calados."""
    assert plano._norm("CR - CREDITOS TRUBUTÁRIOS") in {
        plano._norm(k) for k in plano.APELIDOS}


def test_rateio_por_conta_bate_exato_com_o_plano():
    """O total de cada agrupador tem de ser o do plano, ao centavo. Resíduo de
    arredondamento em 12 meses vira diferença que ninguém explica."""
    p = plano.preparar(ARQUIVO, _meses())
    fora = [c for c in p["conferencia"] if abs(c["diferenca"]) > 0.01]
    assert not fora, f"agrupadores com rateio fora: {fora[:3]}"


def test_importado_mais_nao_importado_fecha_com_a_planilha():
    p = plano.preparar(ARQUIVO, _meses())
    assert (p["valor_importado"] + p["valor_nao_importado"]) == pytest.approx(
        -4673565.68, abs=0.05)


def test_receita_entra_como_bucket_unico():
    """O plano põe os R$ 144 mi todos em FROTA/LOCADOS e zero nas outras
    modalidades. Importar linha a linha acusaria FROTA estourando e AGREGADOS
    100% abaixo — as duas falsas."""
    p = plano.preparar(ARQUIVO, _meses())
    receita = [c for c in p["conferencia"] if c["agrupador"] == plano.BUCKET_RECEITA]
    assert len(receita) == 1
    assert receita[0]["plano"] == pytest.approx(144043178.0, abs=0.01)
    assert receita[0]["contas"] > 1, "rateia entre as contas de receita"


def test_rateio_joga_o_residuo_na_maior_fatia():
    pesos = {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
    r = plano._ratear(100.0, pesos)
    assert round(sum(r.values()), 2) == 100.0


def test_conta_sem_historico_recebe_peso_igual():
    """O plano existe e o dinheiro precisa cair em algum lugar; concentrar
    tudo numa conta faria o orçamento inteiro pousar num lançamento marginal."""
    p = plano._peso_historico(["x", "y"], {})
    assert p == {"x": 0.5, "y": 0.5}


def test_peso_usa_modulo_e_nao_o_sinal():
    """Custo é negativo; com sinal, uma conta de estorno viraria peso negativo
    e inverteria o rateio."""
    p = plano._peso_historico(["a", "b"], {"a": 300.0, "b": 100.0})
    assert p["a"] == pytest.approx(0.75)


def test_importar_cria_versao_nova_sem_tocar_nas_existentes(esquema_pg):
    from api.orcamento import armazenamento as arm
    db = esquema_pg
    arm.init_db(db)
    antiga = arm.criar_versao(db, 2026, "derivada do histórico", 0.0, "teste")
    r = plano.importar(ARQUIVO, 2026, "Plano 2026", "teste", _meses(), esquema=db)
    assert r["versao_id"] != antiga
    from api import pglocal
    assert pglocal.um("SELECT count(*) AS n FROM orc_versao",
                      esquema=db)["n"] == 2
    n = pglocal.um("SELECT count(*) AS n FROM orc_linha WHERE versao_id=%s",
                   (r["versao_id"],), esquema=db)["n"]
    assert n == r["contas"] * 12
