"""O fluxo de "esqueci minha senha" — o único caminho de conta que começa SEM
sessão, e por isso o que mais precisa de guarda.

O que estes testes protegem não é "o botão funciona": é o conjunto de decisões
que separam um autoatendimento de senha de uma porta aberta. Cada um existe
por causa de um jeito conhecido de abusar do recurso:

  * pedir o link NÃO pode mexer na conta — senão qualquer pessoa que saiba um
    e-mail da empresa derruba o acesso de quem quiser, quantas vezes quiser;
  * a resposta é IDÊNTICA para e-mail que existe e para e-mail que não existe —
    senão a tela pública vira um verificador de quem trabalha na empresa;
  * o link serve UMA vez, expira, e a senha nova derruba as sessões abertas;
  * o pedido repetido tem freio, para não virar rajada de e-mail na caixa de
    outra pessoa.

O e-mail é dublê: o que se mede aqui é a REGRA, e nenhum teste manda mensagem.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from api import auth


# ---------------------------------------------------------------------------
# Cenário: um usuário real no schema do teste, e o correio substituído por uma
# caixa em memória. `enviados` é o que a pessoa receberia.
# ---------------------------------------------------------------------------
@pytest.fixture
def cena(esquema_pg, monkeypatch):
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        perfil = c.execute("SELECT id FROM perfis LIMIT 1").fetchone()["id"]
        uid = c.execute(
            """INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                    deve_trocar_senha, criado_em)
               VALUES(%s,%s,%s,%s,1,0,%s) RETURNING id""",
            ("Fulano de Tal", "fulano@sulista.com.br",
             auth._ph.hash("senha-antiga-123"), perfil, auth._agora()),
        ).fetchone()["id"]

    enviados: list[dict] = []

    class CorreioDuble:
        @staticmethod
        def enviar(email, nome, url_link, validade_min, **kw):
            enviados.append({"email": email, "nome": nome, "url": url_link,
                             "validade_min": validade_min})
            return {"ok": True}

    import api.correio.redefinir_senha as real
    monkeypatch.setattr(real, "enviar", CorreioDuble.enviar)
    monkeypatch.setattr(auth, "_url_painel", lambda: "https://cortex.exemplo")
    return {"uid": uid, "email": "fulano@sulista.com.br", "enviados": enviados}


class ReqFalso:
    """O mínimo que as rotas leem: IP do cliente e cabeçalhos."""
    def __init__(self, ip="203.0.113.9"):
        from starlette.datastructures import Headers
        self.headers = Headers({})
        self.client = type("C", (), {"host": ip})()
        self.url = type("U", (), {"scheme": "https"})()


def _corpo(resp) -> dict:
    import json
    return json.loads(resp.body)


def _pedir(email: str, req=None):
    """O pedido, e depois o que a resposta deixou agendado.

    O e-mail sai num `BackgroundTask`: o corpo vai primeiro e o SMTP roda
    depois, para o RELOGIO não contar o que o texto cala (SMTP leva segundos;
    e-mail inexistente voltaria na hora). Aqui a gente roda a tarefa à mão,
    que é o que o Starlette faz depois de escrever a resposta.
    """
    import asyncio
    r = auth.esqueci_senha({"email": email}, req or ReqFalso())
    if r.background:
        asyncio.run(r.background())
    return r


def _token_do_link(url: str) -> str:
    return url.split("#redefinir=", 1)[1]


def _senha_hash(uid: int) -> str:
    with auth._conn() as c:
        return c.execute("SELECT senha_hash FROM usuarios WHERE id=%s",
                         (uid,)).fetchone()["senha_hash"]


def _confere(uid: int, senha: str) -> bool:
    from argon2.exceptions import VerifyMismatchError
    try:
        return bool(auth._ph.verify(_senha_hash(uid), senha))
    except VerifyMismatchError:
        return False


# ---------------------------------------------------------------------------
# 1. O pedido não mexe na conta
# ---------------------------------------------------------------------------

def test_pedir_o_link_NAO_troca_a_senha_de_ninguem(cena):
    """A decisão que separa este recurso de uma negação de serviço: quem pede
    não muda nada. A senha antiga continua entrando."""
    _pedir(cena["email"])
    assert _confere(cena["uid"], "senha-antiga-123")
    assert len(cena["enviados"]) == 1


def test_o_email_sai_DEPOIS_da_resposta(cena):
    """A resposta ser igual no TEXTO não basta: mandar o e-mail antes de
    responder faria a chamada demorar os segundos do SMTP para quem existe e
    voltar na hora para quem não existe — o relógio contaria o que o texto
    cala. Por isso o envio é `BackgroundTask`."""
    import asyncio
    r = auth.esqueci_senha({"email": cena["email"]}, ReqFalso())
    assert cena["enviados"] == [], "o SMTP rodou ANTES de responder"
    assert r.background is not None
    asyncio.run(r.background())
    assert len(cena["enviados"]) == 1


def test_email_inexistente_nao_agenda_envio_nenhum(cena):
    """O caminho curto não pode ter tarefa pendurada: o que iguala o tempo é
    ninguém esperar pelo SMTP, nos dois lados."""
    r = auth.esqueci_senha({"email": "naoexiste@sulista.com.br"}, ReqFalso())
    assert r.background is None


def test_o_link_vai_no_FRAGMENTO_da_url(cena):
    """`#` não é enviado ao servidor: o token não entra no log do uvicorn nem
    no do Cloudflare. Em `?query` entraria nos dois."""
    _pedir(cena["email"])
    url = cena["enviados"][0]["url"]
    assert "#redefinir=" in url and "?" not in url


def test_o_email_do_link_nao_carrega_senha(cena):
    """O de boas-vindas leva senha provisória; este não pode levar nada que
    sirva para entrar sem abrir o link."""
    from api.correio import redefinir_senha as mod
    _assunto, texto, html = mod.montar("Fulano", "https://x/#redefinir=tok", 60)
    assert "senha provis" not in texto.lower()
    assert "senha atual continua" in texto.lower()
    assert "#redefinir=tok" in texto and "#redefinir=tok" in html


# ---------------------------------------------------------------------------
# 2. A resposta não revela quem existe
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("email", [
    "naoexiste@sulista.com.br",     # e-mail que não está cadastrado
    "fulano@sulista.com.br",        # e-mail que está
])
def test_a_resposta_e_a_MESMA_exista_ou_nao(cena, email):
    r = _pedir(email)
    assert r.status_code == 200
    assert _corpo(r) == {
        "ok": True,
        "mensagem": "Se esse e-mail estiver cadastrado, enviamos as instrucoes "
                    "para redefinir a senha. Confira a caixa de entrada e o spam.",
    }


def test_usuario_INATIVO_nao_recebe_link(cena):
    """Reativar conta é do administrador. Um link de senha não pode ser a
    porta de volta de quem foi tirado — e a tela não conta isso."""
    with auth._conn() as c:
        c.execute("UPDATE usuarios SET ativo=0 WHERE id=%s", (cena["uid"],))
    r = _pedir(cena["email"])
    assert r.status_code == 200
    assert cena["enviados"] == []


def test_falha_no_envio_nao_muda_a_resposta(cena, monkeypatch):
    """Dizer 'não consegui enviar' entregaria que o e-mail existe."""
    import api.correio.redefinir_senha as real
    monkeypatch.setattr(real, "enviar",
                        lambda *a, **k: {"ok": False, "erro": "SMTP fora"})
    r = _pedir(cena["email"])
    assert r.status_code == 200 and _corpo(r)["ok"] is True


# ---------------------------------------------------------------------------
# 3. O token: uso único, prazo, e o que ele derruba
# ---------------------------------------------------------------------------

def test_o_link_troca_a_senha_e_derruba_as_sessoes(cena):
    _pedir(cena["email"])
    token = _token_do_link(cena["enviados"][0]["url"])
    with auth._conn() as c:
        ver_antes = c.execute("SELECT token_ver FROM usuarios WHERE id=%s",
                              (cena["uid"],)).fetchone()["token_ver"]

    r = auth.redefinir_senha({"token": token, "senha_nova": "senha-nova-456"},
                             ReqFalso())
    assert r.status_code == 200
    assert _confere(cena["uid"], "senha-nova-456")
    assert not _confere(cena["uid"], "senha-antiga-123")
    with auth._conn() as c:
        u = c.execute("SELECT token_ver, deve_trocar_senha FROM usuarios WHERE id=%s",
                      (cena["uid"],)).fetchone()
    # cookie emitido antes deixa de valer: conta perdida derruba quem está dentro
    assert u["token_ver"] == ver_antes + 1
    # a senha foi ESCOLHIDA pela pessoa, não é provisória: não pede troca
    assert u["deve_trocar_senha"] == 0


def test_o_link_serve_UMA_vez(cena):
    _pedir(cena["email"])
    token = _token_do_link(cena["enviados"][0]["url"])
    auth.redefinir_senha({"token": token, "senha_nova": "senha-nova-456"}, ReqFalso())
    r = auth.redefinir_senha({"token": token, "senha_nova": "outra-senha-789"},
                             ReqFalso())
    assert r.status_code == 409          # recusa legível, não 5xx
    assert not _confere(cena["uid"], "outra-senha-789")


def test_pedido_novo_MATA_o_link_anterior(cena):
    """Dois e-mails na caixa não podem virar duas chaves vivas depois que uma
    foi usada — senão o link velho reabre a conta."""
    _pedir(cena["email"])
    _pedir(cena["email"])
    velho = _token_do_link(cena["enviados"][0]["url"])
    novo = _token_do_link(cena["enviados"][1]["url"])
    auth.redefinir_senha({"token": novo, "senha_nova": "senha-nova-456"}, ReqFalso())
    r = auth.redefinir_senha({"token": velho, "senha_nova": "invadida-000"},
                             ReqFalso())
    assert r.status_code == 409
    assert not _confere(cena["uid"], "invadida-000")


def test_link_EXPIRADO_nao_vale(cena):
    _pedir(cena["email"])
    token = _token_do_link(cena["enviados"][0]["url"])
    passado = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    with auth._conn() as c:
        c.execute("UPDATE senha_reset SET expira_em=%s WHERE usuario_id=%s",
                  (passado, cena["uid"]))
    r = auth.redefinir_senha({"token": token, "senha_nova": "senha-nova-456"},
                             ReqFalso())
    assert r.status_code == 409
    assert _confere(cena["uid"], "senha-antiga-123")


def test_token_inventado_nao_vale(cena):
    r = auth.redefinir_senha({"token": "x" * 43, "senha_nova": "senha-nova-456"},
                             ReqFalso())
    assert r.status_code == 409


def test_o_token_NAO_e_gravado_em_texto(cena):
    """Quem lê a tabela (backup, dump) não pode entrar na conta de ninguém."""
    import hashlib
    _pedir(cena["email"])
    token = _token_do_link(cena["enviados"][0]["url"])
    with auth._conn() as c:
        guardado = c.execute("SELECT token_hash FROM senha_reset WHERE usuario_id=%s",
                             (cena["uid"],)).fetchone()["token_hash"]
    assert guardado != token
    assert guardado == hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_senha_curta_NAO_queima_o_link(cena):
    """Errar o mínimo de caracteres não pode obrigar a pessoa a pedir outro
    e-mail: o token só é consumido quando a senha é aceita."""
    _pedir(cena["email"])
    token = _token_do_link(cena["enviados"][0]["url"])
    r = auth.redefinir_senha({"token": token, "senha_nova": "curta"}, ReqFalso())
    assert r.status_code == 422
    r2 = auth.redefinir_senha({"token": token, "senha_nova": "agora-vale-123"},
                              ReqFalso())
    assert r2.status_code == 200
    assert _confere(cena["uid"], "agora-vale-123")


def test_redefinir_LIBERA_a_conta_bloqueada_por_tentativas(cena):
    """Quem acabou de provar que lê o e-mail da conta não continua trancado do
    lado de fora esperando o bloqueio passar."""
    futuro = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    with auth._conn() as c:
        c.execute("UPDATE usuarios SET falhas=5, bloqueado_ate=%s WHERE id=%s",
                  (futuro, cena["uid"]))
    _pedir(cena["email"])
    token = _token_do_link(cena["enviados"][0]["url"])
    auth.redefinir_senha({"token": token, "senha_nova": "senha-nova-456"}, ReqFalso())
    with auth._conn() as c:
        u = c.execute("SELECT falhas, bloqueado_ate FROM usuarios WHERE id=%s",
                      (cena["uid"],)).fetchone()
    assert u["falhas"] == 0 and u["bloqueado_ate"] is None


# ---------------------------------------------------------------------------
# 4. Freio de rajada
# ---------------------------------------------------------------------------

def test_freio_de_pedidos_repetidos_na_mesma_hora(cena):
    """Sem freio, um formulário público vira uma máquina de encher a caixa de
    entrada de outra pessoa. O freio não conta isso a quem pediu."""
    for _ in range(auth._RESET_MAX_POR_HORA + 2):
        r = _pedir(cena["email"])
        assert r.status_code == 200
    assert len(cena["enviados"]) == auth._RESET_MAX_POR_HORA


def test_pedido_antigo_nao_conta_no_freio(cena):
    """A janela é de UMA hora: quem pediu ontem não fica trancado hoje."""
    for _ in range(auth._RESET_MAX_POR_HORA):
        _pedir(cena["email"])
    ontem = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    with auth._conn() as c:
        c.execute("UPDATE senha_reset SET criado_em=%s WHERE usuario_id=%s",
                  (ontem, cena["uid"]))
    _pedir(cena["email"])
    assert len(cena["enviados"]) == auth._RESET_MAX_POR_HORA + 1


# ---------------------------------------------------------------------------
# 5. Trilha e porta de entrada
# ---------------------------------------------------------------------------

def test_tudo_entra_no_audit_log(cena):
    """Regra da casa (CLAUDE.md §8): toda escrita entra na trilha."""
    _pedir(cena["email"])
    token = _token_do_link(cena["enviados"][0]["url"])
    auth.redefinir_senha({"token": token, "senha_nova": "senha-nova-456"}, ReqFalso())
    with auth._conn() as c:
        acoes = [r["acao"] for r in c.execute(
            "SELECT acao FROM audit_log ORDER BY id").fetchall()]
    assert "senha_esqueci" in acoes and "senha_redefinir" in acoes


def test_o_token_nao_aparece_na_trilha(cena):
    """Trilha com segredo dentro é pior que o e-mail."""
    _pedir(cena["email"])
    token = _token_do_link(cena["enviados"][0]["url"])
    with auth._conn() as c:
        linhas = c.execute("SELECT detalhe, alvo FROM audit_log").fetchall()
    assert all(token not in (r["detalhe"] or "") + (r["alvo"] or "") for r in linhas)


def test_as_duas_rotas_sao_publicas():
    """Elas TÊM de ser: por construção chegam de quem não tem sessão. O
    middleware é fail-closed, então esquecer isto daria 403 na tela de login."""
    assert "/api/auth/esqueci" in auth._PUBLICAS
    assert "/api/auth/redefinir" in auth._PUBLICAS
    assert auth._rota_publica("/api/auth/esqueci")
    assert auth._rota_publica("/api/auth/redefinir")
