# -*- coding: utf-8 -*-
"""A tela de login no navegador: o botão, a caixa de "lembrar" e o fluxo de
"esqueci minha senha".

POR QUE ESTE ARQUIVO EXISTE NO NAVEGADOR E NÃO NO TEXTO DO CSS. As duas regras
do login estavam escritas e certas, e mesmo assim a tela não era a que elas
descreviam: `.lg-btn` (0,1,0) perdia para `button.btn` (0,2,1) e
`.lg-lembrar` (0,1,0) perdia para `.lg-body label` (0,1,1). Ler o CSS não
mostra isso — só o navegador diz quem venceu (memória
`css-regra-que-perde-a-briga`). Por isso todo assert daqui sai do CSSOM, do
`getComputedStyle`, e não de um `in HTML`.

O sintoma no celular era o da foto que motivou o conserto: o rótulo "Entrar"
encostado na esquerda de um bloco escuro de largura inteira, e a caixinha de
"lembrar" como um quadrado laranja do tamanho de um dedo com o texto em negrito
de rótulo de campo.
"""
from __future__ import annotations

import json

CELULAR = {"width": 393, "height": 852}


def _abrir_login(pg, base_url, hash_="", mobile=False):
    """Login montado, com a API respondendo 401 (ninguém logado)."""
    if mobile:
        pg.set_viewport_size(CELULAR)
    pg.route("**/api/**", lambda r: r.fulfill(
        status=401, content_type="application/json", body="{}"))
    pg.goto(base_url + "/static/index.html" + hash_)
    pg.wait_for_selector("#loginOverlay:not(.oculto)", timeout=15000)
    return pg


def _estilo(pg, sel, *props):
    return pg.evaluate(
        """([s, ps]) => { const e=document.querySelector(s); if(!e) return null;
             const c=getComputedStyle(e); const o={};
             ps.forEach(p => o[p]=c.getPropertyValue(p)); return o; }""",
        [sel, list(props)])


# ---------------------------------------------------------------------------
# O botão Entrar
# ---------------------------------------------------------------------------

def test_o_rotulo_do_botao_fica_CENTRADO(pagina):
    """Era isto que fazia o botão parecer grande demais: ele tem a mesma altura
    dos campos, mas o rótulo encostado na esquerda de um bloco escuro de
    largura inteira lê-se como uma barra vazia."""
    pg, base_url = pagina
    _abrir_login(pg, base_url)
    st = _estilo(pg, "#lg-go", "justify-content", "display")
    assert st["justify-content"] == "center", st


def test_o_botao_nao_passa_da_altura_dos_campos(pagina):
    """Botão maior que o campo que ele confirma inverte a hierarquia da tela."""
    pg, base_url = pagina
    _abrir_login(pg, base_url)
    alturas = pg.evaluate("""() => ({
        btn: document.getElementById('lg-go').getBoundingClientRect().height,
        campo: document.getElementById('lg-senha').getBoundingClientRect().height })""")
    assert alturas["btn"] <= alturas["campo"] + 2, alturas


def test_no_celular_a_regra_do_login_VENCE_a_do_botao_generico(pagina):
    """O `@media(max-width:880px)` tem `button.btn{padding:8px 12px}` (0,2,1).
    A regra do login precisa ser mais específica que ele — senão o padding
    escrito aqui nunca vale, que era o caso."""
    pg, base_url = pagina
    _abrir_login(pg, base_url, mobile=True)
    st = _estilo(pg, "#lg-go", "padding-top", "justify-content", "font-size")
    assert st["justify-content"] == "center"
    assert st["padding-top"] == "10px", st


def test_o_botao_ocupa_a_largura_do_cartao_sem_estourar(pagina):
    pg, base_url = pagina
    _abrir_login(pg, base_url, mobile=True)
    m = pg.evaluate("""() => {
        const b=document.getElementById('lg-go').getBoundingClientRect();
        return {btn:b.width, corpo:document.querySelector('.lg-body').clientWidth,
                rolagem:document.documentElement.scrollWidth,
                tela:document.documentElement.clientWidth}; }""")
    assert m["btn"] <= m["corpo"] + 1, m
    assert m["rolagem"] <= m["tela"], "a tela de login rola para o LADO no celular"


