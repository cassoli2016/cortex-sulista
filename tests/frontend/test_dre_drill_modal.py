"""O drill da DRE para no CENTRO DE CUSTO; o razão abre em modal.

O terceiro nível era uma tabela dentro de uma tabela dentro de uma linha de
tabela, num `colspan` já recuado 82px — quatro colunas espremidas para uma
lista que vai a 500 lançamentos. Ele saiu da árvore e passou para um modal,
aberto pelo VALOR: o número é o que se quer conferir, e é nele que se clica.

O que estes guards cobram, e cada um custou algo em outra tela:

1. **O valor é um `<button>`**, não um `<span onclick>`. Quem confere número
   por teclado precisa alcançá-lo.
2. **O teto de 500 se DECLARA.** Lista cortada em silêncio faz a soma da tela
   não bater com o total de cima, e quem confere culpa o número certo.
3. **A árvore não tem mais o terceiro nível** — meia migração deixaria os dois
   caminhos vivos, e o de dentro da tabela é justamente o ilegível.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

DRE = {
    "meses": ["2026-08"],
    "linhas": [{
        "rotulo": "CUSTO VARIAVEL", "nivel": 0, "tipo": "linha",
        "meses": {"2026-08": -425712.13},
        "detalhe": [{
            "agrupador": "CV - FRETE AGREGADOS",
            "meses": {"2026-08": -425712.13},
            "contas": [{
                "grupo": 1, "reduzido": 411803, "estrutural": "4.1.1.08.0003",
                "conta": "PEDAGIO CONTRATO DE TRANSPORTE AGREGADOS",
                "meses": {"2026-08": -425712.13}}]}]}],
    "excluidos": {"n": 0, "efeito": 0.0},
}

CENTROS = {"total": -425712.13, "sem_centro_rotulo": "(sem centro de custo)",
           "linhas": [
               {"centro": 101, "descricao": "MATRIZ CURITIBA",
                "valor": -300000.0, "lancamentos": 42},
               {"centro": None, "descricao": "(sem centro de custo)",
                "valor": -125712.13, "lancamentos": 8}]}

LANC = {"limite": 500, "truncou": False, "linhas": [
    {"dtlancamento": "2026-08-04", "valordebito": 369230.68,
     "valorcredito": None,
     "historicodescricao": "VLR REF PEDAGIO FAT 1/704913583 SEM PARAR"},
    {"dtlancamento": "2026-08-01", "valordebito": None,
     "valorcredito": 376348.52,
     "historicodescricao": "VLR REF BAIXA PROV PEDAGIO FAT 26171585220"},
]}


def _abre(pagina, lanc=None):
    pg, base = pagina

    def rota(r):
        url = r.request.url
        if "/api/auth/me" in url:
            corpo = ADMIN
        elif "/api/financeiro/dre" in url:
            corpo = DRE
        elif "/api/dre/centros" in url:
            corpo = CENTROS
        elif "/api/dre/conta-lancamentos" in url:
            corpo = lanc if lanc is not None else LANC
        else:
            corpo = {}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.set_viewport_size({"width": 1500, "height": 1000})
    pg.goto(base + "/static/index.html#dre")
    pg.wait_for_timeout(900)
    # a DRE e uma arvore: linha -> agrupador -> conta -> centro de custo
    pg.click("#dre-l-0")
    pg.click("#dre-a-0-0")
    pg.wait_for_selector("#dre-corpo tr[data-r='411803'] button.drebt")
    pg.click("#dre-corpo tr[data-r='411803'] button.drebt")
    pg.wait_for_selector("tr.dre-drill button.drevalor")
    return pg


def test_a_arvore_para_no_centro_de_custo(pagina):
    pg = _abre(pagina)
    linhas = pg.eval_on_selector_all(
        "tr.dre-drill tbody tr", "es => es.map(e => e.dataset.nome)")
    assert linhas == ["MATRIZ CURITIBA · 101", "(sem centro de custo)"]
    # nenhum triângulo de terceiro nível dentro da quebra por centro
    assert pg.eval_on_selector_all(
        "tr.dre-drill button.drebt", "es => es.length") == 0


def test_o_valor_abre_o_razao_em_modal(pagina):
    pg = _abre(pagina)
    assert pg.eval_on_selector(
        "tr.dre-drill button.drevalor", "e => e.tagName") == "BUTTON", \
        "o valor precisa ser botão: quem confere por teclado também clica"
    pg.click("tr.dre-drill tbody tr:first-child button.drevalor")
    pg.wait_for_selector("#modalBg.aberto")
    pg.wait_for_selector("#dre-lanc-corpo table")
    txt = pg.inner_text("#modalBox")
    assert "MATRIZ CURITIBA" in txt, "o modal não diz de que centro é a lista"
    assert "PEDAGIO CONTRATO DE TRANSPORTE AGREGADOS" in txt, \
        "o modal não diz de que conta é a lista"
    assert "08/2026" in txt, "o modal não diz de que período é a lista"
    assert "04/08/2026" in txt and "SEM PARAR" in txt
    # a lista não fica presa dentro da linha da tabela
    assert pg.eval_on_selector_all(
        "tr.drill-lanc", "es => es.length") == 0


def test_o_teto_de_500_se_declara(pagina):
    """Lista cortada em silêncio faz a soma não bater com o total de cima."""
    pg = _abre(pagina, lanc={**LANC, "truncou": True})
    pg.click("tr.dre-drill tbody tr:first-child button.drevalor")
    pg.wait_for_selector("#dre-lanc-corpo table")
    txt = pg.inner_text("#modalBox")
    assert "500" in txt and "não fecha" in txt.lower(), \
        "o modal cortou a lista sem dizer"


def test_a_soma_do_modal_e_debito_menos_credito(pagina):
    pg = _abre(pagina)
    pg.click("tr.dre-drill tbody tr:first-child button.drevalor")
    pg.wait_for_selector("#dre-lanc-corpo table")
    txt = pg.inner_text("#dre-lanc-corpo")
    # 369.230,68 - 376.348,52 = -7.117,84
    assert "7.117,84" in txt, "a soma somou crédito como se fosse débito"
