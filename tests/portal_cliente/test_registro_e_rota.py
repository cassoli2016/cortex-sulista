# -*- coding: utf-8 -*-
"""A tela `cliop` está registrada nos SEIS lugares — e a rota respeita a sessão.

TELA NOVA TEM SEIS REGISTROS, NÃO UM, e essa classe de defeito não tem sintoma:
só ausência. O ícone some, a tela não aparece no celular, a busca não acha —
nada quebra, nada acende. Os guards moram longe do código que eles guardam, e
é por isso que este arquivo existe.

A rota é testada por CHAMADA DIRETA, com um request de mentira. Não é atalho:
o que se quer provar aqui é que a raiz vem da SESSÃO e que sem vínculo a
resposta é 403 legível — duas propriedades da função, não do middleware (esse
tem guard próprio em `test_rbac_dos_prefixos`).
"""
from __future__ import annotations

import pathlib
import types

import pytest
import yaml

from api import auth
from api import main
from api import portal_cliente as pc

RAIZ = "11222333"
ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def com_a_coluna(monkeypatch):
    """O estado NORMAL é a migration 0053 aplicada.

    A bancada de teste roda contra um banco que pode não tê-la, e `False` ali
    faria os testes do vínculo passarem por MOTIVO ERRADO — verdes porque o
    campo foi ignorado, não porque foi validado. Quem testa a janela sem a
    migration sobrescreve isto explicitamente.
    """
    monkeypatch.setattr(auth, "tem_coluna_vinculo", lambda: True)
INDEX = (ROOT / "api" / "static" / "index.html").read_text(encoding="utf-8")


# ------------------------------------------------------------ os seis registros

def test_1_a_tela_esta_no_RBAC():
    assert "cliop" in auth.TELAS
    rotulo, grupo = auth.TELAS["cliop"]
    assert rotulo == "Minha Operação"
    assert grupo == "Operação"


def test_2_a_rota_esta_mapeada_e_e_fail_closed():
    """Rota `/api/*` não mapeada é 403 para não-admin — mapear é o que a liga.

    DUAS telas liberam o mesmo prefixo, como `analise-km` já faz para `km` e
    `tvope`: a TV lê exatamente a mesma rota da tela. Sem `tvcli` aqui, um
    perfil só de TV (o da sala de operação, que é o caso de uso) levaria 403 e
    o painel nasceria quebrado — e o RBAC não acharia estranho, porque a rota
    nunca teria sido dele.
    """
    mapeadas = [telas for prefixo, telas in auth.ROTA_TELAS
                if prefixo == "/api/portal/cliente"]
    assert mapeadas == [frozenset({"cliop", "tvcli"})]


def test_2b_a_tela_NAO_e_de_todo_usuario_logado():
    """`cliop` fora de TELAS_TODO_LOGADO.

    Se entrasse lá, todo funcionário da casa passaria a ter a tela — e como o
    escopo recusa sem vínculo, o efeito visível seria uma tela nova quebrada
    no menu de todo mundo.
    """
    assert "cliop" not in auth.TELAS_TODO_LOGADO


def test_3_a_view_existe_no_HTML():
    assert 'id="view-cliop"' in INDEX


def test_4_esta_no_VIEWS_e_no_VIEW_GROUP():
    assert "cliop:'Minha Operação'" in INDEX
    assert "cliop:'Ope'" in INDEX


def test_5_esta_na_barra_lateral_e_na_GAVETA_do_celular():
    """Duas listas diferentes; a do celular é a que se esquece."""
    assert INDEX.count('href="#cliop"') >= 2
    assert 'data-view="cliop"' in INDEX
    assert 'onclick="fecharDrawer()"' in INDEX.split('href="#cliop"')[2][:120]


def test_6_tem_icone_proprio():
    assert "cliopic: IC(" in INDEX
    assert INDEX.count('data-ic="cliopic"') >= 2


def test_o_carregador_esta_nos_DOIS_loadmaps():
    """O arquivo tem dois mapas de carga; registrar em um só deixa a tela muda
    por um dos caminhos de navegação."""
    assert INDEX.count("cliop:loadCliop") == 2


