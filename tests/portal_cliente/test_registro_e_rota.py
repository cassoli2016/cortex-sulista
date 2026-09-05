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

RAIZ = "61156113"
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
    """Rota `/api/*` não mapeada é 403 para não-admin — mapear é o que a liga."""
    mapeadas = [telas for prefixo, telas in auth.ROTA_TELAS
                if prefixo == "/api/portal/cliente"]
    assert mapeadas == [frozenset({"cliop"})]


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


def test_sem_vinculo_a_rota_devolve_403_LEGIVEL():
    """Recusa legível é 4xx.

    Um 5xx aqui teria o corpo trocado pela página do Cloudflare e o usuário
    leria "erro interno" onde o que falta é um cadastro.
    """
    import json

    resp = main.portal_cliente_dados(_req({"admin": True}), aba="agora")
    assert resp.status_code == 403
    corpo = json.loads(bytes(resp.body))
    assert corpo["erro"] == "sem_vinculo_cliente"
    assert "Administração" in corpo["mensagem"]


def test_a_raiz_vem_da_SESSAO_e_nao_do_parametro(monkeypatch):
    """A propriedade que separa um portal de um buscador de operação alheia.

    Se o cliente fosse parâmetro, trocar a URL leria a carteira do vizinho — e
    o RBAC por tela não veria problema nenhum, porque a tela é a mesma e o
    usuário tem acesso a ela.
    """
    vistos = []

    def _agora(raiz, dias=45):
        vistos.append(raiz)
        return {"cargas": [], "em_curso": 0, "concluidas_na_janela": 0,
                "janela_dias": dias, "fonte": "dublê"}

    monkeypatch.setattr(pc, "get_agora", _agora)
    main.portal_cliente_dados(_req({"cliente_cnpj_raiz": RAIZ}), aba="agora")
    assert vistos == [RAIZ]

    # A assinatura não aceita cliente/raiz/cnpj como parâmetro — nem por engano.
    import inspect
    params = set(inspect.signature(main.portal_cliente_dados).parameters)
    assert not (params & {"raiz", "cliente", "cnpj", "cliente_cnpj_raiz"})


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
    ("61156113", "61156113"),
    ("61.156.113/0001-75", "61156113"),   # colado do cadastro do ERP
    ("61156113000175", "61156113"),
])
def test_o_vinculo_aceita_raiz_e_cnpj_inteiro(valor, esperado):
    dados, erro = auth._cadastro_do_payload({"cliente_cnpj_raiz": valor})
    assert erro is None
    assert dados["cliente_cnpj_raiz"] == esperado


@pytest.mark.parametrize("valor", ["611", "abc", "1234567890", "IOCHPE"])
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
    dados, erro = auth._cadastro_do_payload({"cliente_cnpj_raiz": "IOCHPE MAXION"})
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
        {"cargo": "Analista", "cliente_cnpj_raiz": "61156113"})
    assert erro is None
    assert dados == {"cargo": "Analista"}
    assert "cliente_cnpj_raiz" not in dados


def test_com_a_coluna_o_vinculo_volta_a_gravar(monkeypatch):
    monkeypatch.setattr(auth, "tem_coluna_vinculo", lambda: True)
    dados, erro = auth._cadastro_do_payload({"cliente_cnpj_raiz": "61156113"})
    assert erro is None and dados["cliente_cnpj_raiz"] == "61156113"


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