# ---------------------------------------------------------------------------
# A linha "Lembrar meu e-mail"
# ---------------------------------------------------------------------------

def test_a_caixinha_nao_herda_o_estilo_de_campo_de_texto(pagina):
    """`.lg-body input` alcançava o checkbox e dava a ele padding e borda de
    campo de texto — daí o quadrado laranja enorme da foto."""
    pg, base_url = pagina
    _abrir_login(pg, base_url, mobile=True)
    st = _estilo(pg, "#lg-lembrar", "padding-top", "padding-left",
                 "border-top-width", "width", "height")
    assert st["padding-top"] == "0px" and st["padding-left"] == "0px", st
    assert st["border-top-width"] == "0px", st
    assert st["width"] == "17px" and st["height"] == "17px", st


def test_o_texto_do_lembrar_e_discreto_e_nao_rotulo_de_campo(pagina):
    """`.lg-body label` (0,1,1) vencia `.lg-lembrar` (0,1,0) e a linha saía em
    12px/600 com cor de título, competindo com os rótulos de verdade."""
    pg, base_url = pagina
    _abrir_login(pg, base_url, mobile=True)
    st = _estilo(pg, ".lg-lembrar", "font-weight", "font-size", "display",
                 "align-items")
    assert st["font-weight"] == "400", st
    assert st["font-size"] == "13px", st
    assert st["display"] == "flex" and st["align-items"] == "center", st


def test_a_linha_do_lembrar_cabe_no_celular_em_UMA_linha(pagina):
    """"neste computador" num telefone também era errado no conteúdo, não só
    no desenho — o texto foi para "neste aparelho", que vale nos dois."""
    pg, base_url = pagina
    _abrir_login(pg, base_url, mobile=True)
    m = pg.evaluate("""() => {
        const l=document.querySelector('.lg-lembrar');
        const r=l.getBoundingClientRect();
        const linha=parseFloat(getComputedStyle(l).lineHeight)||18;
        return {altura:r.height, linha:linha, texto:l.textContent.trim(),
                corpo:document.querySelector('.lg-body').clientWidth,
                larg:r.width}; }""")
    assert "neste aparelho" in m["texto"], m["texto"]
    assert m["altura"] <= m["linha"] + 8, m      # não quebrou em duas linhas
    assert m["larg"] <= m["corpo"] + 1, m


def test_o_lembrar_continua_marcando_e_desmarcando(pagina):
    """Estilo novo não pode ter trocado a caixinha por um enfeite."""
    pg, base_url = pagina
    _abrir_login(pg, base_url)
    assert pg.evaluate("() => document.getElementById('lg-lembrar').checked") is False
    pg.click(".lg-lembrar")
    assert pg.evaluate("() => document.getElementById('lg-lembrar').checked") is True


# ---------------------------------------------------------------------------
# Esqueci minha senha
# ---------------------------------------------------------------------------

def test_o_login_oferece_esqueci_minha_senha(pagina):
    pg, base_url = pagina
    _abrir_login(pg, base_url)
    assert pg.is_visible("button.lg-link")
    assert "Esqueci minha senha" in pg.inner_text("button.lg-link")


def test_pedir_o_link_manda_o_email_e_mostra_a_MESMA_resposta(pagina):
    """A tela conta a mesma história da API: não diz se o e-mail existe."""
    pg, base_url = pagina
    pedidos = []

    def rota(r):
        if "/api/auth/esqueci" in r.request.url:
            pedidos.append(json.loads(r.request.post_data))
            return r.fulfill(status=200, content_type="application/json",
                             body=json.dumps({"ok": True, "mensagem":
                                              "Se esse e-mail estiver cadastrado, "
                                              "enviamos as instrucoes."}))
        return r.fulfill(status=401, content_type="application/json", body="{}")

    pg.route("**/api/**", rota)
    pg.goto(base_url + "/static/index.html")
    pg.wait_for_selector("#loginOverlay:not(.oculto)", timeout=15000)
    pg.click("button.lg-link")
    pg.wait_for_selector("#lg-form", timeout=5000)
    pg.fill("#lg-email", "alguem@sulista.com.br")
    pg.click("#lg-go")
    pg.wait_for_function("() => (document.getElementById('lg-ok')||{}).textContent",
                         timeout=5000)
    assert pedidos == [{"email": "alguem@sulista.com.br"}]
    assert "estiver cadastrado" in pg.inner_text("#lg-ok")
    # o botão sai do caminho: reenviar por reflexo só gasta o freio da API
    assert not pg.is_visible("#lg-go")