def test_a_tela_esta_no_manual():
    """Um teste da casa cobra toda view de VIEWS com grupo — e a tela `#doc`
    lê daqui."""
    manual = yaml.safe_load((ROOT / "docs" / "manual.yaml").read_text(encoding="utf-8"))
    telas = [t for g in manual["grupos"] for t in g.get("telas", [])]
    assert "cliop" in telas


def test_o_menu_continua_alfabetico_no_grupo_operacao():
    """Tela nova entra 'no fim' por inércia; em três telas isso vira ordem de
    chegada. `Minha Operação` fica entre Jornada e Operação MWM."""
    bloco = INDEX.split('id="subsOpe"')[1].split("</div>")[0]
    import re
    rotulos = re.findall(r'data-view="[a-z]+"[^>]*>.*?<span>([^<]+)</span>', bloco)

    def chave(s):
        import unicodedata
        n = unicodedata.normalize("NFKD", s)
        return "".join(c for c in n if not unicodedata.combining(c)).lower()

    assert "Minha Operação" in rotulos
    assert rotulos == sorted(rotulos, key=chave), rotulos


# ------------------------------------------------------------ a rota

def _req(sessao):
    r = types.SimpleNamespace()
    r.state = types.SimpleNamespace(sessao=sessao)
    return r


def test_gente_da_casa_sem_escolha_recebe_a_LISTA_e_nao_um_403(monkeypatch):
    """A regra mudou em 05/09/2026, e mudou por decisão de quem opera.

    Antes a tela recusava quem não tivesse vínculo — inclusive gente da casa
    com a tela no perfil, que é justamente quem deveria abri-la para atender o
    cliente. Agora quem tem a tela e não tem vínculo ESCOLHE: 200 com a lista.
    A trava do usuário de cliente não mudou nada (ver
    `test_quem_tem_VINCULO_nao_escolhe_nem_pedindo`).
    """
    import json

    monkeypatch.setattr(pc, "get_clientes", lambda dias=365: {
        "clientes": [{"raiz": "11222333", "nome": "CLIENTE DUBLÊ S.A.", "cargas": 6826}],
        "janela_dias": dias, "fonte": "dublê"})
    resp = main.portal_cliente_dados(_req({"admin": True}), aba="agora")
    assert resp.status_code == 200
    corpo = json.loads(bytes(resp.body))
    assert corpo["escolher"] is True and corpo["travado"] is False
    assert corpo["clientes"][0]["raiz"] == "11222333"


def test_o_parametro_raiz_NAO_vence_o_vinculo_na_rota(monkeypatch):
    """A propriedade que separa um portal de um buscador de operação alheia.

    A rota passou a aceitar `raiz` para gente da casa escolher. O que NÃO pode
    mudar é quem manda: com vínculo, o parâmetro é ignorado. Aqui isso é
    cobrado ponta a ponta — não só em `alvo()` — porque é na rota que alguém
    acrescentaria "só um caso especial" mais adiante.
    """
    vistos = []

    def _agora(raiz, dias=45):
        vistos.append(raiz)
        return {"cargas": [], "em_curso": 0, "concluidas_na_janela": 0,
                "janela_dias": dias, "fonte": "dublê"}

    monkeypatch.setattr(pc, "get_agora", _agora)
    monkeypatch.setattr(pc, "nome_do_cliente", lambda r: "DUBLÊ")
    # cliente pedindo a operação de OUTRO cliente
    main.portal_cliente_dados(_req({"cliente_cnpj_raiz": RAIZ}),
                              aba="agora", raiz="44555666")
    # ... e pedindo sem nada
    main.portal_cliente_dados(_req({"cliente_cnpj_raiz": RAIZ}), aba="agora")
    assert vistos == [RAIZ, RAIZ], vistos


