"""A tela de Integracoes e o modal de cada fornecedor, contra o index.html real.

Este arquivo era `tests/telemetria/test_credenciais_tela_e2e.py` e guardava a
aba Integracoes da Gestao. A aba deixou de existir: os cartoes viraram a tela
`integ`, e o ajuste passou a acontecer no modal do cartao. As garantias sao as
mesmas -- mudou onde se clica, nao o que se protege:

1. **O segredo entra e nao volta.** Nem no payload, nem no DOM depois de salvo,
   nem num campo preenchido "para o usuario conferir".
2. **A tela mostra um fornecedor, nao uma lista de campos.** So os campos do
   modo de autenticacao escolhido aparecem -- a Prolog aceita token OU Basic OU
   OAuth2, e desenhar os onze de uma vez fazia a tela parecer desconfigurada.

E uma terceira, que nasceu com o modal e e a que sustenta o desenho inteiro:

3. **Quem nao e administrador nao recebe formulario NEM valor.** A tela `integ`
   e de RBAC normal (quem opera precisa saber que a telemetria parou de chegar
   sem depender de um administrador). Se o detalhe de credencial vazasse para
   ela, a tela teria de virar de admin -- e a razao de ela existir separada da
   Gestao ia junto.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
OPERADOR = {**USUARIO, "admin": False, "perfil": "Operacao",
            "telas": ["integ"]}


# ------------------------------------------------ o detalhe de admin (cofre)

def campo(nome, rotulo, **kw):
    base = {"nome": nome, "rotulo": rotulo, "descricao": "descrição de " + nome,
            "segredo": True, "obrigatorio": True, "placeholder": "",
            "configurado": False, "mascarado": None, "origem": None,
            "atualizado_em": None}
    base.update(kw)
    return base


GOBRAX = {
    "chave": "gobrax", "nome": "Gobrax", "resumo": "Telemetria e premiação.",
    "alimenta": "Telemetria · Premiação", "aba": None,
    "estado": "ativa", "modo_ativo": "token", "falta": [],
    "modos": [{"chave": "token", "rotulo": "Token de API", "completo": True,
               "campos": [campo("GOBRAX_TOKEN", "Token de API", configurado=True,
                                mascarado="eyJh…kP74", origem="cofre",
                                atualizado_em="2026-08-19 15:00:00")]}],
    "ajustes": [],
}

PROLOG = {
    "chave": "prolog", "nome": "Prolog", "resumo": "Gestão de pneus.",
    "alimenta": "Pneus", "aba": None,
    "estado": "incompleta", "modo_ativo": "token", "falta": ["filiais"],
    "modos": [
        {"chave": "token", "rotulo": "Token de API", "completo": True,
         "campos": [campo("PROLOG_TOKEN", "Token de API", configurado=True,
                          mascarado="abcd…wxyz", origem="cofre")]},
        {"chave": "basic", "rotulo": "Usuário e senha", "completo": False,
         "campos": [campo("PROLOG_USUARIO", "Usuário", segredo=False),
                    campo("PROLOG_SENHA", "Senha")]},
        {"chave": "oauth", "rotulo": "OAuth2", "completo": False,
         "campos": [campo("PROLOG_CLIENT_ID", "client_id", segredo=False),
                    campo("PROLOG_CLIENT_SECRET", "client_secret")]},
    ],
    "ajustes": [campo("PROLOG_FILIAIS", "Filiais", segredo=False,
                      placeholder="12, 15"),
                campo("PROLOG_API_BASE_URL", "URL base", segredo=False,
                      obrigatorio=False, configurado=True, origem="cofre",
                      valor="https://prologapp.com/prolog")],
}

SMTP = {
    "chave": "smtp", "nome": "Servidor de e-mail (SMTP)",
    "resumo": "Envio de e-mail pelo CÓRTEX.", "alimenta": "Correio · Cobrança",
    "aba": "email", "estado": "ativa", "modo_ativo": "senha", "falta": [],
    "modos": [{"chave": "senha", "rotulo": "Senha", "completo": True,
               "campos": [campo("SMTP_SENHA", "Senha do servidor",
                                configurado=True, mascarado="••••",
                                origem="cofre")]}],
    "ajustes": [],
}

CREDENCIAIS = {"servicos": [GOBRAX, PROLOG, SMTP], "credenciais": []}


# ---------------------------------------- o panorama (o que pinta os cartoes)
#
# LITERAL, e nao derivado dos dicionarios acima. Ele representa o formato de
# OUTRA rota, com outro nivel de acesso -- montar um a partir do outro faria o
# teste provar que dois dublês concordam, e nao que a tela le o que o servidor
# manda. A regra da casa: entrada que representa formato externo e copia do
# real. O `_campo_publico` do servidor NAO tem `valor` nem `mascarado`, e e
# assim que ele chega aqui.

def publico(rotulo, configurado=True, obrigatorio=True, segredo=True):
    return {"rotulo": rotulo, "obrigatorio": obrigatorio,
            "configurado": configurado, "segredo": segredo}


PANORAMA = {"integracoes": [
    {"chave": "gobrax", "nome": "Gobrax", "resumo": "Telemetria e premiação.",
     "alimenta": "Telemetria · Premiação", "estado": "ok",
     "configuracao": {"estado": "ativa", "status": "ok", "falta": [],
                      "modo": "token", "modo_rotulo": "Token de API",
                      "regime": None,
                      "modos": [{"chave": "token", "rotulo": "Token de API",
                                 "completo": True,
                                 "campos": [publico("Token de API")]}],
                      "ajustes": []},
     "chegada": {"regime": "coleta", "status": "ok",
                 "detalhe": "última coleta há 12 min · 340 registros"},
     "cartao_saude": "Gobrax (telemetria)", "aba": None},
    {"chave": "prolog", "nome": "Prolog", "resumo": "Gestão de pneus.",
     "alimenta": "Pneus", "estado": "alerta",
     "configuracao": {"estado": "incompleta", "status": "alerta",
                      "falta": ["filiais"], "modo": "token",
                      "modo_rotulo": "Token de API", "regime": None,
                      "modos": [
                          {"chave": "token", "rotulo": "Token de API",
                           "completo": True,
                           "campos": [publico("Token de API")]},
                          {"chave": "basic", "rotulo": "Usuário e senha",
                           "completo": False,
                           "campos": [publico("Usuário", False, segredo=False),
                                      publico("Senha", False)]},
                          {"chave": "oauth", "rotulo": "OAuth2",
                           "completo": False,
                           "campos": [publico("client_id", False, segredo=False),
                                      publico("client_secret", False)]}],
                      "ajustes": [publico("Filiais", False, segredo=False),
                                  publico("URL base", True, obrigatorio=False,
                                          segredo=False)]},
     "chegada": {"regime": "coleta", "status": "alerta",
                 "detalhe": "sem coleta há 5 dias"},
     "cartao_saude": "Prolog (pneus)", "aba": None},
    {"chave": "smtp", "nome": "Servidor de e-mail (SMTP)",
     "resumo": "Envio de e-mail pelo CÓRTEX.", "alimenta": "Correio · Cobrança",
     "estado": "info",
     "configuracao": {"estado": "ativa", "status": "ok", "falta": [],
                      "modo": "senha", "modo_rotulo": "Senha", "regime": None,
                      "modos": [{"chave": "senha", "rotulo": "Senha",
                                 "completo": True,
                                 "campos": [publico("Senha do servidor")]}],
                      "ajustes": []},
     "chegada": {"regime": "sob_demanda", "status": "info",
                 "detalhe": "só se prova no envio; a falha aparece na fila do Correio"},
     "cartao_saude": None, "aba": "email"},
], "resumo": {"total": 3, "ok": 1, "atencao": 1, "sem_medicao": 0}}


DESLIGADA = {"integracoes": [
    {**PANORAMA["integracoes"][0], "estado": "info",
     "configuracao": {"estado": "desligada", "status": "info",
                      "falta": ["credencial de acesso (Token de API)"],
                      "modo": None, "modo_rotulo": None, "regime": None,
                      "modos": [{"chave": "token", "rotulo": "Token de API",
                                 "completo": False,
                                 "campos": [publico("Token de API", False)]}],
                      "ajustes": []},
     "chegada": {"regime": "sem_medicao", "status": "info",
                 "detalhe": "esta integração ainda não tem medição de chegada"}},
], "resumo": {"total": 1, "ok": 0, "atencao": 0, "sem_medicao": 1}}

GOBRAX_VAZIO = {"servicos": [
    {**GOBRAX, "estado": "desligada", "modo_ativo": None,
     "falta": ["credencial de acesso (Token de API)"],
     "modos": [{"chave": "token", "rotulo": "Token de API", "completo": False,
                "campos": [campo("GOBRAX_TOKEN", "Token de API")]}]}],
    "credenciais": []}


# ------------------------------------------------------------------ o harness

def _abrir(pg, base_url, quem=ADMIN, panorama=None, cofre=None):
    """Abre a tela `integ` com as DUAS rotas dublê, e devolve o que foi salvo.

    As duas, e nao uma: a tela se pinta com /api/integracoes (RBAC normal) e o
    formulario do modal vem de /api/gestao/credenciais (admin). Dublar so uma
    esconderia justamente a fronteira que este arquivo existe para guardar.
    """
    enviados = []

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = quem
        elif "/api/gestao/credenciais" in u:
            if route.request.method == "POST":
                enviados.append(json.loads(route.request.post_data))
                corpo = {"nome": "GOBRAX_TOKEN", "configurado": True,
                         "mascarado": "abcd…wxyz", "origem": "cofre"}
            else:
                corpo = cofre or CREDENCIAIS
        elif "/api/integracoes" in u:
            corpo = panorama or PANORAMA
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#integ")
    pg.wait_for_selector("#integ-lista .intcard", timeout=20000)
    return enviados, erros


def _modal(pg, chave, formulario=True):
    """Clica o cartao e espera o modal daquele fornecedor.

    `formulario` espera o campo aparecer, e nao so o modal abrir: o detalhe de
    admin vem de OUTRA rota e pode chegar depois da primeira pintura. Sem esta
    espera o teste mede a corrida, nao o comportamento -- e passaria ou
    falharia conforme a maquina do dia.
    """
    pg.click(f'.intcard-alvo[data-chave="{chave}"]')
    pg.wait_for_selector("#modalBg.aberto", timeout=5000)
    if formulario:
        pg.wait_for_selector("#modalBox .ges-cfg", timeout=5000)
    return pg.locator("#modalBox")


# ============================================================== os cartoes

def test_a_tela_abre_sem_erro_de_javascript(pagina):
    pg, base = pagina
    _, erros = _abrir(pg, base)
    assert erros == []


def test_um_cartao_por_fornecedor_com_o_semaforo_da_juncao(pagina):
    """O estado do cartao e o PIOR das duas metades. A Prolog esta com a
    credencial ok e a coleta parada ha cinco dias -- verde ali seria a tela
    dizendo que da para confiar no numero da tela de Pneus."""
    pg, base = pagina
    _abrir(pg, base)
    assert pg.locator("#integ-lista .intcard").count() == 3
    assert pg.locator('.intcard[data-chave="gobrax"].st-ok').count() == 1
    assert pg.locator('.intcard[data-chave="prolog"].st-alerta').count() == 1
    # o farol nao esta sozinho: o badge diz a mesma coisa por escrito
    assert "atenção" in pg.inner_text('.intcard[data-chave="prolog"]')


def test_quem_abre_o_modal_e_um_botao_de_verdade(pagina):
    """<div onclick> nao recebe Tab, nao dispara com Enter e nao se anuncia
    como coisa que abre um dialogo."""
    pg, base = pagina
    _abrir(pg, base)
    alvo = pg.locator('.intcard-alvo[data-chave="gobrax"]')
    assert alvo.evaluate("el => el.tagName") == "BUTTON"
    assert alvo.get_attribute("aria-haspopup") == "dialog"


def test_o_nome_acessivel_do_cartao_e_so_o_FORNECEDOR(pagina):
    """O caminho obvio -- o cartao inteiro ser um <button> -- faz o nome
    acessivel virar todo o texto de dentro, e quem usa leitor de tela ouve o
    semaforo, o resumo e o detalhe da coleta a cada tabulada. O botao envolve
    so o nome; o resto do cartao abre pelo ::after esticado."""
    pg, base = pagina
    _abrir(pg, base)
    alvo = pg.locator('.intcard-alvo[data-chave="prolog"]')
    assert alvo.inner_text().strip() == "Prolog"


def test_o_cartao_nao_aninha_bloco_dentro_de_botao(pagina):
    """<h3> e <p> dentro de <button> e HTML invalido -- <button> so aceita
    conteudo de frase. O navegador tolera, e a conta chega quando alguem mexe
    no CSS meses depois."""
    pg, base = pagina
    _abrir(pg, base)
    dentro = pg.eval_on_selector_all(
        ".intcard-alvo", "els => els.flatMap(e => "
        "[...e.querySelectorAll('h1,h2,h3,h4,p,div,ul,li')].map(x => x.tagName))")
    assert dentro == [], dentro


def test_clicar_no_corpo_do_cartao_tambem_abre(pagina):
    """O ::after esticado e o que mantem o cartao inteiro clicavel depois de o
    botao ter encolhido para caber so o nome.

    Clica o CARTAO, longe do nome, e nao o `.resumo` que esta debaixo da
    camada: mirar o elemento coberto faz o Playwright esperar 30 s por uma
    acionabilidade que nunca vem -- a camada interceptar e o comportamento
    certo, e o teste que reclama dela esta medindo a coisa errada.
    """
    pg, base = pagina
    _abrir(pg, base)
    cartao = pg.locator('.intcard[data-chave="prolog"]')
    caixa = cartao.bounding_box()
    cartao.click(position={"x": caixa["width"] - 20, "y": caixa["height"] - 20})
    pg.wait_for_selector("#modalBg.aberto", timeout=5000)
    assert "Prolog" in pg.inner_text("#modalBox .intm-cab")


def test_a_faixa_de_kpis_conta_as_integracoes(pagina):
    pg, base = pagina
    _abrir(pg, base)
    texto = pg.inner_text("#integ-kpis")
    assert "3" in texto and "Em dia" in texto and "atenção" in texto.lower()


# ================================================= o modal, para quem edita

def test_o_modal_traz_as_DUAS_metades_e_diz_de_onde_vem_cada_uma(pagina):
    """A juncao e a tela inteira. Sem nomear a origem da chegada, "sem coleta
    ha 5 dias" e mais um numero que pede confianca."""
    pg, base = pagina
    _abrir(pg, base)
    m = _modal(pg, "prolog")
    texto = m.inner_text()
    assert "falta filiais" in texto            # a metade da configuracao
    assert "sem coleta há 5 dias" in texto      # a metade da chegada
    assert "Prolog (pneus)" in texto            # de onde a chegada foi medida
    assert "Pneus" in texto                     # o que ela alimenta


