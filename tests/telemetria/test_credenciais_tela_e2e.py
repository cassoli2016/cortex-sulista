"""A aba Integrações da Gestão, contra o index.html real.

Duas coisas se protegem aqui:

1. **O segredo entra e não volta.** Nem no payload, nem no DOM depois de
   salvo, nem num campo preenchido "para o usuário conferir".
2. **A tela mostra um fornecedor, não uma lista de campos.** Só os campos do
   modo de autenticação escolhido aparecem — a Prolog aceita token OU Basic OU
   OAuth2, e desenhar os onze de uma vez fazia a tela inteira parecer
   desconfigurada.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}


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

PADRAO = {"servicos": [GOBRAX, PROLOG, SMTP], "credenciais": []}

VAZIO = {"servicos": [{**GOBRAX, "estado": "desligada", "modo_ativo": None,
                       "falta": ["credencial de acesso (Token de API)"],
                       "modos": [{"chave": "token", "rotulo": "Token de API",
                                  "completo": False,
                                  "campos": [campo("GOBRAX_TOKEN", "Token de API")]}]}],
         "credenciais": []}


def _abrir(pg, base_url, status=None):
    enviados = []

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = ADMIN
        elif "/api/gestao/credenciais" in u:
            if route.request.method == "POST":
                enviados.append(json.loads(route.request.post_data))
                corpo = {"nome": "GOBRAX_TOKEN", "configurado": True,
                         "mascarado": "abcd…wxyz", "origem": "cofre"}
            else:
                corpo = status or PADRAO
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#gestao")
    pg.wait_for_selector("#gtab-integracoes", timeout=20000)
    pg.click("#gtab-integracoes")
    pg.wait_for_selector("#ges-creds .badge", timeout=10000)
    return enviados, erros


def test_aba_abre_sem_erro_de_javascript(pagina):
    pg, base = pagina
    _, erros = _abrir(pg, base)
    assert erros == []


def test_mostra_a_credencial_mascarada_e_a_origem(pagina):
    pg, base = pagina
    _abrir(pg, base)
    texto = pg.inner_text("#ges-creds")
    assert "configurado" in texto
    assert "eyJh…kP74" in texto
    assert "salvo aqui na tela" in texto


def test_campo_do_token_nasce_vazio_e_e_do_tipo_password(pagina):
    """Nunca preencher o campo com o segredo — nem para o usuário conferir."""
    pg, base = pagina
    _abrir(pg, base)
    campo_tok = pg.locator("#cred-GOBRAX_TOKEN")
    assert campo_tok.get_attribute("type") == "password"
    assert campo_tok.input_value() == ""


def test_nao_configurado_avisa_que_a_integracao_esta_desligada(pagina):
    pg, base = pagina
    _abrir(pg, base, status=VAZIO)
    texto = pg.inner_text("#ges-creds")
    assert "não configurado" in texto
    assert "desligada" in texto


def test_salvar_envia_o_valor_e_limpa_o_campo(pagina):
    pg, base = pagina
    enviados, _ = _abrir(pg, base)
    pg.fill("#cred-GOBRAX_TOKEN", "token-novo-de-teste-123456")
    pg.click("#integ-btn-gobrax")
    pg.wait_for_timeout(600)
    assert enviados and enviados[0]["valor"] == "token-novo-de-teste-123456"
    # o segredo não pode ficar no DOM depois de enviado
    assert pg.input_value("#cred-GOBRAX_TOKEN") == ""


def test_salvar_sem_mexer_em_nada_nao_chama_a_api(pagina):
    pg, base = pagina
    enviados, _ = _abrir(pg, base)
    pg.click("#integ-btn-gobrax")
    pg.wait_for_timeout(400)
    assert enviados == []
    assert "Nada mudou" in pg.inner_text("#integ-err-gobrax")


def test_so_os_campos_do_modo_ativo_aparecem(pagina):
    """A Prolog tem três modos; a tela desenha o do modo em uso, não os onze
    campos de uma vez."""
    pg, base = pagina
    _abrir(pg, base)
    assert pg.locator("#cred-PROLOG_TOKEN").count() == 1
    assert pg.locator("#cred-PROLOG_SENHA").count() == 0
    assert pg.locator("#cred-PROLOG_CLIENT_SECRET").count() == 0
    # ajuste vale para qualquer modo e fica sempre visível
    assert pg.locator("#cred-PROLOG_FILIAIS").count() == 1


def test_trocar_de_modo_mostra_os_campos_e_avisa_da_precedencia(pagina):
    """O cliente usa o PRIMEIRO modo completo. Preencher o Basic com um token
    salvo não troca nada — e sem o aviso o operador jura que configurou."""
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#integ-prolog .integ-modos button:nth-child(2)")
    assert pg.locator("#cred-PROLOG_SENHA").count() == 1
    assert pg.locator("#cred-PROLOG_TOKEN").count() == 0
    assert "tem precedência" in pg.inner_text("#integ-prolog")


def test_campo_de_configuracao_vem_preenchido_e_e_texto(pagina):
    """Mascarar uma URL base ou o id da filial só impede conferir o que está
    valendo — configuração não é segredo."""
    pg, base = pagina
    _abrir(pg, base)
    url = pg.locator("#cred-PROLOG_API_BASE_URL")
    assert url.get_attribute("type") == "text"
    assert url.input_value() == "https://prologapp.com/prolog"


def test_so_o_campo_alterado_vai_para_a_api(pagina):
    pg, base = pagina
    enviados, _ = _abrir(pg, base)
    pg.fill("#cred-PROLOG_FILIAIS", "12, 15")
    pg.click("#integ-btn-prolog")
    pg.wait_for_timeout(600)
    assert [e["nome"] for e in enviados] == ["PROLOG_FILIAIS"]


def test_smtp_nao_repete_o_campo_de_senha_nesta_aba(pagina):
    """A senha do SMTP se edita na aba E-mail, junto com servidor e porta.
    Dois lugares para digitar a mesma senha é o que fazia salvar num e
    conferir no outro."""
    pg, base = pagina
    _abrir(pg, base)
    assert pg.locator("#cred-SMTP_SENHA").count() == 0
    assert "Configurar na aba E-mail" in pg.inner_text("#integ-smtp")


def test_resumo_conta_quantas_integracoes_estao_ativas(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert "2 de 3 integrações ativas" in pg.inner_text("#integResumo")
    # a incompleta é anunciada no topo, não só com um badge no meio da lista
    assert "Prolog" in pg.inner_text("#integAviso")
