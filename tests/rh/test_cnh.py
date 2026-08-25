"""A tela de CNH mede COBERTURA antes de medir vencimento.

Contexto medido em 25/08/2026: dos 294 motoristas ativos, 81 (27,6%) têm a data
de vencimento da CNH cadastrada no GLOBUS. Nenhuma vencida e 2 vencendo em 90
dias. Um painel que abrisse com "0 vencidas" em verde afirmaria "frota em dia"
sobre uma base que enxerga 28% da operação — é a mesma armadilha das Multas e
do CRM, e estes testes são o que impede ela de voltar.
"""
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
FOLHA = RAIZ / "api" / "queries_folha.py"
HTML = RAIZ / "api" / "static" / "index.html"


@pytest.fixture(scope="module")
def fonte() -> str:
    return FOLHA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return HTML.read_text(encoding="utf-8")


# --------------------------------------------------------------------- regra
def test_o_filtro_de_funcao_nao_e_o_ingenuo(fonte):
    """O ERP trunca `descfuncao` em ~16 caracteres: o motorista principal fica
    'MOT CARRETEIRO' e NÃO casa com '%MOTORISTA%'. Com o filtro ingênuo a tela
    mediria 21 pessoas em vez de 294 — e diria que a frota tem 21 motoristas."""
    assert "LIKE 'MOT%'" in fonte
    m = re.search(r"_CNH_FUNCAO = (.*)", fonte)
    assert m and "%MOTORISTA%" not in m.group(1), (
        "filtro por '%MOTORISTA%' perde 'MOT CARRETEIRO', que é a maior "
        "população de motoristas")


def test_quem_esta_fora_de_area_de_motorista_e_contado_a_parte(fonte):
    """94 pessoas têm função de motorista lotadas em Presidência, RH e
    Contabilidade, e 92 delas não têm CNH nenhuma. Isso cheira a função errada
    no cadastro — mas quem decide o que essas pessoas são é o RH, não a tela.
    Ficam SEPARADAS, nunca excluídas em silêncio."""
    assert "_CNH_DIRIGE" in fonte
    assert '"fora_de_area"' in fonte and '"dirigindo"' in fonte


def test_a_cobertura_e_um_indicador_de_primeira_classe(fonte):
    assert '"cobertura"' in fonte and '"sem_cnh"' in fonte


def test_a_lista_de_quem_nao_tem_cadastro_e_devolvida(fonte):
    """Sem ela o RH não tem o que fazer com o número: 213 é diagnóstico, a
    lista é o trabalho."""
    assert '"sem_cnh": sem' in fonte


# ----------------------------------------------------------------------- PII
def test_nao_devolve_cpf_nem_o_numero_da_cnh(fonte):
    """Exceção de PII é NOME e CHAPA, porque sem eles ninguém cobra renovação
    de ninguém. O resto continua fora — inclusive o número da CNH, que não é
    preciso para agendar renovação alguma."""
    i = fonte.index("def get_cnh(")
    corpo = fonte[i:]
    for proibido in ("cpfcnpj", "codigo_cnh", "registro_cnh", "salbase", "pis_inss"):
        assert proibido not in corpo.lower(), (
            f"'{proibido}' não pode sair da folha nesta tela")


def test_a_excecao_de_pii_esta_escrita_no_topo_do_modulo(fonte):
    """O módulo declara que só entrega agregados. Abrir exceção sem registrar
    onde a regra está escrita é como não ter regra."""
    cabeca = fonte[:fonte.index("from __future__")] + fonte[:2000]
    assert "EXCEÇÃO" in cabeca and "get_cnh()" in cabeca


# ---------------------------------------------------------------------- tela
def test_zero_vencidas_nao_sai_em_verde(html):
    """O cartão de vencidas só ganha cor quando há vencida (e aí, vermelha).
    Verde diria 'está tudo certo' sobre 28% da base."""
    i = html.index("kpi('CNH vencida'")
    bloco = html[i:i + 420]
    assert "(k.vencidas||0)>0?'neg':''" in bloco, (
        "o cartão não pode receber classe 'pos'")
    assert "entre as " in bloco, "tem de dizer sobre que base fala"


def test_o_cartao_de_cadastro_mostra_o_que_falta(html):
    i = html.index("kpi('CNH cadastrada'")
    assert "sem a data" in html[i:i + 400]


def test_a_tela_esta_registrada_em_todos_os_lugares(html):
    """Tela nova precisa de: seção, link na barra, item na gaveta do celular,
    entrada em VIEWS, em VIEW_GROUP e no LOADMAP. Faltando a gaveta, ela
    simplesmente não existe no celular — já aconteceu com o Milk Run."""
    assert 'id="view-cnh"' in html
    assert 'data-view="cnh"' in html
    assert 'href="#cnh" onclick="fecharDrawer()"' in html
    assert "cnh:'CNH dos Motoristas'" in html
    assert "cnh:'Rh'" in html
    assert "cnh:loadCnh" in html


def test_a_rota_esta_no_rbac():
    auth = (RAIZ / "api" / "auth.py").read_text(encoding="utf-8")
    assert '"cnh":     ("CNH dos Motoristas", "Recursos Humanos"),' in auth
    assert '("/api/rh/cnh",                   frozenset({"cnh"})),' in auth
    assert "perfis_modelo_v27" in auth, (
        "sem bloco de seed novo a tela nunca chega aos perfis existentes — o "
        "seed geral está travado desde julho")
