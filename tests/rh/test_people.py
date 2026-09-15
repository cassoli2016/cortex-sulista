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


def test_o_denominador_de_liderados_e_o_quadro_do_recorte_sem_o_nivel(monkeypatch):
    """`por_liderado` usa o quadro do recorte (modalidade e filial), NÃO o do
    nível — com o nível aplicado a aba Liderança mostraria 1 liderado por
    chefia. Lido no SQL que a função EXECUTA, não no texto do arquivo."""
    ppl, ch = _gravar(monkeypatch)
    ppl.get_people("lideranca", "OPER", "FILIAL SBC")
    # a regra da modalidade tem LIKE 'MOT%' dentro; tirada ela, o LIKE que
    # sobrar só pode ser o do nível (liderança) — que o denominador não leva
    geral = [s for s, _ in ch
             if s.lstrip().startswith("SELECT COUNT(*) n, ROUND(SUM(vf.salbase),2) massa")
             and "'F'" not in s and "LIKE" not in s.replace(ppl.MODALIDADE, "")]
    assert len(geral) == 1, "o denominador sumiu ou passou a receber o nível"
    assert ":filial" in geral[0] and ":modal" in geral[0], (
        "a liderança da filial tem de se medir contra o quadro da filial")
    assert "geral_n - lid_n) / lid_n" in FONTE.read_text(encoding="utf-8")


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


# ------------------------------------------------ modalidade e filial
#
# Pedido de quem opera (15/09/2026): filtrar a tela por modalidade — ADM, OPER
# e MOT — e por filial. Medido no mesmo dia, 193 ativos: ADM 29 · OPER 83 ·
# MOT 81; filial é a `descsecao` (12 unidades), a mesma das telas de Férias e
# CNH.
#
# Os testes abaixo trocam `_q` por um gravador: o que se confere é o SQL que a
# função de fato EXECUTA e os parâmetros que ela manda junto.

class _Linha(dict):
    """Linha de dublê: coluna que o teste não preencheu vem None, como um
    agregado vazio do Oracle — menos `n`, que é COUNT(*) e nunca é NULL."""
    def __missing__(self, chave):
        return 0 if chave == "n" else None


def _gravar(monkeypatch, filiais=("FILIAL SBC", "MATRIZ"),
            modais=(("ADM", 29), ("OPER", 83), ("MOT", 81))):
    import api.people as ppl
    chamadas = []

    def q(sql, params=None):
        chamadas.append((sql, dict(params or {})))
        if "descsecao f" in sql:
            return [_Linha(f=f, total=10, n=10) for f in filiais]
        if " m, COUNT(*) total" in sql:
            return [_Linha(m=m, total=n, n=n) for m, n in modais]
        return [_Linha()]

    monkeypatch.setattr(ppl, "_q", q)
    return ppl, chamadas


def _binds(sql: str) -> set[str]:
    """Os `:nome` do SQL, fora dos literais — 'HH24:MI' não é bind."""
    return set(re.findall(r":(\w+)", re.sub(r"'[^']*'", "''", sql)))


def _excecao(sql: str) -> bool:
    """As consultas que NÃO recebem o recorte, de propósito: o relógio do
    banco, as listas que alimentam os próprios filtros (contam o quadro
    inteiro, `COUNT(*) total`) e o "já houve na casa" dos níveis."""
    return ("FROM dual" in sql or "COUNT(*) total" in sql
            or ("situacaofunc" not in sql and "flp_afastados" not in sql))


@pytest.mark.parametrize("args", [
    ("todos", "todas", ""), ("lideranca", "MOT", "FILIAL SBC"),
    ("demais", "ADM", ""), ("todos", "OPER", "MATRIZ")])
def test_cada_consulta_leva_exatamente_os_parametros_que_usa(monkeypatch, args):
    """O driver Oracle recusa parâmetro que o SQL não usa (DPY-4008) e o que
    falta. Um dicionário único para a tela inteira derrubaria as consultas da
    casa inteira, que não levam `:filial` — e a tela viraria 503 no primeiro
    clique em uma filial."""
    ppl, ch = _gravar(monkeypatch)
    ppl.get_people(*args)
    assert len(ch) >= 18, "o gravador não viu as consultas da tela"
    for sql, params in ch:
        assert _binds(sql) == set(params), (sorted(_binds(sql)), sorted(params), sql)


