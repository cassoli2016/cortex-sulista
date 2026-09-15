"""A tela PEDE o e-mail de acesso (14/09/2026), contra o index.html real.

Por 16 dias o servidor mandava o boas-vindas a quem pedisse e o formulário
de usuário não pedia: a caixa não existia, o payload não levava
`enviar_boas_vindas` e o `gesBvAviso()` procurava um elemento ausente — sem
erro nenhum, porque ele desistia calado. O guard da rota
(`tests/test_usuario_acesso_email.py`) mandava a chave à mão e passava. Este
aqui prova o que só a tela pode provar: que o pedido SAI dela.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO
from tests.frontend.test_acessos_e2e import _abrir


def _gestao(pg, base, gravadas=None):
    return _abrir(pg, base, quem=USUARIO, hash_="#gestao", gravadas=gravadas, espera="#ges-usr tr")


def _novo(pg, nome="Evelyn Teste", email="evelyn@exemplo.test"):
    pg.click("button:has-text('+ Novo usuário')")
    pg.wait_for_selector("#gu-bv", timeout=5000)
    pg.fill("#gu-nome", nome)
    pg.fill("#gu-email", email)
    # o perfil nasce em branco desde 15/09/2026 (antes, no administrador) e a
    # tela não manda cadastro sem ele: escolhe-se, como a pessoa faria
    pg.select_option("#gu-perfil", "2")


def _ultimo(gravadas, caminho):
    enviados = [c for u, c in gravadas if u == caminho]
    assert enviados, f"o POST para {caminho} não saiu"
    return enviados[-1]


def _responder_cadastro(pg, corpo):
    """A rota do cadastro com resposta própria; o resto segue o dublê comum
    (a registrada por último é avaliada primeiro)."""
    def rota(route):
        if route.request.method == "POST":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))
        else:
            route.fallback()
    pg.route("**/api/gestao/usuarios", rota)


def test_novo_usuario_nasce_com_o_email_MARCADO_e_o_pedido_vai(pagina):
    pg, base = pagina
    gravadas = []
    erros = _gestao(pg, base, gravadas)
    _novo(pg)
    assert pg.is_checked("#gu-bv")
    assert "gera uma forte" in pg.inner_text("#gu-bv-hint"), "o aviso do interruptor não foi escrito"
    pg.click("#modalBox button:has-text('Criar usuário')")
    pg.wait_for_timeout(400)
    corpo = _ultimo(gravadas, "/api/gestao/usuarios")
    assert corpo.get("enviar_boas_vindas") is True
    assert corpo["senha_temporaria"] == "", "em branco: quem gera a senha é o servidor"
    assert not erros, erros


def test_desmarcado_o_pedido_NAO_vai_e_o_aviso_pede_a_senha(pagina):
    pg, base = pagina
    gravadas = []
    _gestao(pg, base, gravadas)
    _novo(pg)
    pg.uncheck("#gu-bv")
    assert "digite a senha" in pg.inner_text("#gu-bv-hint")
    pg.fill("#gu-senha", "temporaria-123")
    pg.click("#modalBox button:has-text('Criar usuário')")
    pg.wait_for_timeout(400)
    corpo = _ultimo(gravadas, "/api/gestao/usuarios")
    assert "enviar_boas_vindas" not in corpo
    assert corpo["senha_temporaria"] == "temporaria-123"


def test_na_edicao_o_reenvio_nasce_DESMARCADO_e_so_vai_quando_pedido(pagina):
    """Reenviar TROCA a senha de quem já usa o sistema: marcado por padrão,
    todo "salvar o ramal" derrubaria o acesso de alguém."""
    pg, base = pagina
    gravadas = []
    _gestao(pg, base, gravadas)
    pg.click("#ges-usr tr:has-text('Beto Lima') button:has-text('Editar')")
    pg.wait_for_selector("#gu-bv", timeout=5000)
    assert not pg.is_checked("#gu-bv")
    pg.fill("#gu-ramal", "115")
    pg.click("#modalBox button:has-text('Salvar')")
    pg.wait_for_timeout(400)
    assert "enviar_boas_vindas" not in _ultimo(gravadas, "/api/gestao/usuarios/7")

    pg.wait_for_selector("#ges-usr tr", timeout=5000)
    pg.click("#ges-usr tr:has-text('Beto Lima') button:has-text('Editar')")
    pg.wait_for_selector("#gu-bv", timeout=5000)
    pg.check("#gu-bv")
    assert "senha atual deixa de valer" in pg.inner_text("#gu-bv-hint")
    pg.click("#modalBox button:has-text('Salvar')")
    pg.wait_for_timeout(400)
    assert _ultimo(gravadas, "/api/gestao/usuarios/7").get("enviar_boas_vindas") is True


def test_envio_que_falhou_MOSTRA_a_senha_para_quem_cadastrou(pagina):
    pg, base = pagina
    _gestao(pg, base, [])
    _responder_cadastro(pg, {"ok": True, "id": 9, "senha_temporaria": "Xk7pQ2wzAbcd!7",
                             "email": {"ok": False, "erro": "SMTP recusou"}})
    avisos = []
    pg.on("dialog", lambda d: (avisos.append(d.message), d.accept()))
    _novo(pg)
    pg.click("#modalBox button:has-text('Criar usuário')")
    pg.wait_for_timeout(400)
    assert avisos, "a falha do e-mail passou calada"
    assert "NÃO saiu" in avisos[0] and "SMTP recusou" in avisos[0]
    assert "Xk7pQ2wzAbcd!7" in avisos[0]


def test_envio_que_saiu_CONFIRMA_para_quem(pagina):
    """Sem confirmação, "mandei" e "não mandei" eram o mesmo modal fechando —
    e foi assim que ninguém percebeu por 16 dias."""
    pg, base = pagina
    _gestao(pg, base, [])
    _responder_cadastro(pg, {"ok": True, "id": 9, "email": {"ok": True, "erro": ""}})
    avisos = []
    pg.on("dialog", lambda d: (avisos.append(d.message), d.accept()))
    _novo(pg, email="evelyn@exemplo.test")
    pg.click("#modalBox button:has-text('Criar usuário')")
    pg.wait_for_timeout(400)
    assert avisos and "evelyn@exemplo.test" in avisos[0] and "enviado" in avisos[0]


# ───────────────────────────────────────────── o botão de reenvio (15/09) ──

def _responder_reenvio(pg, corpo, pedidos):
    """O POST do usuário 7 com resposta própria, guardando o que foi pedido."""
    def rota(route):
        if route.request.method == "POST":
            pedidos.append(route.request.post_data_json)
            route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))
        else:
            route.fallback()
    pg.route("**/api/gestao/usuarios/7", rota)


BOTAO = "#ges-usr tr:has-text('Beto Lima') button:has-text('Reenviar acesso')"


def test_o_botao_REENVIAR_ACESSO_pergunta_antes_e_so_manda_o_pedido(pagina):
    """Pedido de quem opera ("o João disse que não recebeu"). Reenviar troca a
    senha, então pergunta — e o pedido é SÓ o reenvio: nenhum campo do
    cadastro vai junto, para um clique não reescrever o que não se viu."""
    pg, base = pagina
    _gestao(pg, base, [])
    pedidos = []
    _responder_reenvio(pg, {"ok": True, "email": {"ok": True, "erro": ""}}, pedidos)
    avisos, decisao = [], {"aceitar": False}

    def dialogo(d):
        avisos.append((d.type, d.message))
        if d.type == "confirm" and not decisao["aceitar"]:
            d.dismiss()
        else:
            d.accept()
    pg.on("dialog", dialogo)
    pg.click(BOTAO)
    pg.wait_for_timeout(300)
    assert avisos and avisos[0][0] == "confirm", avisos
    assert "beto@exemplo.test" in avisos[0][1] and "senha" in avisos[0][1]
    assert pedidos == [], "cancelado, nada sai"
    decisao["aceitar"] = True
    pg.click(BOTAO)
    pg.wait_for_timeout(400)
    assert pedidos == [{"enviar_boas_vindas": True}], pedidos
    assert avisos[-1] == ("alert", "Acesso enviado por e-mail para beto@exemplo.test.")


def test_reenvio_que_falhou_diz_que_a_senha_JA_FOI_TROCADA_e_mostra_a_nova(pagina):
    pg, base = pagina
    _gestao(pg, base, [])
    _responder_reenvio(pg, {"ok": True, "senha_temporaria": "Nw4pQ2wzAbcd!9",
                            "email": {"ok": False, "erro": "SMTP recusou"}}, [])
    avisos = []
    pg.on("dialog", lambda d: (avisos.append(d.message), d.accept()))
    pg.click(BOTAO)
    pg.wait_for_timeout(400)
    ultimo = avisos[-1]
    assert "A senha foi trocada" in ultimo and "SMTP recusou" in ultimo
    assert "Nw4pQ2wzAbcd!9" in ultimo


def test_o_cadastro_do_usuario_tem_o_botao_e_o_modal_FICA_aberto(pagina):
    pg, base = pagina
    _gestao(pg, base, [])
    pedidos = []
    _responder_reenvio(pg, {"ok": True, "email": {"ok": True, "erro": ""}}, pedidos)
    pg.on("dialog", lambda d: d.accept())
    # cadastro NOVO não tem o que reenviar
    pg.click("button:has-text('+ Novo usuário')")
    pg.wait_for_selector("#gu-bv", timeout=5000)
    assert pg.locator("#modalBox button:has-text('Reenviar acesso')").count() == 0
    pg.evaluate("() => fecharModal()")
    pg.click("#ges-usr tr:has-text('Beto Lima') button:has-text('Editar')")
    pg.wait_for_selector("#gu-bv", timeout=5000)
    pg.fill("#gu-ramal", "115")
    pg.click("#modalBox button:has-text('Reenviar acesso por e-mail')")
    pg.wait_for_timeout(400)
    assert pedidos == [{"enviar_boas_vindas": True}], "o ramal digitado NÃO vai junto"
    # o formulário continua no DOM depois de fecharModal() — ler o campo não
    # prova nada; quem diz se o modal está aberto é a classe do fundo
    aberto = pg.evaluate("() => document.getElementById('modalBg').classList.contains('aberto')")
    assert aberto, "o modal tem de ficar ABERTO"
    assert pg.input_value("#gu-ramal") == "115", "e o que foi digitado não se perde"
