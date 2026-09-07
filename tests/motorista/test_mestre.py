# -*- coding: utf-8 -*-
"""O código mestre: o que ele abre, e as seis coisas que ele não deixa abrir.

ESTE ARQUIVO GUARDA UM SEGREDO QUE NÃO EXPIRA. O código de entrada do
motorista vive 10 minutos e vale para uma pessoa; o mestre vale para sempre e
abre a conta de qualquer um dos ~300. A diferença de risco é toda a razão de
os testes daqui serem sobre RECUSA, não sobre o caminho feliz.

Cada teste abaixo cobre uma contenção que as outras não cobrem — e o guard que
mais importa é o `test_a_lista_nao_sai_sem_o_codigo`: uma rota que listasse os
motoristas antes de conferir o segredo seria, sozinha, a lista de quem dirige
para esta empresa.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import pglocal
from api.motorista import mestre as mm
from api.motorista import sessao as msessao

from .conftest import cadastrar

#: Um segredo de teste com o tamanho que o módulo exige. Literal e não gerado:
#: se ele passasse a ser derivado de `mm.TAMANHO_MINIMO`, baixar a constante
#: baixaria junto o segredo do teste e o guard ficaria verde para sempre — a
#: armadilha do "dublê que se monta a partir da constante testada".
CODIGO = "chave-de-teste-1234567890"


@pytest.fixture
def com_codigo(esq, monkeypatch):
    """O segredo no ambiente, e o schema descartável já redirecionado."""
    monkeypatch.setattr(mm, "_segredo", lambda: CODIGO)
    return esq


# ----------------------------------------------------------------- o segredo

def test_sem_configurar_nao_abre_nada(esq, monkeypatch):
    """Instalação incompleta recusa como recusaria código errado — e não
    levanta. Sem o segredo no cofre, o acesso simplesmente não existe."""
    monkeypatch.delenv(mm.CHAVE, raising=False)
    monkeypatch.setattr(mm, "_segredo", lambda: "")
    assert not mm.configurado()
    with pytest.raises(mm.Recusa):
        mm.conferir("qualquer coisa", ip="1.2.3.4", esquema=esq)


def test_codigo_curto_e_recusado_mesmo_estando_configurado(esq, monkeypatch):
    """O piso de tamanho vale no `_segredo`, não na comparação: assim não
    existe caminho no módulo em que um segredo fraco valha por acidente.

    Sem este guard, alguém põe "sulista2026" no cofre e o acesso à PII de 300
    pessoas passa a caber num palpite.
    """
    monkeypatch.setenv(mm.CHAVE, "curto123")
    from api import credenciais
    monkeypatch.setattr(credenciais, "ler", lambda *a, **k: "")
    assert not mm.configurado()
    with pytest.raises(mm.Recusa):
        mm.conferir("curto123", ip="1.2.3.4", esquema=esq)


def test_o_codigo_certo_passa_e_o_errado_nao(com_codigo):
    mm.conferir(CODIGO, ip="1.2.3.4", esquema=com_codigo)     # não levanta
    with pytest.raises(mm.Recusa):
        mm.conferir(CODIGO + "x", ip="1.2.3.5", esquema=com_codigo)


def test_a_tentativa_e_contada_ANTES_da_comparacao(com_codigo):
    """Contar depois deixaria de fora exatamente as que interessam — as que
    erram — e o teto nunca chegaria. É o mesmo erro que `entrada.confirmar` já
    não comete."""
    for _ in range(3):
        with pytest.raises(mm.Recusa):
            mm.conferir("errado", ip="9.9.9.9", esquema=com_codigo)
    r = pglocal.um("SELECT count(*) AS n FROM mot_mestre_tentativas "
                   "WHERE ip = '9.9.9.9'", esquema=com_codigo)
    assert r["n"] == 3


def test_o_teto_por_endereco_barra_ate_o_codigo_CERTO(com_codigo):
    """O teto é do endereço, não do código: quem estourou tentando errado não
    entra digitando certo na sequência. Sem isso, o teto seria um aviso."""
    for _ in range(mm.MAX_TENTATIVAS_HORA):
        with pytest.raises(mm.Recusa):
            mm.conferir("errado", ip="8.8.8.8", esquema=com_codigo)
    with pytest.raises(mm.Recusa):
        mm.conferir(CODIGO, ip="8.8.8.8", esquema=com_codigo)
    # e o teto é POR ENDEREÇO: outro IP continua entrando
    mm.conferir(CODIGO, ip="8.8.4.4", esquema=com_codigo)


def test_o_codigo_tentado_nunca_e_gravado(com_codigo):
    """Nem em hash: hash de tentativa errada é inútil e hash da certa é o
    próprio segredo num lugar a mais."""
    mm.conferir(CODIGO, ip="1.1.1.1", esquema=com_codigo)
    colunas = pglocal.query(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = %(e)s AND table_name = 'mot_mestre_tentativas'""",
        {"e": com_codigo}, com_codigo)
    nomes = {c["column_name"] for c in colunas}
    assert nomes == {"id", "ip", "quando", "aceita"}, (
        "coluna nova em mot_mestre_tentativas — o código tentado não entra aqui")


# ------------------------------------------------------------------- a lista

def test_a_lista_nao_traz_o_codigo_do_ERP(com_codigo):
    """O `motorista_codigo` é o CPF para pessoa física, e esta lista vai para
    um navegador. Só id opaco e nome saem daqui — a mesma disciplina da lista
    de escolha da entrada."""
    cadastrar(com_codigo, "12345678901", "5547999990001", "FULANO DE TAL")
    r = mm.motoristas(esquema=com_codigo)
    assert r["motoristas"] and r["total"] == 1
    for m in r["motoristas"]:
        assert set(m) == {"id", "nome"}
    assert "12345678901" not in repr(r)


