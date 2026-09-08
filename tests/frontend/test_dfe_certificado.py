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
    # `state="attached"` E NAO o padrao: `wait_for_selector` espera
    # VISIBILIDADE, e a tabela das caixas nasce dentro de uma aba FECHADA
    # desde que a tela passou de 900px. Esperar visibilidade ali e esperar para
    # sempre -- a armadilha esta escrita no CLAUDE.md.
    pg.wait_for_selector("#dfe-caixas tr", state="attached", timeout=20000)
    return erros


def _aba_admin(pg):
    """Abre a aba Administracao. O formulario mora nela desde que a tela passou
    de 900px e o excedente foi para sub-aba."""
    pg.click("#tabdfe-adm")
    pg.wait_for_selector("#dfe-cert-caixa", state="visible", timeout=10000)


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
    # E A ABA INTEIRA SOME. Um botao "Administração" que abre um painel vazio
    # promete alguma coisa e entrega nada -- quem clica acha que quebrou.
    assert pg.is_hidden("#tabdfe-adm"), (
        "a aba Administração aparece para quem nao e administrador")


def test_o_formulario_aparece_para_o_administrador(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url, ADMIN)
    assert not erros, erros
    assert pg.is_visible("#tabdfe-adm")
    _aba_admin(pg)
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
    _aba_admin(pg)
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
    _aba_admin(pg)
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
    _aba_admin(pg)
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


# ============================== a folha so aparece onde ela existe

def _com_documentos(pg, base_url, docs):
    dados = {**CAIXAS, "documentos": docs}

    def rota(route):
        u = route.request.url
        corpo = ADMIN if "/api/auth/me" in u else (dados if "/api/dfe" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(base_url + "/static/index.html#dfe")
    pg.wait_for_selector("#dfe-docs tr", state="attached", timeout=20000)


def test_evento_NAO_ganha_botao_de_folha(pagina):
    """Cancelamento e passagem nao tem representacao grafica propria -- eles se
    leem NA nota que alteraram. Um botao que sempre recusa ensina a ignorar
    botao."""
    pg, base_url = pagina
    _com_documentos(pg, base_url, [
        {"cnpj": "76104397000123", "nsu": "000000001144011", "tipo": "evento",
         "chave": "41260901178298000197550010001767921298714780",
         "emitente_nome": None, "emitente": "87124582000104", "valor": None,
         "emitido_em": "2026-09-07T19:50:32-03:00", "situacao": None,
         "completo": True, "descricao": "Registro de Passagem Automatico",
         "evento_tipo": "510630"}])
    linha = pg.inner_html("#dfe-docs tr:first-child")
    assert "/api/dfe/xml" in linha, "sumiu ate o XML"
    assert "/api/dfe/pdf" not in linha, "ofereceu folha para um EVENTO"
    # e a descricao do evento aparece: sem ela a linha e muda
    assert "Registro de Passagem" in linha


def test_a_NOTA_completa_ganha_XML_e_DANFE(pagina):
    pg, base_url = pagina
    _com_documentos(pg, base_url, [
        {"cnpj": "76104397000123", "nsu": "000000000000001", "tipo": "nfe",
         "chave": "41260912345678000199550010000012341000012349",
         "emitente_nome": "METALURGICA EXEMPLO LTDA",
         "emitente": "12345678000199", "valor": 4821.55,
         "emitido_em": "2026-09-05T14:32:00-03:00", "situacao": "100",
         "completo": True, "descricao": None, "evento_tipo": None}])
    linha = pg.inner_html("#dfe-docs tr:first-child")
    assert "/api/dfe/xml" in linha and "/api/dfe/pdf" in linha
    assert "DANFE" in linha


def test_o_RESUMO_nao_ganha_nem_XML_nem_folha(pagina):
    """Baixar um "XML" que e ficha de tres linhas e pior que nao ter botao."""
    pg, base_url = pagina
    _com_documentos(pg, base_url, [
        {"cnpj": "76104397000123", "nsu": "000000000000002", "tipo": "nfe",
         "chave": "41260912345678000199550010000012341000012348",
         "emitente_nome": "FORNECEDOR X", "emitente": "12345678000199",
         "valor": 100.0, "emitido_em": "2026-09-05T10:00:00-03:00",
         "situacao": "1", "completo": False, "descricao": None,
         "evento_tipo": None}])
    linha = pg.inner_html("#dfe-docs tr:first-child")
    assert "/api/dfe/xml" not in linha and "/api/dfe/pdf" not in linha
    assert "só resumo" in linha


# ================================ as abas: o </div> que rasga a tela

def test_as_TRES_abas_sao_IRMAS_e_nao_encaixadas():
    """O `</div>` QUE RASGOU AS ABAS, de novo -- e a casa ja tinha essa licao.

    Ao dividir a tela em sub-abas, a primeira versao esqueceu de fechar a aba
    das caixas: a de administracao abriu DENTRO dela, e a de documentos dentro
    dessa. O sintoma nao foi erro nenhum -- foi `abaTrocar` mostrando um painel
    cujo PAI continuava escondido, e o formulario "sumindo" para o
    administrador.

    A medida e a PROFUNDIDADE: as tres `.aba` do mesmo grupo tem de estar no
    mesmo nivel, e o bloco tem de fechar em zero.
    """
    import re
    html = (Path(__file__).resolve().parents[2] / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    i = html.index('<section class="view" id="view-dfe">')
    j = html.index('<section class="view" id="view-pecas">')

    prof, abas = 0, []
    for ln in html[i:j].splitlines():
        m = re.search(r'class="aba" data-abas="dfe" data-aba="(\w+)"', ln)
        if m:
            abas.append((m.group(1), prof))
        prof += len(re.findall(r"<div\b", ln)) - len(re.findall(r"</div>", ln))

    assert len(abas) == 3, "esperava tres abas na tela dfe, achei %s" % abas
    niveis = {p for _, p in abas}
    assert len(niveis) == 1, (
        "as abas estao ENCAIXADAS em vez de irmas: %s. `abaTrocar` mostra o "
        "painel, mas o PAI continua escondido." % abas)
    assert prof == 0, (
        "o bloco da tela nao fecha (%d div(s) em aberto) -- ele vai comer a "
        "tela seguinte" % prof)


def test_a_aba_que_nasce_aberta_e_a_de_DOCUMENTOS():
    """E a unica que alguem abre a tela para usar; as outras duas se olham
    quando algo esta errado."""
    html = (Path(__file__).resolve().parents[2] / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    i = html.index('<section class="view" id="view-dfe">')
    j = html.index('<section class="view" id="view-pecas">')
    bloco = html[i:j]
    for aba, escondida in (("docs", False), ("cx", True), ("adm", True)):
        marca = 'data-aba="%s" id="aba-dfe-%s"' % (aba, aba)
        k = bloco.index(marca)
        abertura = bloco[k:bloco.index(">", k) + 1]
        assert ("hidden" in abertura) is escondida, (
            "a aba %s nasce %s: %s"
            % (aba, "escondida" if escondida else "aberta", abertura))