def test_mostra_a_credencial_mascarada_e_a_origem(pagina):
    pg, base = pagina
    _abrir(pg, base)
    texto = _modal(pg, "gobrax").inner_text()
    assert "configurado" in texto
    assert "eyJh…kP74" in texto
    assert "salvo aqui na tela" in texto


def test_campo_do_token_nasce_vazio_e_e_do_tipo_password(pagina):
    """Nunca preencher o campo com o segredo — nem para o usuário conferir."""
    pg, base = pagina
    _abrir(pg, base)
    _modal(pg, "gobrax")
    campo_tok = pg.locator("#cred-GOBRAX_TOKEN")
    assert campo_tok.get_attribute("type") == "password"
    assert campo_tok.input_value() == ""


def test_nao_configurado_avisa_que_a_integracao_esta_desligada(pagina):
    pg, base = pagina
    _abrir(pg, base, panorama=DESLIGADA, cofre=GOBRAX_VAZIO)
    assert "não configurada nesta instalação" in pg.inner_text("#integ-lista")
    assert "não configurado" in _modal(pg, "gobrax").inner_text()


def test_salvar_envia_o_valor_e_limpa_o_campo(pagina):
    pg, base = pagina
    enviados, _ = _abrir(pg, base)
    _modal(pg, "gobrax")
    pg.fill("#cred-GOBRAX_TOKEN", "token-novo-de-teste-123456")
    pg.click("#integ-btn-gobrax")
    pg.wait_for_timeout(800)
    assert enviados and enviados[0]["valor"] == "token-novo-de-teste-123456"
    # o segredo nao pode ficar no DOM depois de enviado
    assert pg.input_value("#cred-GOBRAX_TOKEN") == ""


