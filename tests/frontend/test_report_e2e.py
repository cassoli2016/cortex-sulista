"""Botão Reportar e o modal, contra o index.html real.

Toda /api/** é interceptada: o teste cobre revelar o botão, validar o
formulário, o payload que sobe (agora um CHAMADO do Suporte, com os canais de
aviso) e o que acontece quando o servidor recusa.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

CONFIG = {
    "ativo": True,
    "canais": {"email": {"disponivel": True, "destino": "a***@sulista.local", "motivo": ""},
               "whatsapp": {"disponivel": False, "destino": "", "motivo": "cadastre seu telefone em Minha conta"}},
    "ultima_escolha": {"email": True, "whatsapp": True},
    "sou_suporte": False,
}


def _mockar(pg, ativo=True, resposta_report=None, status_report=200):
    """Intercepta a API. Devolve a lista onde cai o payload de cada POST."""
    enviados: list[dict] = []

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo, status = USUARIO, 200
        elif "/api/suporte/meus/config" in u:
            corpo, status = ({**CONFIG, "ativo": ativo} if ativo else {"ativo": False}), 200
        elif u.endswith("/api/suporte/meus/chamados"):
            try:
                enviados.append(json.loads(route.request.post_data or "{}"))
            except ValueError:
                enviados.append({})
            corpo = resposta_report or {"id": 42, "codigo": "SUP-2026-0042", "numero": "SUP-2026-0042",
                                        "url": "#sup?chamado=42", "status": "aberto"}
            status = status_report
        elif "/api/versao" in u:
            corpo, status = {"versao": "0.3.0", "rotulo": "CX-10/08/2026-v0.3.0",
                             "data": "2026-08-10"}, 200
        else:
            corpo, status = {}, 200
        route.fulfill(status=status, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    return enviados


def _abrir(pg, base, ativo=True, viewport=None, **kw):
    if viewport:
        pg.set_viewport_size(viewport)
    enviados = _mockar(pg, ativo=ativo, **kw)
    pg.goto(f"{base}/static/index.html#home")
    pg.wait_for_function("() => window.USER !== null", timeout=20000)
    return enviados


def _preencher(pg, titulo="Saldo não bate", desc="O total do card veio menor."):
    pg.click("#btnReport")
    pg.wait_for_selector("#rep-form")
    pg.fill("#rep-titulo", titulo)
    pg.fill("#rep-desc", desc)


# --------------------------------------------------------------- o botão

def test_botao_nao_existe_quando_o_servico_nao_responde(pagina):
    """Sem o serviço de suporte o botão não aparece — nada de botão morto."""
    pg, base = pagina
    _abrir(pg, base, ativo=False)
    pg.wait_for_timeout(300)
    assert pg.is_hidden("#btnReport")


def test_botao_aparece_para_todo_usuario_logado(pagina):
    """Não depende mais de GitHub: o chamado nasce no banco da casa."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    assert pg.get_attribute("#btnReport", "aria-label")


def test_botao_nao_cobre_a_barra_de_navegacao_no_celular(pagina):
    """A .bottomnav é fixa e ocupa exatamente este canto no mobile."""
    pg, base = pagina
    _abrir(pg, base, viewport={"width": 390, "height": 780})
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    fab = pg.eval_on_selector("#btnReport", "e=>e.getBoundingClientRect().bottom")
    nav = pg.eval_on_selector("#bottomnav", "e=>e.getBoundingClientRect().top")
    assert fab <= nav, f"o botão ({fab}) invade a bottomnav ({nav})"


def test_botao_some_no_painel_de_tv(pagina):
    """Mural não reporta nada e o botão ficaria por cima do mapa."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    pg.evaluate("document.body.classList.add('tvfull')")
    assert pg.eval_on_selector("#btnReport", "e=>getComputedStyle(e).display") == "none"


# --------------------------------------------------------------- o modal

def test_modal_abre_com_bug_pre_selecionado(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    pg.click("#btnReport")
    pg.wait_for_selector("#rep-form")
    assert "on" in (pg.get_attribute("#rep-t-bug", "class") or "")
    assert "Trava meu trabalho" in pg.inner_text("#rep-grav")


def test_gravidade_muda_de_rotulo_quando_e_melhoria_ou_duvida(pagina):
    """'Trava meu trabalho' não faz sentido num pedido de melhoria."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    pg.click("#btnReport")
    pg.wait_for_selector("#rep-form")
    pg.click("#rep-t-mel")
    texto = pg.inner_text("#rep-grav")
    assert "Muito importante" in texto and "Trava meu trabalho" not in texto
    pg.click("#rep-t-duv")
    assert "Estou travado" in pg.inner_text("#rep-grav")


