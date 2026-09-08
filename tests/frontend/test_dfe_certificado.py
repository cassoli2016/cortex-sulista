"""O cadastro do certificado NA TELA — no navegador, e nao no texto do arquivo.

ONDE ELE MORA, desde 08/09/2026: no modal do cartao **SEFAZ da tela
Integracoes**. Antes era uma sub-aba "Administração" dentro de Notas de
Entrada, e sair de la conserta duas coisas de uma vez:

  - Central de Documentos e tela de OPERACAO. Uma aba que so administrador enxerga
    dentro dela obrigava a esconder botao por perfil, e aba escondida e a que
    ninguem acha quando precisa;
  - o cartao da SEFAZ nas Integracoes PROMETIA um ajuste que nao existia: como
    ela nao esta no cofre de credenciais, `integAjusteHTML` nao achava a chave
    e o modal ficava em "carregando as configuracoes..." para sempre.

POR QUE ESTE ARQUIVO EXISTE, e nao um teste de string
=====================================================

A primeira versao destes guards lia o `index.html` procurando trechos:
`"senhaEl.value = ''" in corpo`. Sabotados, os tres ficaram VERDES --

  - trocar `if(senhaEl)` por `if(false)` deixa a string intacta;
  - a linha continua no arquivo mesmo dentro de um ramo morto.

Guard que le TEXTO-FONTE protege contra APAGAR, nao contra QUEBRAR. Aqui os
mesmos fatos sao afirmados no navegador: o formulario aparece (ou nao) para
quem deve, e a senha SAI do campo depois do envio.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
COMUM = {**USUARIO, "admin": False, "perfil": "Operacao",
         "telas": ["dfe", "integ"]}

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

# O CARTAO DA SEFAZ COMO O SERVIDOR O MANDA -- copiado da saida de
# `api.sefaz.painel.cartao_de_integracao()`, e nao montado a partir dela. Duble
# que se deriva do codigo testado nao testa o codigo: sabotar o cartao sabotaria
# junto o que o teste fabrica, e ele seguiria verde. Note o que NAO ha aqui:
# `cartao_saude` e `aba` nao existem no cartao da SEFAZ, e e assim que ele chega
# na tela.
SEFAZ = {
    "chave": "sefaz", "nome": "SEFAZ (recolha de NF)",
    "resumo": ("As notas fiscais emitidas CONTRA a Sulista, e os eventos "
               "delas, direto do serviço nacional de Distribuição de DFe. "
               "É a única fonte que não depende de o fornecedor mandar o "
               "XML por e-mail — e o XML é a obrigação de guarda de cinco "
               "anos."),
    "alimenta": "Central de Documentos", "estado": "alerta",
    "configuracao": {"estado": "incompleta", "status": "alerta",
                     "falta": ["certificado A1 de 9 das 10 filiais"],
                     "modo": "certificado A1", "regime": None},
    "chegada": {"regime": "coleta", "status": "alerta",
                "detalhe": "1 de 10 filial(is) com certificado · "
                           "510 documento(s) recolhido(s)"},
}

PANORAMA = {"integracoes": [SEFAZ],
            "resumo": {"total": 1, "ok": 0, "atencao": 1, "sem_medicao": 0}}

# O que `/api/gestao/dfe/filiais` devolve: a saida de `painel.certificados()`.
FILIAIS = {"filiais": [
    {"cnpj": "76104397000123", "apelido": "FIL MTZ", "tem_certificado": True,
     "valida_ate": "2026-09-29", "dias": 22, "vencido": False, "erro": None,
     "titular": "TRANSPORTADORA SULISTA S A"},
    {"cnpj": "76104397000204", "apelido": "FIL S.B. DO CAMPO",
     "tem_certificado": False, "valida_ate": None, "dias": None,
     "vencido": None, "erro": None},
]}


def _abrir(pg, base_url, usuario, ao_cadastrar=None, filiais=None):
    """Abre a tela `integ` com a sessao dada. `ao_cadastrar` responde ao POST."""
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo, status = usuario, 200
        elif "/api/gestao/dfe/certificado" in u:
            corpo, status = (ao_cadastrar or {"ok": True}), 200
        elif "/api/gestao/dfe/filiais" in u:
            corpo, status = (FILIAIS if filiais is None else filiais), 200
        elif "/api/integracoes" in u:
            corpo, status = PANORAMA, 200
        elif "/api/dfe" in u:
            corpo, status = CAIXAS, 200
        else:
            corpo, status = {}, 200
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#integ")
    pg.wait_for_selector('#integ-lista .intcard[data-chave="sefaz"]',
                         timeout=20000)
    return erros


def _modal_sefaz(pg, com_formulario=True):
    """Abre o modal do cartao da SEFAZ — o lugar do formulario."""
    pg.click('.intcard-alvo[data-chave="sefaz"]')
    pg.wait_for_selector("#modalBg.aberto", timeout=5000)
    if com_formulario:
        # `#dfe-cert-caixa` e montado pelo JS junto com o modal; a lista de
        # filiais chega DEPOIS, por outra rota. Esperar o `option` de verdade e
        # o que separa medir o comportamento de medir a corrida.
        pg.wait_for_selector("#dfe-cert-caixa", state="visible", timeout=10000)
        pg.wait_for_function(
            "() => (document.querySelectorAll('#dfe-cert-cnpj option')||[])"
            "        .length > 0 && !document.querySelector"
            "        ('#dfe-cert-cnpj option').textContent.includes('carregando')",
            timeout=10000)


# ------------------------------------------------- quem ve o formulario

def test_o_formulario_NAO_aparece_para_quem_nao_e_admin(pagina):
    """A tela Integracoes e de RBAC normal -- quem opera precisa saber que a
    recolha parou sem depender de um administrador. Trocar o certificado e
    outro ato: ele assina documento fiscal em nome da empresa."""
    pg, base_url = pagina
    erros = _abrir(pg, base_url, COMUM)
    assert not erros, erros
    _modal_sefaz(pg, com_formulario=False)
    assert pg.locator("#dfe-cert-caixa").count() == 0, (
        "o formulario de certificado apareceu para quem nao e administrador")
    assert pg.locator("#modalBox input[type=password]").count() == 0
    assert pg.locator("#modalBox input[type=file]").count() == 0
    # E O MODAL NAO FICA MUDO: ele continua respondendo o que falta, que e a
    # pergunta que quem opera veio fazer.
    texto = pg.inner_text("#modalBox")
    assert "certificado A1 de 9 das 10 filiais" in texto
    assert "Só administrador" in texto


def test_o_formulario_aparece_para_o_administrador(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url, ADMIN)
    assert not erros, erros
    _modal_sefaz(pg)
    assert pg.is_visible("#dfe-cert-caixa")
    # a lista de filiais sai da ROTA, nao de uma lista escrita no HTML: filial
    # nova entra sozinha.
    opcoes = pg.eval_on_selector_all(
        "#dfe-cert-cnpj option", "els => els.map(e => e.value)")
    assert opcoes == ["76104397000204", "76104397000123"], (
        "a filial SEM certificado tem de vir primeiro: e a que alguem abriu "
        "isto para resolver. Veio: %s" % opcoes)


def test_o_modal_da_SEFAZ_NAO_fica_em_carregando(pagina):
    """O defeito que a mudanca de lugar consertou.

    A SEFAZ nao esta no cofre de credenciais (quem autentica e um certificado
    A1 em arquivo). `integAjusteHTML` procurava a chave dela na lista do cofre,
    nao achava, e o modal ficava em "carregando as configuracoes..." PARA
    SEMPRE -- cartao prometendo um ajuste que nao existia em lugar nenhum.
    """
    pg, base_url = pagina
    _abrir(pg, base_url, ADMIN)
    _modal_sefaz(pg)
    assert "carregando as configurações" not in pg.inner_text("#modalBox")


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
    _modal_sefaz(pg)
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
    a recolha para e nao ha erro que aponte para ca.

    E ELE SOBREVIVE AO QUE ACONTECE DEPOIS. O cadastro repinta os cartoes e
    recarrega a lista de filiais; repintar o MODAL junto apagaria justamente
    esta mensagem, que e a parte que alguem precisa ler.
    """
    pg, base_url = pagina
    _abrir(pg, base_url, ADMIN,
           ao_cadastrar={"ok": True, "titular": "X", "valida_ate": "2026-09-29",
                         "dias": 22,
                         "avisos": ["Vence em 22 dia(s) (2026-09-29)."]})
    _modal_sefaz(pg)
    pg.set_input_files("#dfe-cert-arq", {
        "name": "x.pfx", "mimeType": "application/x-pkcs12", "buffer": b"\x30x"})
    pg.fill("#dfe-cert-senha", "s")
    pg.click("#dfe-cert-caixa button")
    pg.wait_for_function(
        "() => (document.getElementById('dfe-cert-msg')||{}).textContent"
        "        .includes('Vence em 22')", timeout=15000)
    # e continua la depois da repintura dos cartoes
    pg.wait_for_timeout(600)
    assert "Vence em 22" in pg.inner_text("#dfe-cert-msg")