def test_salvar_sem_mexer_em_nada_nao_chama_a_api(pagina):
    pg, base = pagina
    enviados, _ = _abrir(pg, base)
    _modal(pg, "gobrax")
    pg.click("#integ-btn-gobrax")
    pg.wait_for_timeout(400)
    assert enviados == []
    assert "Nada mudou" in pg.inner_text("#integ-err-gobrax")


def test_so_os_campos_do_modo_ativo_aparecem(pagina):
    """A Prolog tem tres modos; o modal desenha o do modo em uso, nao os onze
    campos de uma vez."""
    pg, base = pagina
    _abrir(pg, base)
    _modal(pg, "prolog")
    assert pg.locator("#cred-PROLOG_TOKEN").count() == 1
    assert pg.locator("#cred-PROLOG_SENHA").count() == 0
    assert pg.locator("#cred-PROLOG_CLIENT_SECRET").count() == 0
    # ajuste vale para qualquer modo e fica sempre visivel
    assert pg.locator("#cred-PROLOG_FILIAIS").count() == 1


def test_trocar_de_modo_mostra_os_campos_e_avisa_da_precedencia(pagina):
    """O cliente usa o PRIMEIRO modo completo. Preencher o Basic com um token
    salvo nao troca nada — e sem o aviso o operador jura que configurou."""
    pg, base = pagina
    _abrir(pg, base)
    m = _modal(pg, "prolog")
    pg.click("#modalBox .integ-modos button:nth-child(2)")
    assert pg.locator("#cred-PROLOG_SENHA").count() == 1
    assert pg.locator("#cred-PROLOG_TOKEN").count() == 0
    assert "tem precedência" in m.inner_text()