def test_a_resposta_diz_de_QUEM_e_o_numero(monkeypatch):
    """Painel de cliente que não nomeia o cliente é como alguém lê a conta
    errada e age em cima — e numa TV ninguém vai conferir o filtro."""
    import json

    monkeypatch.setattr(pc, "get_agora", lambda raiz, dias=45: {
        "cargas": [], "em_curso": 0, "concluidas_na_janela": 0,
        "janela_dias": dias, "fonte": "dublê"})
    monkeypatch.setattr(pc, "nome_do_cliente", lambda r: "CLIENTE DUBLÊ S.A.")
    resp = main.portal_cliente_dados(_req({"cliente_cnpj_raiz": RAIZ}), aba="agora")
    corpo = json.loads(bytes(resp.body))
    assert corpo["cliente_raiz"] == RAIZ
    assert corpo["cliente_nome"] == "CLIENTE DUBLÊ S.A."
    assert corpo["travado"] is True


def test_a_janela_pedida_e_limitada(monkeypatch):
    """Parâmetro que vem do navegador não escolhe o tamanho da varredura."""
    vistos = []
    monkeypatch.setattr(pc, "get_agora", lambda raiz, dias=45: (
        vistos.append(dias) or {"cargas": [], "em_curso": 0,
                                "concluidas_na_janela": 0, "janela_dias": dias,
                                "fonte": "dublê"}))
    for pedido in (-5, 0, 1, 45, 9999):
        main.portal_cliente_dados(_req({"cliente_cnpj_raiz": RAIZ}),
                                  aba="agora", dias=pedido)
    assert min(vistos) >= 1 and max(vistos) <= 180


def test_aba_desconhecida_cai_no_padrao_e_nao_estoura(monkeypatch):
    monkeypatch.setattr(pc, "get_agora", lambda raiz, dias=45: {
        "cargas": [], "em_curso": 0, "concluidas_na_janela": 0,
        "janela_dias": dias, "fonte": "dublê"})
    resp = main.portal_cliente_dados(_req({"cliente_cnpj_raiz": RAIZ}),
                                     aba="qualquer-coisa")
    assert resp.status_code == 200


# ------------------------------------------------------------ o vínculo no cadastro

@pytest.mark.parametrize("valor,esperado", [
    ("11222333", "11222333"),
    ("11.222.333/0001-99", "11222333"),   # colado do cadastro do ERP
    ("11222333000199", "11222333"),
])
def test_o_vinculo_aceita_raiz_e_cnpj_inteiro(valor, esperado):
    dados, erro = auth._cadastro_do_payload({"cliente_cnpj_raiz": valor})
    assert erro is None
    assert dados["cliente_cnpj_raiz"] == esperado


@pytest.mark.parametrize("valor", ["611", "abc", "1234567890", "FULANO"])
def test_o_vinculo_RECUSA_o_que_nao_vira_raiz(valor):
    """Raiz errada é portal vazio — e ninguém reporta isso como erro de
    cadastro, reporta como 'o portal não funciona'."""
    dados, erro = auth._cadastro_do_payload({"cliente_cnpj_raiz": valor})
    assert erro and "raiz do CNPJ" in erro
    assert dados == {}


def test_chave_ausente_NAO_mexe_e_chave_vazia_LIMPA():
    """A regra de edição parcial da casa, que aqui tem peso de segurança."""
    assert "cliente_cnpj_raiz" not in auth._cadastro_do_payload({"cargo": "X"})[0]
    assert auth._cadastro_do_payload({"cliente_cnpj_raiz": ""})[0]["cliente_cnpj_raiz"] is None


def test_texto_sem_digito_nao_apaga_o_vinculo_em_silencio():
    """"abc" no campo é engano, não intenção de desvincular — e desvincular
    calado tira o portal de alguém sem ninguém ver erro."""
    dados, erro = auth._cadastro_do_payload({"cliente_cnpj_raiz": "NOME DO CLIENTE"})
    assert erro is not None
    assert dados == {}


# ------------------------------------------------- a janela sem a migration

