"""O cadastro do certificado NA TELA — no navegador, e nao no texto do arquivo.

POR QUE ESTE ARQUIVO EXISTE, e nao um teste de string
=====================================================

A primeira versao destes guards lia o `index.html` procurando trechos:
`"senhaEl.value = ''" in corpo`. Sabotados, os tres ficaram VERDES --

  - trocar `if(senhaEl)` por `if(false)` deixa a string intacta;
  - a linha continua no arquivo mesmo dentro de um ramo morto.

Guard que le TEXTO-FONTE protege contra APAGAR, nao contra QUEBRAR. Aqui os
mesmos tres fatos sao afirmados no navegador: o formulario aparece (ou nao)
para quem deve, e a senha SAI do campo depois do envio.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
COMUM = {**USUARIO, "admin": False, "perfil": "Operacao",
         "telas": ["dfe"]}

CAIXAS = {
    "caixas": [
        {"cnpj": "76104397000123", "apelido": "FIL MTZ", "uf": "PR",
         "ultimo_nsu": "000000001144010", "max_nsu": "000000001144012",
         "falta": 2, "ultima_consulta": "2026-09-07T19:28:00-03:00",
         "idade_h": 1.0, "cstat": "138", "motivo": "Documento localizado",
         "parada": False,
         "certificado": {"cnpj": "76104397000123", "apelido": "FIL MTZ",
                         "tem_certificado": True, "valida_ate": "2026-09-29",
                         "dias": 22, "vencido": False, "erro": None},
         "documentos": {"total": 0, "pendentes": 0}},
        {"cnpj": "76104397000204", "apelido": "FIL S.B. DO CAMPO", "uf": "SP",
         "ultimo_nsu": "000000000000000", "max_nsu": None, "falta": None,
         "ultima_consulta": None, "idade_h": None, "cstat": None,
         "motivo": None, "parada": False,
         "certificado": {"cnpj": "76104397000204", "tem_certificado": False,
                         "valida_ate": None, "dias": None, "vencido": None,
                         "erro": None},
         "documentos": {"total": 0, "pendentes": 0}},
    ],
    "total": {"total": 0, "pendentes": 0, "nfe": 0, "cte": 0, "eventos": 0},
    "documentos": [],
}


def _abrir(pg, base_url, usuario, ao_cadastrar=None):
    """Abre a tela `dfe` com a sessao dada. `ao_cadastrar` responde ao POST."""
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo, status = usuario, 200
        elif "/api/gestao/dfe/certificado" in u:
            corpo, status = (ao_cadastrar or {"ok": True}), 200
        elif "/api/dfe" in u:
            corpo, status = CAIXAS, 200
        else:
            corpo, status = {}, 200
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#dfe")
    pg.wait_for_selector("#dfe-caixas tr", timeout=20000)
    return erros


# ------------------------------------------------- quem ve o formulario

def test_o_formulario_NAO_aparece_para_quem_nao_e_admin(pagina):
    """A tela e de RBAC normal -- quem opera precisa VER se a recolha esta
    viva. Trocar o certificado e outro ato: ele assina documento fiscal em nome
    da empresa."""
    pg, base_url = pagina
    erros = _abrir(pg, base_url, COMUM)
    assert not erros, erros
    assert pg.is_hidden("#dfe-cert-caixa"), (
        "o formulario de certificado apareceu para quem nao e administrador")


def test_o_formulario_aparece_para_o_administrador(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url, ADMIN)
    assert not erros, erros
    assert pg.is_visible("#dfe-cert-caixa")
    # e a lista de filiais sai das CAIXAS que a API devolveu, nao de uma lista
    # escrita no HTML: filial nova entra sozinha.
    opcoes = pg.eval_on_selector_all(
        "#dfe-cert-cnpj option", "els => els.map(e => e.value)")
    assert opcoes == ["76104397000204", "76104397000123"], (
        "a filial SEM certificado tem de vir primeiro: e a que alguem abriu a "
        "tela para resolver. Veio: %s" % opcoes)


# ------------------------------------------------------ a senha sai do campo

def test_a_senha_SAI_do_campo_depois_de_cadastrar(pagina):
    """Ela nao volta da API, e deixa-la no campo cria uma copia viva num
    computador que fica destravado.

    NO NAVEGADOR, e nao no texto do arquivo: a versao anterior deste guard
    procurava `senhaEl.value = ''` no HTML e continuava verde com a linha
    dentro de um `if(false)`."""
    pg, base_url = pagina
    _abrir(pg, base_url, ADMIN,
           ao_cadastrar={"ok": True, "titular": "TRANSPORTADORA SULISTA S A",
                         "valida_ate": "2026-09-29", "dias": 22, "avisos": []})
    pg.set_input_files("#dfe-cert-arq", {
        "name": "76104397000123.pfx", "mimeType": "application/x-pkcs12",
        "buffer": b"\x30\x82fake"})
    pg.fill("#dfe-cert-senha", "senha-secreta")
    assert pg.input_value("#dfe-cert-senha") == "senha-secreta"

    pg.click("#dfe-cert-caixa button")
    pg.wait_for_function(
        "() => (document.getElementById('dfe-cert-msg')||{}).textContent"
        "        .includes('SULISTA')", timeout=15000)
    assert pg.input_value("#dfe-cert-senha") == "", (
        "a senha ficou no campo depois do cadastro")


def test_o_aviso_do_servidor_chega_na_tela(pagina):
    """Certificado vencendo nao pode ser aceito em silencio: quando ele vencer,
    a recolha para e nao ha erro que aponte para ca."""
    pg, base_url = pagina
    _abrir(pg, base_url, ADMIN,
           ao_cadastrar={"ok": True, "titular": "X", "valida_ate": "2026-09-29",
                         "dias": 22,
                         "avisos": ["Vence em 22 dia(s) (2026-09-29)."]})
    pg.set_input_files("#dfe-cert-arq", {
        "name": "x.pfx", "mimeType": "application/x-pkcs12", "buffer": b"\x30x"})
    pg.fill("#dfe-cert-senha", "s")
    pg.click("#dfe-cert-caixa button")
    pg.wait_for_function(
        "() => (document.getElementById('dfe-cert-msg')||{}).textContent"
        "        .includes('Vence em 22')", timeout=15000)


def test_sem_arquivo_ou_sem_senha_a_tela_RECUSA_antes_de_enviar(pagina):
    """Mandar pedido incompleto para uma rota que grava segredo e ruido no log
    do servidor -- e a mensagem util e a que aparece do lado de ca."""
    pg, base_url = pagina
    _abrir(pg, base_url, ADMIN)
    chamou = pg.evaluate("""() => {
        window.__post = 0;
        const orig = window.fetch;
        window.fetch = (u, o) => { if(String(u).includes('certificado')) window.__post++;
                                   return orig(u, o); };
        return true; }""")
    assert chamou
    pg.click("#dfe-cert-caixa button")
    pg.wait_for_function(
        "() => (document.getElementById('dfe-cert-msg')||{}).textContent"
        "        .includes('Escolha o arquivo')", timeout=15000)
    assert pg.evaluate("() => window.__post") == 0, (
        "enviou para o servidor mesmo sem arquivo e sem senha")


def test_o_formulario_JA_NASCE_escondido_no_HTML():
    """O `hidden` no HTML guarda o FLASH, e so ele.

    Os testes acima afirmam o estado DEPOIS que o script rodou -- e por isso
    nao veem a janela entre a primeira pintura e a decisao do `USER.admin`.
    Nessa janela, sem o `hidden`, quem nao e administrador ve o formulario de
    certificado aparecer e sumir.

    E teste de TEXTO-FONTE de proposito, e a excecao se justifica: a afirmacao
    e sobre o DOCUMENTO servido, nao sobre comportamento. O comportamento tem
    guard proprio logo acima -- este aqui cobre exatamente o que aquele nao
    alcanca, e sozinho nao bastaria (sabotar o `USER.admin` o deixa verde).
    """
    html = (Path(__file__).resolve().parents[2] / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    i = html.index('id="dfe-cert-caixa"')
    abertura = html[i:html.index(">", i) + 1]
    assert "hidden" in abertura, (
        "o formulario de certificado nasce VISIVEL no HTML: quem nao e "
        "administrador vai ve-lo piscar antes de o script escondê-lo. %s"
        % abertura)
