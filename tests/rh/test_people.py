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


# ------------------------------------------------------ filtro de liderança
#
# Liderança = coordenador, supervisor, gerente e diretor, como o negócio
# definiu. Medido em 29/08/2026: 16 pessoas em 10 cargos — 8,4% do quadro e
# 20,1% da massa salarial, com 10,9 liderados por chefia. Salário mediano de
# R$ 7.038 contra R$ 2.933 do restante. DIRETOR: nenhum ativo (os três da base
# são de 2006/2010 e estão desligados).

def test_lideranca_le_o_campo_completo_e_nao_o_truncado(fonte):
    """`descfuncao` é VARCHAR2(16) e chega truncado: 'COOR DE FATURAM',
    'GER DE PROJETOS', 'COORDENADOR DE M'. Filtrar por ele perderia chefia de
    verdade — o mesmo defeito que a tela de CNH já teve com 'MOT CARRETEIRO'."""
    assert "descfuncaocompleta" in fonte
    assert '_CAMPO_CARGO = _CARGO' in fonte
    m = re.search(r"^LIDERANCA = .*?\n\n", fonte, re.S | re.M)
    assert m, "LIDERANCA não encontrado"
    assert "descfuncao)" not in m.group(0), (
        "o predicado de liderança está lendo o campo truncado de 16 caracteres")


def test_lideranca_casa_no_inicio_de_palavra(fonte):
    """`LIKE '%GER%'` classificaria AJUDANTE GERAL, AUXILIAR SERVICOS GERAIS e
    SERVENTE LIMPEZA E SERVIÇOS GERAIS como gerência — três pessoas do chão de
    fábrica viradas em chefia, inflando a massa salarial de liderança."""
    # o predicado REAL, e não o comentário que explica por que %GER% é errado
    import api.people as ppl
    assert "'%GER%'" not in ppl.LIDERANCA, (
        "o predicado montado casaria GERAL e GERAIS no meio da palavra")
    # cada prefixo é ancorado no início do texto ou depois de um espaço
    assert "LIKE '{p}%'" in fonte and "LIKE '% {p}%'" in fonte
    assert "LIKE 'GERENTE%'" in ppl.LIDERANCA
    assert "LIKE '% GERENTE%'" in ppl.LIDERANCA


def test_lideranca_reconhece_a_abreviacao_do_cadastro(fonte):
    """Existe 'COORD DE SUPORTE E IMPLANTAÇÃO' escrito assim no campo COMPLETO
    — a abreviação está no cadastro, não no truncamento. `COORDENADOR%` sozinho
    deixaria essa pessoa de fora do filtro."""
    assert '"COOR"' in fonte, "prefixo curto de coordenador ausente"
    assert '"SUPERV"' in fonte
    assert '"GERENTE"' in fonte and '"DIRETOR"' in fonte


def test_diretor_continua_no_predicado_mesmo_sem_ocupante(fonte):
    """Hoje não há diretor ativo. Tirar o nível do predicado faria o primeiro
    diretor contratado não aparecer em liderança, e ninguém repararia."""
    assert '"DIRETOR"' in fonte


def test_o_escopo_entra_em_todas_as_consultas(fonte):
    """Filtro que só alguns cartões obedecem é pior que filtro nenhum: era o
    que fazia a Análise de KM dizer 143.326 km vazios no cabeçalho e 95.632 na
    tabela logo abaixo. As sete consultas da tela recebem `{esc}`."""
    assert fonte.count("{esc}") >= 7, (
        f"só {fonte.count('{esc}')} consultas recebem o escopo — alguma "
        f"ficaria mostrando o quadro inteiro dentro do recorte de liderança")


def test_escopo_invalido_cai_em_todos_e_nao_recusa(fonte):
    """Recorte digitado errado na URL não pode deixar a tela em branco."""
    assert 'escopo = escopo if escopo in ESCOPOS else "todos"' in fonte
    assert 'ESCOPOS = ("todos", "lideranca", "demais")' in fonte


def test_a_composicao_da_lideranca_e_auditavel(fonte):
    """Filtro que não se audita vira número que ninguém defende numa reunião:
    a tela mostra cargo a cargo o que entrou na conta."""
    assert '"cargos": lid_cargos' in fonte
    assert '"limitrofes": limitrofes' in fonte, (
        "os cargos deixados de fora de propósito têm de ser declarados")


def test_o_denominador_de_liderados_e_o_quadro_inteiro(fonte):
    """`por_liderado` usa o total geral, não o do escopo — com o filtrado a aba
    Liderança mostraria 1 liderado por chefia."""
    assert "geral_n - lid_n) / lid_n" in fonte
    assert "WHERE {_ATIVO}\"\"\", p)[0]" in fonte.replace("'''", '"""')


def test_nivel_sem_ocupante_continua_na_tela(html):
    """Zero silencioso lê-se como filtro quebrado. E 'nunca existiu na casa' é
    diferente de 'existiu e hoje não há' — a tela separa os dois."""
    assert "ja_existiu" in html
    assert "já houve na casa · hoje ninguém" in html
    assert "nunca houve na folha" in html


def test_a_tela_diz_qual_recorte_esta_ativo(html):
    """Ler número de liderança achando que é o quadro inteiro é o erro que o
    filtro cria — o rótulo abaixo dos chips existe para impedi-lo."""
    assert "ppl-escopo-hint" in html
    assert "TODOS os números abaixo são apenas deles" in html


def test_trocar_o_escopo_refaz_a_consulta(html):
    """Mediana, dispersão e massa não se recalculam a partir do agregado já
    recebido — filtrar em memória devolveria número errado."""
    assert "PPL_ESCOPO = e;" in html
    assert re.search(r"pplEscopo\(e\)\{.*?loadPeople\(\)", html, re.S)
    assert "escopo='+encodeURIComponent(PPL_ESCOPO)" in html


def test_o_cartao_que_nao_segue_o_recorte_se_declara(html):
    """O cartão de composição mostra a liderança em QUALQUER escopo — inclusive
    em "Demais", onde ela é exatamente quem o recorte exclui do resto da tela.
    Sem o selo, os 16 do cartão e os 175 dos KPIs acima pareceriam a mesma
    população. É a regra da casa: card fora do filtro leva badge visível."""
    assert 'id="ppl-lid-selo"' in html
    assert "não segue o recorte" in html
    assert "PPL_ESCOPO !== 'lideranca'" in html


def test_o_cargo_e_normalizado_no_agrupamento(fonte):
    """O cadastro tem "AUXILIAR ADMINISTRATIVO" e "AUXILIAR ADMINISTRATIVo".
    Sem UPPER/TRIM a tela contaria dois cargos onde há um, medindo grafia em
    vez de função — a mesma razão de o telefone do WhatsApp ser normalizado."""
    assert '_CARGO = "UPPER(TRIM(vf.descfuncaocompleta))"' in fonte
    assert "GROUP BY vf.descfuncaocompleta" not in fonte, (
        "algum agrupamento por cargo ficou sem normalizar")