def test_campo_de_configuracao_vem_preenchido_e_e_texto(pagina):
    """Mascarar uma URL base ou o id da filial so impede conferir o que esta
    valendo — configuracao nao e segredo."""
    pg, base = pagina
    _abrir(pg, base)
    _modal(pg, "prolog")
    url = pg.locator("#cred-PROLOG_API_BASE_URL")
    assert url.get_attribute("type") == "text"
    assert url.input_value() == "https://prologapp.com/prolog"


def test_so_o_campo_alterado_vai_para_a_api(pagina):
    pg, base = pagina
    enviados, _ = _abrir(pg, base)
    _modal(pg, "prolog")
    pg.fill("#cred-PROLOG_FILIAIS", "12, 15")
    pg.click("#integ-btn-prolog")
    pg.wait_for_timeout(800)
    assert [e["nome"] for e in enviados] == ["PROLOG_FILIAIS"]


def test_smtp_nao_repete_o_campo_de_senha_e_aponta_a_aba(pagina):
    """A senha do SMTP se edita na aba E-mail, junto com servidor e porta.
    Dois lugares para digitar a mesma senha e o que fazia salvar num e
    conferir no outro."""
    pg, base = pagina
    _abrir(pg, base)
    m = _modal(pg, "smtp", formulario=False)
    assert pg.locator("#cred-SMTP_SENHA").count() == 0
    assert "aba E-mail" in m.inner_text()