def test_o_check_da_coluna_filtra_pelo_SCHEMA_CORRENTE():
    """Sem o filtro, um schema de TESTE esquecido responde pela produção.

    Aconteceu em 05/09/2026: `information_schema.columns WHERE table_name =
    'usuarios'` achou a coluna em `teste_aud_07a1a0a2f1` — sobra de uma suíte
    antiga no MESMO banco — e o detector respondeu "existe" enquanto o schema
    `cortex` não tinha nada. O guard mentiria justamente no estado que ele foi
    escrito para pegar, e a tela de Usuários cairia com a Saúde no verde.
    """
    fonte = (ROOT / "api" / "auth.py").read_text(encoding="utf-8")
    trecho = fonte.split("def tem_coluna_vinculo")[1].split("def ")[0]
    assert "current_schema()" in trecho

    fonte_srv = (ROOT / "api" / "servidor.py").read_text(encoding="utf-8")
    trecho_srv = fonte_srv.split("def _portal_cliente")[1].split("\ndef ")[0]
    assert "current_schema()" in trecho_srv


def test_sem_a_coluna_o_cadastro_de_usuario_CONTINUA_salvando(monkeypatch):
    """O AutoDeploy não roda migration: a janela entre código e DDL é real.

    Nela o formulário de usuário manda `cliente_cnpj_raiz` como sempre (vazio
    vira `None`). Se o validador insistisse na coluna, um `UPDATE` com coluna
    inexistente derrubaria a tela de Usuários inteira — por causa de uma tela
    que ninguém ainda usa. O campo é ignorado; quem grita é a Saúde.
    """
    monkeypatch.setattr(auth, "tem_coluna_vinculo", lambda: False)
    dados, erro = auth._cadastro_do_payload(
        {"cargo": "Analista", "cliente_cnpj_raiz": "11222333"})
    assert erro is None
    assert dados == {"cargo": "Analista"}
    assert "cliente_cnpj_raiz" not in dados


def test_com_a_coluna_o_vinculo_volta_a_gravar(monkeypatch):
    monkeypatch.setattr(auth, "tem_coluna_vinculo", lambda: True)
    dados, erro = auth._cadastro_do_payload({"cliente_cnpj_raiz": "11222333"})
    assert erro is None and dados["cliente_cnpj_raiz"] == "11222333"


def test_a_saude_acusa_a_migration_pendente_com_o_COMANDO(monkeypatch):
    """Cartão que diz o que fazer, não só que está errado."""
    from api import servidor

    class _C:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, *a):
            class _R:
                def fetchone(_): return None
            return _R()

    monkeypatch.setattr(auth, "_conn", lambda *a, **k: _C())
    cartao = servidor._portal_cliente()
    assert cartao["status"] == "erro"
    assert "migrar_schema.py" in cartao["detalhe"]
    assert "0053" in cartao["detalhe"]


# ================================================ o painel de TV (`tvcli`)

def test_tv_registrada_no_RBAC_e_no_grupo_de_BI():
    assert auth.TELAS["tvcli"] == ("Painel TV — Operação do Cliente",
                                   "Business Intelligence")


def test_tv_nos_DOIS_E_TV():
    """A régua e a auditoria de espaços têm listas SEPARADAS de telas de TV.

    Entrar em uma só faz a outra medir a TV com a régua de painel comum —
    1050px contra 900px — e acusar uma tela que está certa, ou pior, deixar
    passar uma que não está.
    """
    import sys
    sys.path.insert(0, str(ROOT))
    import scripts.medir_paineis as medir
    import scripts.auditar_espacos as espacos
    assert "tvcli" in medir.E_TV
    assert "tvcli" in espacos.E_TV


