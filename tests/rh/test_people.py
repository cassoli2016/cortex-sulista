"""People Analytics: o que ele NAO pode fazer.

Medido em 25/08/2026: 196 ativos, 12 afastados, massa de R$ 682.175 em salario
base, idade mediana 39,6, tempo de casa mediano 2,7 anos, 24 pessoas com 60+
(12,2%), 37 de 59 cargos com ocupante unico.
"""
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
FONTE = RAIZ / "api" / "people.py"
HTML = RAIZ / "api" / "static" / "index.html"


@pytest.fixture(scope="module")
def fonte() -> str:
    return FONTE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return HTML.read_text(encoding="utf-8")


def test_ativo_e_a_mesma_definicao_do_headcount(fonte):
    """A tela de CNH ja contou motorista demitido como ativo. Duas telas de RH
    com nocoes diferentes de quem trabalha aqui e defeito por construcao."""
    assert "_ATIVO = \"vf.codigoempresa = :emp AND vf.situacaofunc = 'A'\"" in fonte


def test_afastado_nao_entra_no_quadro_ativo(fonte):
    """Somar inflaria a capacidade; ignorar esconderia o custo e a reposicao.
    Fica ao lado, sempre."""
    assert "situacaofunc = 'F'" in fonte
    assert '"afastados"' in fonte and '"afastados_massa"' in fonte


def test_falecimento_nao_e_ficha_esquecida(fonte):
    """Ha afastamentos abertos de gente ja desligada e a maioria e obito: o
    registro esta certo, morte nao tem data de retorno. Trata-los como erro de
    cadastro seria acusar o ERP de algo que ele nao fez — engano que so se
    evita lendo a tabela de dominio antes de concluir."""
    assert "COND_FALECIMENTO = 12" in fonte
    i = fonte.index("COND_FALECIMENTO = 12")
    assert "FALECIMENTO" in fonte[:i], "o motivo tem de estar explicado no topo"
    # obito NAO conta como afastamento longo a conferir
    assert 'r["cond"] != COND_FALECIMENTO' in fonte


def test_afastamento_longo_e_marca_e_nao_acusacao(fonte):
    """Auxilio-doenca de anos existe. O corte serve para pedir conferencia, nao
    para afirmar erro."""
    m = re.search(r"AFASTAMENTO_LONGO_DIAS = (\d+)", fonte)
    assert m and int(m.group(1)) >= 365 * 3


def test_a_saida_por_tempo_de_casa_ficou_de_fora_com_a_razao_escrita(fonte):
    """DATATERMINOCONTRATO devolveu 18 saidas TODAS na mesma faixa e zero nas
    outras. Distribuicao assim nao existe: publicar seria inventar achado."""
    assert "NAO ENTRA NESTA TELA" in fonte
    assert '"saidas"' not in fonte


def test_nao_repete_o_que_o_headcount_ja_da(fonte):
    """Turnover, admissoes e demissoes sao do Headcount. Repetir criaria dois
    numeros para a mesma pergunta."""
    for proibido in ('"turnover', '"admissoes', '"demissoes'):
        assert proibido not in fonte


def test_dispersao_salarial_so_faz_sentido_com_mais_de_um_ocupante(html):
    """Amplitude de um cargo com uma pessoa e sempre 1,00 — linha inutil que
    empurraria as comparaveis para baixo."""
    assert "(d.cargos||[]).filter(c=>c.n>1)" in html


def test_percentual_sai_em_portugues(html):
    """A tela ja imprimiu "9.2%" com ponto no meio de um app todo em pt-BR."""
    assert "function pplPct(" in html
    assert "(k.pct_sessenta||0)+'%'" not in html


def test_nao_expoe_cpf_nem_dado_bancario(fonte):
    """A excecao de PII e o NOME na lista de afastados, onde o RH precisa agir.
    CPF, PIS, CTPS e dado bancario continuam fora.

    A verificacao olha o SQL, nao o texto do arquivo: a primeira versao
    procurava "conta" no fonte inteiro e casava com "contando", "contadas" e
    "conta de quando retorna" — teste que le prosa acusa a propria
    documentacao."""
    sql = " ".join(re.findall(r'_q\(\s*f?"""(.*?)"""', fonte, re.S)).lower()
    assert sql, "nenhum SQL encontrado — o teste deixaria de valer em silencio"
    for proibido in ("cpf", "pisnumero", "ctps", "nrconta", "banco",
                     "agencia", "chavepix"):
        assert proibido not in sql, f"{proibido!r} nao pode sair da folha"


def test_a_tela_esta_registrada_em_todos_os_lugares(html):
    assert 'id="view-people"' in html
    assert 'data-view="people"' in html
    assert 'href="#people" onclick="fecharDrawer()"' in html
    assert "people:'People Analytics'" in html
    assert "people:'Rh'" in html
    assert "people:loadPeople" in html


def test_a_rota_esta_no_rbac():
    auth = (RAIZ / "api" / "auth.py").read_text(encoding="utf-8")
    assert '"people":  ("People Analytics", "Recursos Humanos"),' in auth
    assert '("/api/rh/people",                frozenset({"people"})),' in auth
    assert "perfis_modelo_v30" in auth