def test_sem_arquivo_ou_sem_senha_a_tela_RECUSA_antes_de_enviar(pagina):
    """Mandar pedido incompleto para uma rota que grava segredo e ruido no log
    do servidor -- e a mensagem util e a que aparece do lado de ca."""
    pg, base_url = pagina
    _abrir(pg, base_url, ADMIN)
    _modal_sefaz(pg)
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


def test_a_falha_ao_LER_as_filiais_aparece_no_lugar_do_formulario(pagina):
    """`select` vazio nao explica nada, e a pessoa fica clicando em Cadastrar
    sem filial escolhida. A rota que enche os campos e outra, e a falha DELA
    tem de aparecer aqui."""
    pg, base_url = pagina
    _abrir(pg, base_url, ADMIN, filiais={"filiais": []})
    _modal_sefaz(pg, com_formulario=False)
    pg.wait_for_function(
        "() => (document.getElementById('dfe-cert-msg')||{}).textContent"
        "        .includes('nenhuma caixa aberta')", timeout=10000)


# ================== a tela de Central de Documentos NAO tem mais administracao

def _abrir_dfe(pg, base_url, usuario):
    def rota(route):
        u = route.request.url
        corpo = usuario if "/api/auth/me" in u else (
            CAIXAS if "/api/dfe" in u else {})
        route.fulfill(status=200, content_type="application/json",
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


def test_notas_de_entrada_NAO_tem_mais_formulario_nem_aba_de_admin(pagina):
    """A mudanca pedida por quem opera, afirmada onde ela se ve.

    Nem para ADMINISTRADOR: mover e mover. Enquanto o formulario existir nos
    dois lugares, um deles fica sem manutencao e passa a divergir -- e o que
    grava certificado nao pode ter duas versoes.
    """
    pg, base_url = pagina
    erros = _abrir_dfe(pg, base_url, ADMIN)
    assert not erros, erros
    assert pg.locator("#dfe-cert-caixa").count() == 0, (
        "o formulario de certificado continua na tela de Central de Documentos")
    assert pg.locator("#tabdfe-adm").count() == 0, (
        "a aba Administração continua na tela de Central de Documentos")
    assert pg.locator('#view-dfe .subtabs[data-abas="dfe"] button').count() == 2


def test_o_ESTADO_do_certificado_continua_na_tela_de_quem_opera(pagina):
    """O que NAO foi junto, e de proposito: a coluna Certificado.

    Quem opera precisa VER que a recolha vai parar, mesmo sem poder resolver --
    o certificado e a unica coisa que a para sem dar erro em lugar nenhum.
    Levar a leitura junto com o formulario seria trocar um problema de lugar
    por outro pior.
    """
    pg, base_url = pagina
    _abrir_dfe(pg, base_url, COMUM)
    linhas = pg.inner_text("#dfe-caixas")
    # 22 dias e o caso que importa: o aviso de vencimento vence a data. Quem
    # opera le "vence em 22 d" e sabe pedir a renovacao; "vale ate 2026-09-29"
    # e a mesma informacao com uma conta no meio.
    assert "vence em 22 d" in linhas
    assert "sem certificado" in linhas


def test_o_formulario_NAO_esta_no_HTML_servido():
    """Ele e montado pelo JS, e so para administrador.

    Enquanto morava no HTML, o `hidden` na marcacao guardava o FLASH entre a
    primeira pintura e a decisao do `USER.admin`. Fora do documento nao ha
    flash a guardar -- e este guard vira o contrario do antigo: o formulario
    nao pode VOLTAR para a marcacao, onde qualquer um o le com Ctrl+U.

    E teste de TEXTO-FONTE de proposito, e a excecao se justifica: a afirmacao
    e sobre o DOCUMENTO servido. O comportamento tem guard proprio acima.
    """
    html = (Path(__file__).resolve().parents[2] / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    i = html.index('<section class="view" id="view-dfe">')
    j = html.index('<section class="view" id="view-pecas">')
    bloco = html[i:j]
    for marca in ('id="dfe-cert-caixa"', 'id="dfe-cert-senha"',
                  'id="dfe-rec-nsu"', 'id="tabdfe-adm"'):
        assert marca not in bloco, (
            "%s voltou para a marcacao da tela dfe" % marca)


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

def test_as_DUAS_abas_sao_IRMAS_e_nao_encaixadas():
    """O `</div>` QUE RASGOU AS ABAS, de novo -- e a casa ja tinha essa licao.

    Ao dividir a tela em sub-abas, a primeira versao esqueceu de fechar a aba
    das caixas: a seguinte abriu DENTRO dela. O sintoma nao foi erro nenhum --
    foi `abaTrocar` mostrando um painel cujo PAI continuava escondido.

    Eram TRES abas ate a Administração ir para as Integracoes; agora sao duas,
    e a conta que importa continua sendo a PROFUNDIDADE: as abas do mesmo grupo
    tem de estar no mesmo nivel, e o bloco tem de fechar em zero. Tirar um
    bloco do meio de uma tela e exatamente o movimento que deixa `</div>`
    sobrando -- e ele nao da erro nenhum.
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

    assert [a for a, _ in abas] == ["cx", "docs"], (
        "esperava as abas cx e docs na tela dfe, achei %s" % abas)
    niveis = {p for _, p in abas}
    assert len(niveis) == 1, (
        "as abas estao ENCAIXADAS em vez de irmas: %s. `abaTrocar` mostra o "
        "painel, mas o PAI continua escondido." % abas)
    assert prof == 0, (
        "o bloco da tela nao fecha (%d div(s) em aberto) -- ele vai comer a "
        "tela seguinte" % prof)


def test_a_aba_que_nasce_aberta_e_a_de_DOCUMENTOS():
    """E a unica que alguem abre a tela para usar; a outra se olha quando algo
    esta errado."""
    html = (Path(__file__).resolve().parents[2] / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    i = html.index('<section class="view" id="view-dfe">')
    j = html.index('<section class="view" id="view-pecas">')
    bloco = html[i:j]
    for aba, escondida in (("docs", False), ("cx", True)):
        marca = 'data-aba="%s" id="aba-dfe-%s"' % (aba, aba)
        k = bloco.index(marca)
        abertura = bloco[k:bloco.index(">", k) + 1]
        assert ("hidden" in abertura) is escondida, (
            "a aba %s nasce %s: %s"
            % (aba, "escondida" if escondida else "aberta", abertura))