def test_tv_esta_nas_QUATRO_grafias_da_lista_de_telas_de_TV():
    """O `index.html` repete a disjunção das telas de TV em quatro grafias.

    Faltar em uma delas não quebra nada visível: a tela abre, só não entra em
    modo TV, ou não recarrega sozinha, ou não redesenha ao virar tela cheia.
    Defeito sem sintoma é o que este teste existe para pegar — e a duplicação
    em si está anotada na crônica como dívida.
    """
    for grafia in (
        "k==='tvfat' || k==='tvope' || k==='tvdir' || k==='tvcom' || k==='tvcli'",
        "v==='tvfat' || v==='tvope' || v==='tvdir' || v==='tvcom' || v==='tvcli'",
        "v === 'tvfat' || v === 'tvope' || v === 'tvdir' || v === 'tvcom' || v === 'tvcli'",
    ):
        assert grafia in INDEX, grafia
    assert "else if(cv==='tvcli') loadTvCli();" in INDEX      # tick de 60s
    assert "else if(v==='tvcli') loadTvCli();" in INDEX       # reflow


def test_tv_tem_view_icone_menu_e_carregador():
    assert 'id="view-tvcli"' in INDEX
    assert "tvcli:'Painel TV — Operação do Cliente'" in INDEX
    assert "tvcli:'Bi'" in INDEX
    assert "tvcliic: IC(" in INDEX
    assert INDEX.count("tvcli:loadTvCli") == 2
    assert INDEX.count('href="#tvcli"') >= 2          # sidebar + gaveta


def test_tv_nao_tem_ABA_nem_TOOLTIP():
    """Regra dura do mural: ninguém clica numa TV, e ninguém passa o mouse.

    Cada número se explica no rótulo. Uma sub-aba num painel de parede esconde
    metade do conteúdo para sempre; um `title` esconde a explicação de todos.
    """
    bloco = INDEX.split('id="view-tvcli"')[1].split("</section>")[0]
    assert "subtabs" not in bloco
    assert 'class="aba"' not in bloco
    assert "title=" not in bloco.replace('title="tela cheia"', "").replace(
        'title="sair do modo TV"', "")


def test_tv_tem_TELA_CHEIA():
    """É o pedido que originou o painel: acompanhar a operação em tela cheia."""
    bloco = INDEX.split('id="view-tvcli"')[1].split("</section>")[0]
    assert "tvFull()" in bloco


def test_tv_esta_no_manual():
    manual = yaml.safe_load((ROOT / "docs" / "manual.yaml").read_text(encoding="utf-8"))
    telas = [t for g in manual["grupos"] for t in g.get("telas", [])]
    assert "tvcli" in telas


# ==================================== mapa, medidor e rosca no painel de TV

def _bloco_tv():
    return INDEX.split('id="view-tvcli"')[1].split("</section>")[0]


def test_o_mapa_da_TV_tem_classe_PROPRIA_e_nao_a_da_Torre():
    """`.tvw-mapa` traz `grid-row:1/3;grid-column:2` cravado do layout da Torre.

    Reusar a classe trouxe junto um POSICIONAMENTO que não era meu: o inline
    vencia o `grid-column`, mas o `grid-row` continuava valendo e jogava o card
    para a primeira linha da grade. Só o render mostrou — é a regra da casa,
    a regra de CSS pode existir, estar certa e não valer.
    """
    bloco = _bloco_tv()
    assert 'class="tv-card tvc-mapa"' in bloco
    assert "tvw-mapa" not in bloco
    assert ".tvc-mapa{" in INDEX


def test_o_mapa_usa_leaflet_da_casa_e_nao_CDN():
    """Leaflet é vendorizado; `ensureLeaflet` é quem carrega."""
    assert "await ensureLeaflet()" in INDEX.split("async function tvCliMapa")[1][:400]


def test_o_mapa_agrupa_o_que_esta_no_mesmo_patio():
    """Numa operação planta a planta os veículos param no MESMO ponto.

    Sem agrupar, o render mostrou seis etiquetas ilegíveis empilhadas em
    Cruzeiro. Grupo de um mostra a PLACA; grupo maior mostra a contagem.
    """
    corpo = INDEX.split("async function tvCliMapa")[1].split("\n}")[0]
    assert "toFixed(2)" in corpo, "a grade de agrupamento sumiu"
    assert "veíc." in corpo


def test_posicao_velha_NAO_some_do_mapa():
    corpo = INDEX.split("async function tvCliMapa")[1].split("\n}")[0]
    assert "todasVelhas" in corpo
    assert "#6E7883" in corpo, "a cor de posição velha sumiu"


