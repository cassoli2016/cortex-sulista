"""A área de modelos de mensagem, no navegador.

O backend tem testes próprios. O que só se prova AQUI é a regra que impede a
trilha de mentir:

**Com um modelo escolhido, a caixa de mensagem é PRÉVIA, não campo, e o POST
manda a CHAVE e os VALORES — nunca o texto.** Se a tela mandasse o texto junto
com a chave, a coluna "Modelo" da trilha registraria "veio do modelo revisado"
para uma mensagem que alguém reescreveu por cima. Nenhum teste de backend
distingue os dois casos: os dois chegam como um POST bem formado.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

CONFIG = {
    "ativo": True, "limite_dia": 60, "intervalo_seg": 5,
    "janela_inicio": "08:00", "janela_fim": "20:00",
    "assinatura": "Sulista Transportes", "atualizado_em": "2026-08-28 09:00:00",
    "credenciais_ok": True, "instancia": "3D2F…9077", "token_ok": True,
    "client_token_ok": True, "pronto": True, "dentro_da_janela": True,
    "limite_max": 500,
}
WHATS = {
    "config": CONFIG,
    "conexao": {"ok": True, "conectado": True, "celular": True, "erro": "",
                "configurado": True, "em": "2026-08-28 09:10:00"},
    "resumo": {"total": 0, "ok": 0, "falha": 0, "numeros": 0, "hoje": 3,
               "ultimo": None},
    "envios": [],
}

CTX_COBRANCA = {
    "chave": "cobranca", "rotulo": "Cobrança",
    "ajuda": "Aviso de título a vencer ou vencido.",
    "consumidores": [],
    "variaveis": [
        {"chave": "cliente", "rotulo": "Nome do cliente", "exemplo": "TUPY FUNDIÇÕES"},
        {"chave": "documento", "rotulo": "Número do documento/fatura", "exemplo": "123456"},
        {"chave": "vencimento", "rotulo": "Data de vencimento", "exemplo": "15/08/2026"},
    ],
}
CTX_LIVRE = {"chave": "livre", "rotulo": "Livre (sem variáveis)",
             "ajuda": "Mensagem avulsa, escrita inteira.",
             "consumidores": ["Gestão › WhatsApp"], "variaveis": []}

MODELOS = {
    "modelos": [
        {"id": 1, "chave": "cobranca-1o-aviso", "nome": "Cobrança — 1º aviso",
         "contexto": "cobranca", "contexto_rotulo": "Cobrança",
         "descricao": "Primeiro contato, tom amigável",
         "corpo": "Olá {{cliente}}, o título {{documento}} venceu em {{vencimento}}.",
         "variaveis": ["cliente", "documento", "vencimento"],
         "previa": "Olá TUPY FUNDIÇÕES, o título 123456 venceu em 15/08/2026.",
         "ativo": 1, "criado_em": "2026-08-28 09:00:00", "criado_por": "ana@sulista",
         "atualizado_em": "2026-08-28 09:00:00", "atualizado_por": "ana@sulista"},
        {"id": 2, "chave": "boas-vindas", "nome": "Boas-vindas",
         "contexto": "livre", "contexto_rotulo": "Livre (sem variáveis)",
         "descricao": "", "corpo": "Olá! Somos a Sulista.", "variaveis": [],
         "previa": "Olá! Somos a Sulista.", "ativo": 0,
         "criado_em": "2026-08-28 09:00:00", "criado_por": "ana@sulista",
         "atualizado_em": "2026-08-28 09:00:00", "atualizado_por": "ana@sulista"},
    ],
    "contextos": [CTX_LIVRE, CTX_COBRANCA],
    "limites": {"corpo": 3000, "texto": 4096},
}


def _abrir(pg, base_url, posts=None):
    """`posts` recolhe (url, corpo) de cada POST — é o que a tela MANDA."""
    def rota(route):
        u, req = route.request.url, route.request
        if req.method == "POST" and posts is not None:
            try:
                posts.append((u, json.loads(req.post_data or "{}")))
            except ValueError:                      # pragma: no cover
                posts.append((u, {}))
        if "/api/auth/me" in u:
            corpo = ADMIN
        elif "/whatsapp/modelos/previa" in u:
            # o servidor é quem monta o texto: o dublê devolve algo
            # reconhecível para o teste distinguir prévia de digitação
            enviados = json.loads(req.post_data or "{}")
            vals = enviados.get("valores") or {}
            corpo = {"erro": "", "variaveis": [],
                     "caracteres": len(enviados.get("corpo") or ""),
                     "texto": "PREVIA:" + json.dumps(vals, sort_keys=True,
                                                     ensure_ascii=False)}
        elif "/whatsapp/modelos" in u:
            corpo = MODELOS
        elif "/whatsapp/enviar" in u:
            corpo = {"ok": True, "enviados": 1, "falhas": 0, "resultados": []}
        elif "/gestao/whatsapp" in u:
            corpo = WHATS
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#gestao")
    pg.wait_for_selector("#gtab-whatsapp", timeout=20000)
    pg.click("#gtab-whatsapp")
    pg.wait_for_selector("#wa-mod-lista table", timeout=10000)
    return erros


# --------------------------------------------------------------------- lista

def test_a_aba_lista_os_modelos_sem_erro(pagina):
    pg, base = pagina
    assert _abrir(pg, base) == []
    corpo = pg.inner_text("#wa-mod-lista")
    assert "Cobrança — 1º aviso" in corpo
    assert "cobranca-1o-aviso" in corpo          # a chave aparece: é o contrato
    assert "2 modelos · 1 ligado" in pg.inner_text("#wa-mod-hint")


def test_contexto_sem_tela_que_o_dispare_diz_isso(pagina):
    """O catálogo declara contextos que ainda não têm consumidor. Escondê-lo
    faria o modelo parecer em operação quando é só texto pronto."""
    pg, base = pagina
    _abrir(pg, base)
    # `tbody` explícito: `tr:nth-child(1)` solto casa a linha do cabeçalho
    linha = pg.inner_text("#wa-mod-lista tbody tr:nth-child(1)")
    assert "sem tela ainda" in linha
    # o contexto 'livre' TEM consumidor e não leva o aviso
    assert "sem tela ainda" not in pg.inner_text("#wa-mod-lista tbody tr:nth-child(2)")


def test_modelo_desligado_nao_aparece_no_seletor_de_envio(pagina):
    pg, base = pagina
    _abrir(pg, base)
    opcoes = pg.inner_text("#wa-modelo")
    assert "Cobrança — 1º aviso" in opcoes
    assert "Boas-vindas" not in opcoes           # desligado
    assert "Sem modelo" in opcoes


# --------------------------------------------------------------------- envio

def _escolher_modelo(pg):
    pg.select_option("#wa-modelo", "cobranca-1o-aviso")
    pg.wait_for_selector("#wa-vars input[data-var]", timeout=5000)
    pg.wait_for_timeout(400)


def test_escolher_modelo_abre_um_campo_por_variavel(pagina):
    pg, base = pagina
    _abrir(pg, base)
    _escolher_modelo(pg)
    campos = pg.eval_on_selector_all("#wa-vars input[data-var]",
                                     "els=>els.map(e=>e.dataset.var)")
    assert campos == ["cliente", "documento", "vencimento"]
    # o rótulo é o do catálogo, não o nome cru da variável (o CSS o deixa em
    # caixa alta, então a comparação ignora caixa)
    assert "NOME DO CLIENTE" in pg.inner_text("#wa-vars").upper()
    # e o exemplo vira placeholder, não valor: exemplo preenchido sairia como
    # se fosse dado real se alguém não reparasse
    assert pg.get_attribute("#wav-cliente", "placeholder") == "TUPY FUNDIÇÕES"
    assert pg.input_value("#wav-cliente") == ""


def test_com_modelo_a_caixa_de_mensagem_fica_SO_LEITURA(pagina):
    """É o que impede a coluna 'Modelo' da trilha de mentir."""
    pg, base = pagina
    _abrir(pg, base)
    assert pg.eval_on_selector("#wa-msg", "e=>e.readOnly") is False
    _escolher_modelo(pg)
    assert pg.eval_on_selector("#wa-msg", "e=>e.readOnly") is True
    pg.select_option("#wa-modelo", "")
    pg.wait_for_timeout(200)
    assert pg.eval_on_selector("#wa-msg", "e=>e.readOnly") is False


def test_a_previa_vem_do_SERVIDOR_e_nao_e_montada_na_tela(pagina):
    pg, base = pagina
    _abrir(pg, base)
    _escolher_modelo(pg)
    pg.fill("#wav-cliente", "VOLVO")
    pg.wait_for_timeout(600)
    # o dublê devolve "PREVIA:<valores>" — se a tela montasse o texto sozinha,
    # a caixa teria o corpo do modelo substituído em JavaScript
    texto = pg.input_value("#wa-msg")
    assert texto.startswith("PREVIA:")
    assert '"cliente": "VOLVO"' in texto


def test_o_envio_manda_a_CHAVE_e_os_VALORES_nunca_o_texto(pagina):
    pg, base = pagina
    posts = []
    _abrir(pg, base, posts=posts)
    _escolher_modelo(pg)
    pg.fill("#wav-cliente", "VOLVO")
    pg.fill("#wav-documento", "998877")
    pg.fill("#wav-vencimento", "01/09/2026")
    pg.fill("#wa-tel", "(47) 99999-8888")
    pg.click("#wa-enviar")
    pg.wait_for_timeout(700)

    envio = [c for u, c in posts if u.endswith("/whatsapp/enviar")]
    assert envio, "o POST de envio não saiu"
    corpo = envio[0]
    assert corpo["modelo"] == "cobranca-1o-aviso"
    assert corpo["valores"] == {"cliente": "VOLVO", "documento": "998877",
                                "vencimento": "01/09/2026"}
    assert "mensagem" not in corpo


def test_sem_modelo_o_envio_volta_a_mandar_a_mensagem_escrita(pagina):
    pg, base = pagina
    posts = []
    _abrir(pg, base, posts=posts)
    pg.fill("#wa-tel", "(47) 99999-8888")
    pg.fill("#wa-msg", "Bom dia, sua carga saiu.")
    pg.click("#wa-enviar")
    pg.wait_for_timeout(700)
    corpo = [c for u, c in posts if u.endswith("/whatsapp/enviar")][0]
    assert corpo["mensagem"] == "Bom dia, sua carga saiu."
    assert "modelo" not in corpo


# -------------------------------------------------------------------- editor

def test_editor_lista_as_variaveis_do_contexto_e_insere_no_cursor(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.click("text=+ Novo modelo")
    pg.wait_for_selector("#mo-corpo", timeout=5000)
    pg.select_option("#mo-ctx", "cobranca")
    pg.wait_for_timeout(300)

    botoes = pg.eval_on_selector_all("#mo-vars button", "els=>els.map(e=>e.textContent)")
    assert botoes == ["{{cliente}}", "{{documento}}", "{{vencimento}}"]

    pg.fill("#mo-corpo", "Olá , tudo bem?")
    pg.eval_on_selector("#mo-corpo", "e=>{e.focus(); e.selectionStart=e.selectionEnd=4}")
    pg.click("#mo-vars button:has-text('{{cliente}}')")
    assert pg.input_value("#mo-corpo") == "Olá {{cliente}}, tudo bem?"


def test_contexto_livre_avisa_que_nao_tem_variavel(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.click("text=+ Novo modelo")
    pg.wait_for_selector("#mo-corpo", timeout=5000)
    pg.select_option("#mo-ctx", "livre")
    pg.wait_for_timeout(300)
    assert "não tem variáveis" in pg.inner_text("#mo-vars")
    # e diz quem já usa esse contexto hoje
    assert "Gestão › WhatsApp" in pg.inner_text("#mo-ctx-ajuda")


def test_a_chave_e_readonly_no_modelo_novo_e_editavel_no_existente(pagina):
    """No modelo novo ela é derivada do nome; num que já existe, mudá-la é
    mudança de contrato — possível, mas de propósito e com aviso."""
    pg, base = pagina
    _abrir(pg, base)
    pg.click("text=+ Novo modelo")
    pg.wait_for_selector("#mo-chave", timeout=5000)
    assert pg.get_attribute("#mo-chave", "readonly") is not None
    pg.click("#modalBox button:has-text('Cancelar')")

    pg.click("#wa-mod-lista tbody tr:nth-child(1) button:has-text('Editar')")
    pg.wait_for_selector("#mo-chave", timeout=5000)
    assert pg.get_attribute("#mo-chave", "readonly") is None
    assert pg.input_value("#mo-chave") == "cobranca-1o-aviso"
    assert "quebra qualquer rotina" in pg.inner_text("#modalBox")


def test_salvar_manda_o_modelo_inteiro(pagina):
    pg, base = pagina
    posts = []
    _abrir(pg, base, posts=posts)
    pg.click("text=+ Novo modelo")
    pg.wait_for_selector("#mo-corpo", timeout=5000)
    pg.select_option("#mo-ctx", "cobranca")
    pg.fill("#mo-nome", "Cobrança — 2º aviso")
    pg.fill("#mo-corpo", "Olá {{cliente}}, seguimos sem o pagamento.")
    pg.click("#mo-salvar")
    pg.wait_for_timeout(600)
    corpo = [c for u, c in posts if u.endswith("/whatsapp/modelos")][0]
    assert corpo["nome"] == "Cobrança — 2º aviso"
    assert corpo["contexto"] == "cobranca"
    assert corpo["ativo"] == 1
    assert "id" not in corpo                 # é criação, não edição