# ====================================== o modal, para quem NAO e administrador

def test_quem_nao_e_admin_NAO_recebe_formulario_nem_valor(pagina):
    """A fronteira que sustenta o desenho. Se o detalhe de credencial chegasse
    aqui, a tela teria de virar de administrador — e a razao de ela existir
    separada da Gestao (quem opera saber que a coleta parou) ia junto."""
    pg, base = pagina
    _abrir(pg, base, quem=OPERADOR)
    m = _modal(pg, "gobrax", formulario=False)
    texto = m.inner_text()
    assert pg.locator("#cred-GOBRAX_TOKEN").count() == 0, "formulário para não-admin"
    assert pg.locator("#integ-btn-gobrax").count() == 0, "botão de salvar para não-admin"
    assert "eyJh…kP74" not in texto, "o mascarado é do detalhe de admin"
    assert "Só administrador altera" in texto


def test_quem_nao_e_admin_ainda_ve_o_que_falta(pagina):
    """Ler o estado e o ponto da tela: sem isso ela vira um cadeado, e a
    pessoa volta a descobrir que a coleta parou pelo numero errado na tela de
    Pneus."""
    pg, base = pagina
    _abrir(pg, base, quem=OPERADOR)
    texto = _modal(pg, "prolog", formulario=False).inner_text()
    assert "falta filiais" in texto
    assert "sem coleta há 5 dias" in texto
    # os campos aparecem por NOME, com marca de preenchido — nunca com valor
    assert "Filiais" in texto and "Token de API" in texto