def test_a_cobertura_do_mapa_vai_na_tela_SEM_nomear_fornecedor():
    """A cobertura e a idade ficam; o nome de quem nos vende rastreamento sai.

    "33 de 33 veículos" impede olhar os pontos e concluir que aquilo é a
    operação inteira, e a idade impede tomar posição de ontem por posição de
    agora — as duas coisas interessam a quem lê a parede. Já "erp" e "gobrax"
    são fornecedor NOSSO: num painel que o cliente lê, não dizem nada a ele e
    expõem a nossa cadeia. A procedência por fornecedor continua no payload,
    para a Saúde e o diagnóstico interno.
    """
    corpo = INDEX.split("async function tvCliMapa")[1].split("\n}")[0]
    assert "veículos" in corpo and "fresca_ate_min" in corpo
    assert "r.fontes" not in corpo


# O medidor e a rosca sao cobrados por COMPORTAMENTO em
# `tests/frontend/test_tvcli_figuras.py`, onde as funcoes sao EXECUTADAS no
# navegador. A primeira versao deste guard lia o texto-fonte do arquivo --
# "o `path` esta la", "a palavra `zona` aparece" -- e ficou VERDE com a
# funcao sabotada, porque codigo morto continua escrito. Guard de texto
# sobrevive aqui so onde o que se afirma E o texto: uma classe de CSS, um
# registro de tela, uma chamada que precisa existir.


def test_o_medidor_usa_o_MESMO_fator_de_arco_da_Torre():
    """Dois arcos com medidas diferentes na mesma casa seriam duas verdades
    sobre o que é "cheio"."""
    assert INDEX.count("* 1.319") >= 1
    corpo = INDEX.split("function tvCliGauge")[1].split("\n}")[0]
    assert "1.319" in corpo


def test_sem_regua_o_medidor_NAO_inventa_verde():
    corpo = INDEX.split("function tvCliGauge")[1].split("\n}")[0]
    assert "sem régua de freetime" in corpo


def test_a_rosca_leva_rotulo_DIRETO_porque_TV_nao_tem_tooltip():
    corpo = INDEX.split("function tvCliRosca")[1].split("\n}")[0]
    assert "tvc-leg" in corpo
    assert "title=" not in corpo


def test_a_rosca_declara_por_que_e_rosca_e_nao_barra():
    """A casa prefere barra empilhada quando UMA categoria domina.

    Aqui as etapas ficam equilibradas, que é o caso em que o anel funciona — e
    isso está escrito, para quem mudar saber que a escolha foi medida e não
    estética.
    """
    ctx = INDEX.split("function tvCliRosca")[0][-1200:]
    assert "barra empilhada" in ctx and "domina" in ctx


def test_numero_em_portugues_leva_VIRGULA():
    """O separador saía do JavaScript, não do país: o float concatenado na
    string entregava ponto no mural."""
    assert "function tvH(v)" in INDEX
    corpo = INDEX.split("async function loadTvCli")[1].split("\nasync function")[0]
    assert "tvH(" in corpo
    assert "descarga_piso + 'h'" not in corpo


# ============================== o painel de TV: presença sem inventar cor

def test_a_TV_nao_estica_os_cards_ate_a_altura_do_mais_alto():
    """`align-items:start` na segunda linha.

    Com o `stretch` padrão o cartão do medidor acompanhava a altura da tabela e
    sobrava meia tela de vazio embaixo do arco. Numa parede, vazio não é
    respiro — é espaço que podia estar dizendo alguma coisa.
    """
    assert ".tvc-linha2{align-items:start}" in INDEX
    assert 'class="tv-grid tvc-linha2"' in INDEX


def test_a_grade_da_TV_e_minmax_0_1fr():
    """A armadilha que a régua NÃO pega em painel de TV.

    `1fr` é `minmax(auto,1fr)`: a trilha não encolhe abaixo do min-content, e
    a tabela `nowrap` de quatro colunas empurrou o card para FORA da tela sem
    erro nenhum. A régua de largura pula os `E_TV`, então aqui o guard é este.
    """
    assert "#view-tvcli .tv-grid{grid-template-columns:repeat(4,minmax(0,1fr))}" in INDEX
    assert "#view-tvcli .tv-tab{table-layout:fixed}" in INDEX


