"""A tela existe, está no menu, no mobile e nos mapas de carga."""
from __future__ import annotations

from pathlib import Path

HTML = Path(__file__).resolve().parent.parent.parent / "api" / "static" / "index.html"
S = HTML.read_text(encoding="utf-8")


def test_menu_tem_o_grupo_antt():
    assert 'id="grpAntt"' in S
    assert 'data-view="anpiso"' in S


def test_view_registrada_nos_mapas_de_carga():
    assert "anpiso:loadAnpiso" in S
    assert "anpiso:DATAANPISO" in S


def test_tela_entra_na_gaveta_mobile():
    drawer = S.split('<div class="drawer"', 1)[1]
    assert 'href="#anpiso"' in drawer


def test_filtros_da_tela_estao_no_qsview():
    bloco = S.split("function qsView(k){", 1)[1].split("\n}", 1)[0]
    assert "k==='anpiso'" in bloco
    assert "modalidade" in bloco


def test_secao_da_view_existe_com_os_alvos_do_render():
    assert 'id="view-anpiso"' in S
    for alvo in ('id="kpis-anpiso"', 'id="chartAnpiso"', 'id="anpiso-transp"',
                 'id="anpiso-pend"'):
        assert alvo in S, alvo


def test_grupo_de_filtros_proprio_existe_e_e_alternado():
    assert 'id="grpAnp"' in S
    assert "document.getElementById('grpAnp').style.display" in S


def test_tela_declara_a_fonte_do_dado_como_as_vizinhas():
    """Padrão da casa: todo card tem ihelp dizendo de onde vem o número."""
    view = S.split('id="view-anpiso"', 1)[1].split("</section>", 1)[0]
    assert view.count('class="ihelp"') >= 3
    assert "programacaoembarque" in view
    assert "vigente NA DATA DA VIAGEM" in view


def test_estados_de_nao_calculo_tem_rotulo_humano():
    """O usuário nunca vê o nome interno do estado."""
    for estado in ("sem_eixos", "sem_carga", "sem_km", "sem_tabela", "isento"):
        assert f"{estado}:" in S.split("const ANPISO_SIT", 1)[1][:800]


def test_view_esta_no_dicionario_do_roteador():
    """Sem entrada em VIEWS, currentView() cai em 'home' e a tela nunca abre —
    o menu leva para a Visão Geral sem erro nenhum. Foi o que aconteceu na
    primeira versão desta tela, e só o teste de browser pegou."""
    bloco = S.split("const VIEWS = {", 1)[1].split("};", 1)[0]
    assert "anpiso:" in bloco