def test_modalidade_e_filial_entram_em_toda_consulta_do_quadro(monkeypatch):
    """Filtro que só alguns cartões obedecem é pior que filtro nenhum. Toda
    consulta ao quadro — KPIs, afastamentos, áreas, cargos, pirâmide, tempo de
    casa e o cartão da liderança — recebe os dois."""
    ppl, ch = _gravar(monkeypatch)
    ppl.get_people("todos", "MOT", "FILIAL SBC")
    quadro = [s for s, _ in ch if not _excecao(s)]
    assert len(quadro) >= 14, f"só {len(quadro)} consultas ao quadro — a varredura encolheu"
    for sql in quadro:
        assert "vf.descsecao = :filial" in sql, sql
        assert ppl.MODALIDADE + " = :modal" in sql, sql
    # a exceção do "já houve na casa" não pode esconder consulta de verdade
    historico = [s for s, _ in ch if _excecao(s)
                 and "FROM dual" not in s and "COUNT(*) total" not in s]
    assert len(historico) == 4, "só os quatro níveis de liderança olham a casa inteira"


def test_recorte_desconhecido_cai_em_todas_e_nao_zera_a_tela(monkeypatch):
    """Filial fora da lista ou modalidade inventada na URL: a tela mostra o
    quadro e DIZ que o recorte é "todas" — não uma tela zerada sem motivo."""
    ppl, ch = _gravar(monkeypatch)
    d = ppl.get_people("todos", "motoqueiro", "FILIAL QUE NAO EXISTE")
    assert d["filtros"] == {"escopo": "todos", "modalidade": "todas", "filial": ""}
    assert not any("filial" in p or "modal" in p for _, p in ch)


def test_modalidade_aceita_minuscula(monkeypatch):
    ppl, _ = _gravar(monkeypatch)
    assert ppl.get_people("todos", " mot ", "")["filtros"]["modalidade"] == "MOT"


def test_sem_departamento_so_vira_opcao_quando_existe(monkeypatch):
    """"Sem departamento" é ausência de cadastro: chip que diz 0 para sempre
    seria ruído, e chip que some quando alguém cai lá esconderia o furo."""
    ppl, _ = _gravar(monkeypatch)
    assert [m["modalidade"] for m in ppl.get_people()["modalidades"]] == ["ADM", "OPER", "MOT"]
    ppl, _ = _gravar(monkeypatch, modais=(("ADM", 29), ("OPER", 83), ("MOT", 81), ("SEM", 2)))
    assert [m["modalidade"] for m in ppl.get_people()["modalidades"]] == ["ADM", "OPER", "MOT", "SEM"]


def test_a_regra_da_modalidade_executada_em_casos_do_cadastro_real(esquema_pg):
    """A regra RODA num banco, contra as combinações de área × departamento
    que o GLOBUS tem (15/09/2026). Três coisas que ler a expressão não prova:
    MOT vence o departamento (as áreas MOT estão todas no OPERACIONAL); a área
    "MOT AUDI " tem espaço no fim; e "GESTAO DE MOTORISTAS" não é motorista.
    O CASE usa só SQL padrão (UPPER, TRIM, LIKE), igual no Oracle e aqui."""
    from api import pglocal
    import api.people as ppl
    casos = [("MOT SBC", "OPERACIONAL", "MOT"),
             ("MOT AUDI ", "OPERACIONAL", "MOT"),
             ("mot matriz", "OPERACIONAL", "MOT"),
             ("GESTAO DE MOTORISTAS", "OPERACIONAL", "OPER"),
             ("MANUTENCAO SBC", "OPERACIONAL", "OPER"),
             ("CCO", "OPERACIONAL", "OPER"),
             ("CCO", "ADMINISTRATIVO", "ADM"),
             ("MANUTENCAO MATRIZ", "ADMINISTRATIVO", "ADM"),
             ("RH", None, "SEM"),
             (None, None, "SEM")]

    def lit(v):
        return "NULL" if v is None else "'" + v.replace("'", "''") + "'"
    valores = ", ".join(f"({lit(a)}::text, {lit(d)}::text, {lit(e)})" for a, d, e in casos)
    r = pglocal.query(
        f"SELECT vf.descarea, vf.esperado, {ppl.MODALIDADE} AS obtido "
        f"FROM (VALUES {valores}) AS vf(descarea, descdepto, esperado)",
        esquema=esquema_pg)
    assert len(r) == len(casos)
    errados = [x for x in r if x["esperado"] != x["obtido"]]
    assert not errados, errados


def test_trocar_modalidade_ou_filial_refaz_a_consulta(html):
    """Mediana e massa não se recalculam a partir do agregado recebido."""
    assert re.search(r"pplModal\(m\)\{.*?loadPeople\(\)", html, re.S)
    assert re.search(r"pplFilial\(f\)\{.*?loadPeople\(\)", html, re.S)
    assert "'&modalidade='+encodeURIComponent(PPL_MODAL)" in html
    assert "'&filial='+encodeURIComponent(PPL_FILIAL)" in html