def test_a_lista_conta_o_que_cortou(com_codigo, monkeypatch):
    """Top-N sem contador vira total falso: "40 motoristas" quando são 300 é a
    diferença entre conferir a operação e achar que se conferiu."""
    monkeypatch.setattr(mm, "LIMITE_LISTA", 2)
    for i in range(5):
        cadastrar(com_codigo, f"MOT-{i}", "554799999000%d" % i, f"NOME {i}")
    r = mm.motoristas(esquema=com_codigo)
    assert r["mostrados"] == 2 and r["total"] == 5


def test_desligado_nao_aparece_e_nao_abre(com_codigo):
    mid = cadastrar(com_codigo, "MOT-X", "5547999990009", "SAIU DA CASA",
                    ativo=False)
    assert mm.motoristas(esquema=com_codigo)["total"] == 0
    with pytest.raises(mm.Recusa):
        mm.abrir(mid, esquema=com_codigo)


# ------------------------------------------------------------------ a sessão

def test_a_sessao_nasce_marcada_e_com_prazo_curto(com_codigo):
    """As três coisas que a marca muda: a tarja, o prazo e a trilha. Sem ela na
    linha, a sessão mestre seria indistinguível da do motorista."""
    import jwt
    from api import auth

    mid = cadastrar(com_codigo, "MOT-1", "5547999990001", "FULANO")
    r = mm.abrir(mid, esquema=com_codigo)

    linha = pglocal.um("SELECT mestre FROM mot_sessoes WHERE id = %(i)s",
                       {"i": r["sessao_id"]}, com_codigo)
    assert linha["mestre"] is True

    claims = jwt.decode(r["token"], auth.SECRET, algorithms=["HS256"])
    horas = (claims["exp"] - claims["iat"]) / 3600.0
    assert abs(horas - mm.TTL_HORAS) < 0.1, "o prazo curto não entrou no token"
    assert horas < msessao.TTL_DIAS * 24, "a sessão mestre herdou os 30 dias"

    sess = msessao.atual(r["token"], com_codigo)
    assert sess["mestre"] is True, "a marca não chegou à página — sem ela não há tarja"


def test_a_sessao_normal_NAO_nasce_marcada(com_codigo):
    """A outra ponta do guard acima: sem isto, um `mestre = true` fixo passaria
    nos dois testes e a tarja apareceria para todo motorista."""
    cadastrar(com_codigo, "MOT-2", "5547999990002", "BELTRANO")
    sid = msessao.abrir("MOT-2", esquema=com_codigo)
    token = msessao.emitir(1, sid)
    linha = pglocal.um("SELECT mestre FROM mot_sessoes WHERE id = %(i)s",
                       {"i": sid}, com_codigo)
    assert linha["mestre"] is False
    assert token


# -------------------------------------------------------------- pelas rotas

def test_a_lista_nao_sai_sem_o_codigo(com_codigo):
    """O guard mais importante deste arquivo. Uma rota que listasse antes de
    conferir seria, sozinha, a lista de quem dirige para esta empresa."""
    from api.main import app
    cadastrar(com_codigo, "MOT-1", "5547999990001", "FULANO DE TAL")
    c = TestClient(app)

    r = c.post("/api/motorista/mestre/motoristas", json={})
    assert r.status_code >= 400
    assert "FULANO" not in r.text

    r = c.post("/api/motorista/mestre/motoristas", json={"codigo": "chute"})
    assert r.status_code >= 400
    assert "FULANO" not in r.text


def test_entrar_confere_o_codigo_DE_NOVO(com_codigo):
    """São duas rotas independentes: uma que confiasse na anterior abriria
    sessão sem segredo nenhum para quem a chamasse direto."""
    from api.main import app
    mid = cadastrar(com_codigo, "MOT-1", "5547999990001", "FULANO")
    c = TestClient(app)
    r = c.post("/api/motorista/mestre/entrar",
               json={"codigo": "chute", "motorista": mid})
    assert r.status_code >= 400
    assert msessao.COOKIE not in r.cookies


def test_a_recusa_e_a_MESMA_para_codigo_errado_e_para_teto(com_codigo):
    """Textos diferentes diriam a quem tenta se vale a pena continuar — e
    "acesso não configurado" diria que não há nada a descobrir aqui."""
    from api.main import app
    c = TestClient(app)
    textos = set()
    for _ in range(mm.MAX_TENTATIVAS_HORA + 2):
        r = c.post("/api/motorista/mestre/motoristas",
                   json={"codigo": "errado"})
        textos.add(r.json().get("mensagem"))
    assert textos == {mm.RECUSA}


def test_a_sessao_mestre_le_a_operacao_de_UM_motorista_so(com_codigo):
    """O ponto inteiro do desenho: não existe rota que devolva vários. A sessão
    mestre é a sessão daquele motorista, com aviso na tela."""
    from api.main import app
    mid = cadastrar(com_codigo, "MOT-1", "5547999990001", "FULANO")
    c = TestClient(app)
    r = c.post("/api/motorista/mestre/entrar",
               json={"codigo": CODIGO, "motorista": mid})
    assert r.status_code == 200 and r.json()["mestre"] is True

    eu = c.get("/api/motorista/eu")
    assert eu.status_code == 200
    d = eu.json()
    assert d["mestre"] is True and d["nome"] == "FULANO"
    # e ela continua sendo uma sessão de motorista: o painel segue fechado
    assert c.get("/api/auth/me").status_code in (401, 403)
