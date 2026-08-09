"""A documentacao e EXTRAIDA do index.html, entao os testes cobram fidelidade:
se uma tela sumir do painel, tem de sumir da documentacao sozinha.
"""
from __future__ import annotations

from api import documentacao


def test_extrai_as_telas_do_painel():
    telas = documentacao.extrair_telas()
    assert len(telas) >= 40, f"so {len(telas)} telas extraidas"
    assert "dre" in telas and "home" in telas


def test_toda_tela_extraida_tem_titulo():
    for view, t in documentacao.extrair_telas().items():
        assert t["titulo"], view


def test_nao_perde_a_tela_inicial_que_tem_classe_extra():
    """view-fluxo e class="view on" (e a tela que abre). Uma regex presa a
    class="view" exato perdia o Fluxo de Caixa e colava os cards dele na tela
    anterior."""
    telas = documentacao.extrair_telas()
    assert "fluxo" in telas
    assert telas["fluxo"]["titulo"] == "Fluxo de Caixa e Bancos"
    assert telas["fluxo"]["cards"], "fluxo extraido sem nenhum card"


def test_cobre_todas_as_telas_do_menu():
    """Toda view registrada em VIEWS tem de estar documentada."""
    from api.documentacao import _titulos_views
    telas = documentacao.extrair_telas()
    faltando = set(_titulos_views()) - set(telas)
    assert not faltando, f"telas do menu sem documentacao: {sorted(faltando)}"


def test_ignora_tela_dormente():
    """view-rent existe no HTML mas nao esta em VIEWS: o router nao abre e o
    menu nao mostra. Documentar seria descrever algo inalcancavel."""
    assert "rent" not in documentacao.extrair_telas()


def test_captura_a_procedencia_dos_cards():
    """O ihelp do card de faturamento cita as tres fontes oficiais."""
    home = documentacao.extrair_telas()["home"]
    fontes = " ".join(c["fonte"] or "" for c in home["cards"])
    assert "CT-e" in fontes
    assert "KMM" in fontes.upper()


def test_cards_sem_ihelp_ficam_com_fonte_nula_e_nao_quebram():
    for t in documentacao.extrair_telas().values():
        for c in t["cards"]:
            assert c["titulo"]
            assert c["fonte"] is None or isinstance(c["fonte"], str)


def test_montar_traz_versoes_e_glossario():
    d = documentacao.montar()
    assert d["versoes"][0]["versao"] == documentacao.versoes()[0]["versao"]
    assert any("RKM" in g["termo"] for g in d["glossario"])
    assert d["rotulo"].startswith("CX-")


def test_toda_tela_do_painel_esta_em_algum_grupo():
    """E o que impede a documentacao de esquecer tela nova."""
    d = documentacao.montar()
    agrupadas = {v for g in d["grupos"] for v in g["telas"]}
    faltando = set(d["telas"]) - agrupadas
    assert not faltando, f"telas fora de grupo: {sorted(faltando)}"
