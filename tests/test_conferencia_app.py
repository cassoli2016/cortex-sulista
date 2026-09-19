# -*- coding: utf-8 -*-
"""Abrir o app de um motorista pelo painel — o poder, a porta e a trilha.

O que este arquivo guarda:

- **o poder nasce desligado**, inclusive para quem tem a tela da premiação: ver
  a régua e abrir a conta de alguém são autorizações diferentes;
- poder SÓ SE DÁ (`tirar` é recusado): tirar o que ninguém tem seria uma linha
  inerte no banco, lida como proteção por quem for conferir;
- a porta é o PODER, não a tela: quem tem `prem` e não tem o poder leva 403;
- a trilha tem NOME — é a razão inteira desta porta existir ao lado do código
  mestre, que registra "alguém que sabia o código";
- as duas portas abrem a MESMA sessão: curta, marcada como mestre, com tarja.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import acessos, auth, conferencia, pglocal

SENHA = "senha-de-teste-123"


# ───────────────────────────────────────────────── o poder, sozinho
def test_o_poder_NASCE_DESLIGADO():
    assert acessos.pode(conferencia.PODER, [], admin=False) is False
    assert acessos.pode(conferencia.PODER, [("prem", "liberar")], False) is False


def test_a_TELA_recebe_os_poderes():
    """O defeito de 18/09/2026: o servidor calculava os poderes a cada
    requisição e NÃO os mandava para a tela.

    `auth._payload_me` é uma lista de permissão escrita à mão — a única forma
    honesta de publicar sessão, porque copiar-e-apagar faria todo campo novo
    nascer VISÍVEL. O preço é que campo novo nasce INVISÍVEL, e essa metade não
    tem sintoma: `USER.poderes` chegava `undefined`, `gmaPodeConferir()` dava
    falso para todo mundo (administrador inclusive), o botão "Ver o app" nunca
    era desenhado, e a única porta que sobrava era o código mestre — que é
    exatamente o que ele veio substituir. Ninguém viu erro nenhum.
    """
    from api import auth
    sessao = _sessao_de_tela(poderes=[conferencia.PODER])
    payload = auth._payload_me(sessao)
    assert "poderes" in payload, (
        "a tela não recebe os poderes: o botão de conferir não será desenhado "
        "para ninguém, e ninguém verá erro nenhum")
    assert conferencia.PODER in payload["poderes"]
    # E QUEM NÃO TEM, NÃO RECEBE — sem isto o guard passaria com o payload
    # publicando a lista inteira de `PODERES` para qualquer um.
    assert auth._payload_me(_sessao_de_tela(poderes=[]))["poderes"] == []


def test_o_poder_que_a_TELA_lE_existe_no_registro():
    """A tela compara com a chave `poder.conferir_app` escrita à mão no
    JavaScript. String que descreve o CÓDIGO se confere CONTRA o código: se o
    registro for renomeado, o botão some calado em vez de dar erro."""
    import pathlib
    import re
    from api import acessos
    html = (pathlib.Path(__file__).resolve().parents[1] / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    achadas = set(re.findall(r"'(poder\.[a-z_]+)'", html))
    assert achadas, "nenhum poder citado no index.html — a varredura é vazia"
    for chave in achadas:
        assert chave in acessos.PODERES, (
            "%s está escrito na tela e não existe em acessos.PODERES" % chave)


def _sessao_de_tela(poderes):
    """Uma sessão com a FORMA que `_montar_sessao` produz — é dela que o
    payload da tela é recortado."""
    return {"id": 1, "nome": "Teste", "email": "t@sulista.local",
            "perfil": "Administrador", "perfil_id": 1, "admin": True,
            "telas": ["prem"], "deve_trocar_senha": False, "telefone": "",
            "cargo": "", "setor": "", "ramal": "", "foto_em": None,
            "cliente_cnpj_raiz": None, "pagina_inicial": None,
            "abas_tiradas": [], "simulacao": None, "poderes": list(poderes)}

def test_administrador_tem_todos_os_poderes():
    """Mesma regra das telas: inventar uma exceção aqui criaria dois modelos de
    acesso na mesma casa."""
    assert acessos.pode(conferencia.PODER, [], admin=True) is True
    assert acessos.poderes_do([], admin=True) == set(acessos.PODERES)


def test_o_poder_SO_SE_DA(tmp_path):
    ok, erro = acessos.validar(
        [{"chave": conferencia.PODER, "efeito": "tirar"}], ["prem"])
    assert ok is None and "só se dá" in erro
    ok, erro = acessos.validar(
        [{"chave": conferencia.PODER, "efeito": "liberar"}], ["prem"])
    assert ok == [(conferencia.PODER, "liberar")] and erro is None


def test_chave_desconhecida_continua_recusada():
    ok, erro = acessos.validar([{"chave": "poder.inventado",
                                 "efeito": "liberar"}], ["prem"])
    assert ok is None and "não é uma tela" in erro


def test_exigir_LEVANTA_em_vez_de_devolver_falso():
    """Uma função que respondesse "não pode" seria lida um dia num `if`
    distraído, e a rota passaria a abrir a conta de qualquer um."""
    with pytest.raises(conferencia.SemPoder):
        conferencia.exigir({"admin": False, "poderes": []})
    conferencia.exigir({"admin": False, "poderes": [conferencia.PODER]})
    conferencia.exigir({"admin": True, "poderes": []})


# ─────────────────────────────────────────────────── a porta, no ar
@pytest.fixture
def cli(esquema_pg, monkeypatch):
    from api import motorista
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(motorista, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        c.execute("INSERT INTO perfis(nome, descricao, admin, criado_em)"
                  " VALUES('Frota2','premiacao',0,%s)", (auth._agora(),))
        pid = c.execute("SELECT id FROM perfis WHERE nome='Frota2'").fetchone()["id"]
        c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,'prem')",
                  (pid,))
        for nome, email in (("Sem poder", "sem@sulista.local"),
                            ("Com poder", "com@sulista.local")):
            c.execute(
                "INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,"
                " deve_trocar_senha, criado_em) VALUES(%s,%s,%s,%s,1,0,%s)",
                (nome, email, auth._ph.hash(SENHA), pid, auth._agora()))
        uid = c.execute("SELECT id FROM usuarios WHERE email='com@sulista.local'"
                        ).fetchone()["id"]
        c.execute("INSERT INTO usuario_acessos(usuario_id, chave, efeito,"
                  " criado_em, criado_por) VALUES(%s,%s,'liberar',%s,'teste')",
                  (uid, conferencia.PODER, auth._agora()))
    pglocal.executar(
        "INSERT INTO mot_vinculos(motorista_codigo, nome, telefone, ativo,"
        " criado_em) VALUES('111','MOTORISTA UM','5547999990001',true,%s)",
        (auth._agora(),), esquema=esquema_pg)

    from api.main import app

    def entrar(email):
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"email": email, "senha": SENHA})
        assert r.status_code == 200, r.text
        return c
    return {"sem": entrar("sem@sulista.local"), "com": entrar("com@sulista.local"),
            "esquema": esquema_pg}


def test_quem_tem_a_TELA_mas_nao_o_PODER_leva_403(cli):
    for rota, corpo in (("/api/conferencia/motoristas", {}),
                        ("/api/conferencia/abrir", {"codigo": "111"})):
        r = cli["sem"].post(rota, json=corpo)
        assert r.status_code == 403, rota
        assert "concedido pessoa a pessoa" in r.json()["mensagem"]


def test_quem_tem_o_poder_lista_e_ABRE_com_trilha_no_nome_dele(cli):
    r = cli["com"].post("/api/conferencia/motoristas", json={})
    assert r.status_code == 200 and r.json()["total"] >= 1

    r = cli["com"].post("/api/conferencia/abrir", json={"codigo": "111"})
    assert r.status_code == 200, r.text
    assert r.json()["mestre"] is True and r.json()["nome"] == "MOTORISTA UM"
    # A TRILHA TEM NOME — é a razão desta porta existir.
    linhas = pglocal.query(
        "SELECT usuario, acao, detalhe FROM audit_log WHERE acao = %s",
        ("conferencia_app_abriu",), esquema=cli["esquema"])
    assert len(linhas) == 1
    assert linhas[0]["usuario"] == "com@sulista.local"
    assert "MOTORISTA UM" in linhas[0]["detalhe"]


def test_a_sessao_aberta_e_MESTRE_e_curta(cli):
    r = cli["com"].post("/api/conferencia/abrir", json={"codigo": "111"})
    assert r.status_code == 200
    assert r.json()["horas"] == conferencia.TTL_HORAS
    assert conferencia.TTL_HORAS <= 4, (
        "a janela da conferência pelo painel é curta de propósito: quem abre "
        "está no meio do expediente e vai esquecer")
    marcada = pglocal.query(
        "SELECT mestre FROM mot_sessoes WHERE motorista_codigo = '111'",
        esquema=cli["esquema"])
    assert marcada and all(x["mestre"] for x in marcada), (
        "sem a marca não há tarja, e sem tarja o print vira 'o app mostrou "
        "isso ao motorista'")


def test_quem_nunca_entrou_no_app_e_recusa_legivel(cli):
    r = cli["com"].post("/api/conferencia/abrir", json={"codigo": "999"})
    assert r.status_code == 409
    assert "ainda não entrou no aplicativo" in r.json()["mensagem"]


def test_sem_sessao_de_painel_e_401(cli):
    from api.main import app
    assert TestClient(app).post("/api/conferencia/abrir",
                                json={"codigo": "111"}).status_code == 401


def test_a_rota_NAO_fica_sob_api_gestao(cli):
    """`/api/gestao` é checado como ADMIN antes do mapeamento de telas, e o
    poder é concedido pessoa a pessoa — lá a porta nasceria só de admin."""
    import inspect

    from api import main
    fonte = inspect.getsource(main.conferencia_abrir)
    assert "/api/gestao" not in fonte
    assert auth.rota_sem_tela("/api/conferencia/abrir")


def test_o_catalogo_da_gestao_oferece_o_poder(cli):
    from api.acessos import catalogo_poderes
    cat = catalogo_poderes()
    assert [x["chave"] for x in cat] == [conferencia.PODER]
    assert "tarja" in cat[0]["explica"] and "registrada" in cat[0]["explica"]