def test_da_para_voltar_do_esqueci_para_o_login(pagina):
    pg, base_url = pagina
    _abrir_login(pg, base_url)
    pg.click("button.lg-link")
    # `state="attached"`: o #lg-ok nasce VAZIO, e wait_for_selector espera
    # VISIBILIDADE — esperar o padrao aqui daria timeout no elemento certo.
    pg.wait_for_selector("#lg-ok", state="attached", timeout=5000)
    pg.click(".lg-alt button.lg-link")
    pg.wait_for_selector("#lg-lembrar", timeout=5000)
    assert pg.is_visible("#lg-senha")


# ---------------------------------------------------------------------------
# O link do e-mail
# ---------------------------------------------------------------------------

def test_o_link_do_email_abre_a_tela_de_senha_nova(pagina):
    pg, base_url = pagina
    _abrir_login(pg, base_url, hash_="#redefinir=" + "a" * 43)
    assert pg.is_visible("#lg-conf")
    assert "senha nova" in pg.inner_text("#lg-box").lower()


def test_o_token_SAI_da_barra_de_endereco(pagina):
    """Link de uso único não pode ficar em histórico nem em favorito."""
    pg, base_url = pagina
    _abrir_login(pg, base_url, hash_="#redefinir=" + "b" * 43)
    assert "redefinir" not in pg.url, pg.url


def test_a_senha_nova_vai_com_o_token_do_fragmento(pagina):
    pg, base_url = pagina
    token = "c" * 43
    enviados = []

    def rota(r):
        if "/api/auth/redefinir" in r.request.url:
            enviados.append(json.loads(r.request.post_data))
            return r.fulfill(status=200, content_type="application/json",
                             body=json.dumps({"ok": True}))
        return r.fulfill(status=401, content_type="application/json", body="{}")

    pg.route("**/api/**", rota)
    pg.goto(base_url + "/static/index.html#redefinir=" + token)
    pg.wait_for_selector("#lg-conf", timeout=15000)
    pg.fill("#lg-senha", "senha-nova-456")
    pg.fill("#lg-conf", "senha-nova-456")
    pg.click("#lg-go")
    pg.wait_for_selector("#lg-lembrar", timeout=5000)
    assert enviados == [{"token": token, "senha_nova": "senha-nova-456"}]
    # NÃO entra sozinho: volta para o login, que é onde a pessoa confirma que
    # guardou a senha (o aparelho pode ser emprestado)
    assert pg.is_visible("#lg-senha") and pg.is_visible("#lg-lembrar")
    # o aviso sai no slot de SUCESSO; pintar o de erro de verde deixaria o
    # proximo erro de verdade em verde (lgErro so troca o texto)
    assert "Senha alterada" in pg.inner_text("#lg-ok")
    assert pg.inner_text("#lg-err").strip() == ""


def test_confirmacao_diferente_nao_chega_a_chamar_a_api(pagina):
    pg, base_url = pagina
    chamadas = []

    def rota(r):
        if "/api/auth/redefinir" in r.request.url:
            chamadas.append(1)
        return r.fulfill(status=401, content_type="application/json", body="{}")

    pg.route("**/api/**", rota)
    pg.goto(base_url + "/static/index.html#redefinir=" + "d" * 43)
    pg.wait_for_selector("#lg-conf", timeout=15000)
    pg.fill("#lg-senha", "senha-nova-456")
    pg.fill("#lg-conf", "outra-coisa-789")
    pg.click("#lg-go")
    pg.wait_for_function("() => (document.getElementById('lg-err')||{}).textContent",
                         timeout=5000)
    assert chamadas == []
    assert "confirma" in pg.inner_text("#lg-err").lower()


def test_hash_de_tela_normal_nao_vira_redefinicao(pagina):
    """O roteador da página é por hash: `#oc` não pode acionar o fluxo de
    senha, e um `#redefinir=` curto demais também não."""
    pg, base_url = pagina
    _abrir_login(pg, base_url, hash_="#redefinir=curto")
    assert pg.is_visible("#lg-lembrar"), "entrou no fluxo de senha com token inválido"