def test_canais_mostram_o_destino_e_o_motivo_do_indisponivel(pagina):
    """O canal que não dá para usar aparece desligado COM o motivo — nunca
    some em silêncio (senão a pessoa espera um WhatsApp que não vem)."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    pg.click("#btnReport")
    pg.wait_for_selector("#rep-canais")
    assert pg.eval_on_selector("#rep-canais [data-canal=email]", "e=>e.checked") is True
    assert pg.eval_on_selector("#rep-canais [data-canal=whatsapp]", "e=>e.disabled") is True
    texto = pg.inner_text("#rep-canais")
    assert "a***@sulista.local" in texto and "cadastre seu telefone" in texto


def test_esc_nao_fecha_o_modal_com_texto_digitado(pagina):
    """O modal abre travado: fechar sem querer apagaria print e texto."""
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    _preencher(pg)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    assert pg.is_visible("#rep-form")


def test_recusa_envio_sem_titulo(pagina):
    pg, base = pagina
    enviados = _abrir(pg, base)
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    pg.click("#btnReport")
    pg.wait_for_selector("#rep-form")
    pg.fill("#rep-desc", "descrição sem título")
    pg.click("#rep-enviar")
    pg.wait_for_timeout(200)
    assert "título" in pg.inner_text("#m-err")
    assert enviados == [], "não pode chamar a API com o formulário incompleto"


# ---------------------------------------------------------------- o envio

def test_envio_manda_tela_filtros_versao_ambiente_e_canais(pagina):
    pg, base = pagina
    enviados = _abrir(pg, base)
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    _preencher(pg)
    pg.click("#rep-enviar")
    pg.wait_for_function("() => document.querySelector('.rep-ok')", timeout=5000)

    assert len(enviados) == 1
    p = enviados[0]
    assert p["tipo"] == "bug" and p["gravidade"] == "media"
    assert p["titulo"] == "Saldo não bate"
    assert p["canais"] == {"email": True, "whatsapp": False}   # WhatsApp indisponível não sobe marcado
    assert p["contexto"]["tela"] == "home"
    assert p["contexto"]["versao"] == "CX-10/08/2026-v0.3.0"
    assert p["contexto"]["navegador"]
    assert "x" in p["contexto"]["tela_px"]


def test_envio_bem_sucedido_mostra_o_numero_do_chamado_e_acompanhar(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    _preencher(pg)
    pg.click("#rep-enviar")
    pg.wait_for_selector(".rep-ok", timeout=5000)
    assert "SUP-2026-0042" in pg.inner_text(".rep-ok")
    assert "e-mail" in pg.inner_text(".rep-ok")          # diz por onde a resposta chega
    pg.click("#rep-acompanhar")
    pg.wait_for_function("() => location.hash.startsWith('#sup')", timeout=5000)


def test_falha_do_servidor_preserva_o_que_foi_digitado(pagina):
    """Reescrever texto e refazer o print é o custo de perder o formulário."""
    pg, base = pagina
    _abrir(pg, base, status_report=422,
           resposta_report={"erro": "parametro_invalido", "mensagem": "Escolha um tipo válido (401)."})
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    _preencher(pg)
    pg.click("#rep-enviar")
    pg.wait_for_function("() => document.querySelector('#m-err').textContent.length > 0",
                         timeout=5000)
    assert "401" in pg.inner_text("#m-err")
    assert pg.input_value("#rep-titulo") == "Saldo não bate"
    assert pg.eval_on_selector("#rep-enviar", "e=>e.disabled") is False


# -------------------------------------------------------- buffer de erros

def test_erro_de_javascript_viaja_junto_do_chamado(pagina):
    """É o que mais economiza tempo em bug de tela em branco."""
    pg, base = pagina
    enviados = _abrir(pg, base)
    pg.wait_for_selector("#btnReport:not([hidden])", timeout=5000)
    pg.evaluate("window.dispatchEvent(new ErrorEvent('error',"
                "{message:'x is not a function', filename:'/static/index.html', lineno:42}))")
    _preencher(pg)
    pg.click("#rep-enviar")
    pg.wait_for_selector(".rep-ok", timeout=5000)
    erros = enviados[0]["contexto"]["erros"]
    assert any("x is not a function" in e for e in erros)


def test_buffer_de_erros_guarda_no_maximo_dez(pagina):
    """Buffer sem teto viraria um POST gigante numa tela que erra em laço."""
    pg, base = pagina
    _abrir(pg, base)
    pg.evaluate("for(let i=0;i<25;i++) _repErro('erro '+i)")
    assert pg.evaluate("REPERR.length") == 10
    assert pg.evaluate("REPERR[9].includes('erro 24')")