def test_a_tabela_da_TV_nao_quebra_linha():
    """Rota e situação em duas linhas dobram a altura de cada registro.

    Numa parede, texto cortado com reticências se lê melhor que texto
    empilhado — e as quatro colunas têm largura declarada, senão `fixed`
    divide igual e o número da coleta sai com reticências.
    """
    assert "#tvcli-cargas td,#view-tvcli .tv-tab th{white-space:nowrap;overflow:hidden;" in INDEX
    for n in (1, 2, 3, 4):
        assert "#view-tvcli .tv-tab th:nth-child(%d){width:" % n in INDEX


def test_o_heroi_traz_o_TOTAL_e_a_reparticao_junto():
    """Obrigar o olho a somar quatro cartões para chegar no total desfaz a
    leitura de três segundos que a TV existe para dar."""
    bloco = _bloco_tv()
    assert 'id="tvcli-hero"' in bloco and 'id="tvcli-etapas"' in bloco
    assert ".tvc-hero .n{font-size:clamp(" in INDEX


def test_o_chip_de_etapa_leva_o_NUMERO_junto_da_cor():
    """Sem tooltip numa TV, cor sozinha não diz nada."""
    corpo = INDEX.split("async function loadTvCli")[1].split("\n}")[0]
    assert "tvc-chip" in corpo
    for etapa in ("'Em viagem'", "'No destino'", "'Na origem'"):
        assert etapa + "," in corpo, etapa


def test_carga_sem_apontamento_NAO_aparece_no_painel_do_cliente():
    """Decisão de quem opera (06/09/2026).

    A carga existe — a coleta foi emitida e o manifesto não fechou — mas o que
    o portal teria a dizer sobre ela é "não sabemos por onde anda", e isso é
    processo nosso, não informação do cliente. Ela volta no instante em que a
    operação apontar o primeiro marco.

    O CUSTO fica dito no código e aqui: a carga emitida hoje some do painel até
    o primeiro apontamento, que chega com cerca de um dia de atraso.
    """
    corpo = INDEX.split("async function loadTvCli")[1].split("\n}")[0]
    assert "Sem apontamento'," not in corpo
    assert "semApont" not in corpo


def test_o_brilho_segue_a_cor_do_ESTADO_e_nao_inventa_uma():
    """`currentColor`: o card acende na cor que o semáforo já decidiu.

    Se o brilho tivesse cor própria, seria um quarto estado — e o semáforo
    desta casa tem três.
    """
    assert ".tvc-glow{box-shadow:inset 0 0 0 2px currentColor" in INDEX
    corpo = INDEX.split("async function loadTvCli")[1].split("\n}")[0]
    assert "card.style.color = cor" in corpo


def test_o_ticker_so_aparece_quando_ha_o_que_dizer():
    """Parede que alarma sempre é parede que ninguém olha."""
    corpo = INDEX.split("function tvCliTicker")[1].split("\n}")[0]
    assert "if(!itens.length){ cx.hidden = true;" in corpo
    # cada linha é um fato com número, nunca um aviso genérico
    assert "sem posição no rastreamento" in corpo
    assert "acima do freetime" in corpo


def test_o_ticker_repete_a_lista_para_nao_ficar_vazio():
    """A animação anda 100% da largura e volta ao início: com uma cópia só, a
    faixa fica vazia metade do tempo."""
    corpo = INDEX.split("function tvCliTicker")[1].split("\n}")[0]
    assert "linha + linha" in corpo


def test_o_movimento_respeita_quem_pediu_menos_movimento():
    assert "@media (prefers-reduced-motion: reduce){" in INDEX
    i = INDEX.index(".tvc-tick-in{animation:none")
    assert i > INDEX.index("@keyframes tvcTick")
