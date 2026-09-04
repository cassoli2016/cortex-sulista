"""O drill da DRE para no CENTRO DE CUSTO; o razão abre em modal.

O terceiro nível era uma tabela dentro de outra tabela dentro de uma linha de
tabela, num `colspan` já recuado 82px, com quatro colunas espremidas para uma
lista que vai a 500 lançamentos. Ele saiu da árvore.

E o centro de custo virou LINHA da própria tabela da DRE, mês a mês, alinhada
com os níveis de cima. Ele era o único nível com um número só do período
inteiro: quem via "R$ 2,3 mi" num centro não sabia se era um mês fora da curva
ou doze meses iguais — que é a pergunta que traz alguém até aqui.

O que estes guards cobram, e cada um custou algo em alguma tela:

1. **O valor é um `<button>`**, não um `<span onclick>`. Quem confere número
   por teclado precisa alcançá-lo.
2. **O recorte vem do BOTÃO**: clicar no valor de julho abre julho. Usar o
   período do filtro traria os três meses e a soma do modal não bateria com o
   número em que a pessoa clicou.
3. **As células do centro são as MESMAS do resto da tabela** (R$ mil, seta
   mensal). Duplicar o formato faria a linha de baixo parecer mil vezes maior
   que a de cima, na mesma coluna.
4. **A linha de centro herda o grupo de visibilidade da conta.** Sem isso ela
   nasce escondida — e, pior, continuaria visível depois de recolher o
   agrupador, órfã embaixo de um nível já fechado. O mesmo defeito que as
   contas já tiveram.
5. **O teto de 500 se DECLARA**, e diz que alcança a exportação.
6. **A exportação leva a lista INTEIRA, não a página** — planilha com as 30
   visíveis não soma com o número clicado, e isso só se descobre depois de
   mandar o arquivo para alguém.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

MESES = ["2026-06", "2026-07", "2026-08"]

DRE = {
    "meses": MESES,
    "comp_de_aa": "2025-06", "comp_ate_aa": "2025-08",
    "atualizado_em": "2026-09-03T10:00:00",
    "linhas": [{
        "rotulo": "CUSTO VARIAVEL", "nivel": 0, "tipo": "linha",
        "total": -1160063.13,
        "meses": {"2026-06": -365958.0, "2026-07": -368393.0,
                  "2026-08": -425712.13},
        "detalhe": [{
            "agrupador": "CV - FRETE AGREGADOS", "total": -1160063.13,
            "meses": {"2026-06": -365958.0, "2026-07": -368393.0,
                      "2026-08": -425712.13},
            "contas": [{
                "grupo": 1, "reduzido": 411803, "estrutural": "4.1.1.08.0003",
                "conta": "PEDAGIO CONTRATO DE TRANSPORTE AGREGADOS",
                "total": -1160063.13,
                "meses": {"2026-06": -365958.0, "2026-07": -368393.0,
                          "2026-08": -425712.13}}]}]}],
    "excluidos": {"n": 0, "efeito": 0.0},
}

CENTROS = {
    "total": -1160063.13, "meses": MESES,
    "sem_centro_rotulo": "(sem centro de custo)",
    "linhas": [
        {"centro": 101, "descricao": "VEICULOS AGREGADOS", "lancamentos": 42,
         "valor": -1034351.0,
         "meses": {"2026-06": -330000.0, "2026-07": -340000.0,
                   "2026-08": -364351.0}},
        {"centro": None, "descricao": "(sem centro de custo)",
         "lancamentos": 8, "valor": -125712.13,
         "meses": {"2026-06": -35958.0, "2026-07": -28393.0,
                   "2026-08": -61361.13}},
    ]}


def _lanc(n: int) -> dict:
    """`n` lançamentos, os dois primeiros com os valores que os guards conferem."""
    ls = [{"dtlancamento": "2026-08-04", "valordebito": 369230.68,
           "valorcredito": None,
           "historicodescricao": "VLR REF PEDAGIO FAT 1/704913583 SEM PARAR"},
          {"dtlancamento": "2026-08-01", "valordebito": None,
           "valorcredito": 376348.52,
           "historicodescricao": "VLR REF BAIXA PROV PEDAGIO FAT 26171585220"}]
    for i in range(len(ls), n):
        ls.append({"dtlancamento": "2026-08-%02d" % (i % 28 + 1),
                   "valordebito": 100.0 + i, "valorcredito": None,
                   "historicodescricao": "LANCAMENTO %d" % i})
    return {"limite": 500, "truncou": False, "linhas": ls[:n]}


def _abre(pagina, lanc=None):
    pg, base = pagina
    vistas: list[str] = []

    def rota(r):
        url = r.request.url
        if "/api/auth/me" in url:
            corpo = ADMIN
        elif "/api/financeiro/dre" in url:
            corpo = DRE
        elif "/api/dre/centros" in url:
            corpo = CENTROS
        elif "/api/dre/conta-lancamentos" in url:
            vistas.append(url)
            corpo = lanc if lanc is not None else _lanc(2)
        else:
            corpo = {}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.set_viewport_size({"width": 1500, "height": 1000})
    pg.goto(base + "/static/index.html#dre")
    pg.wait_for_timeout(900)
    # a DRE é uma árvore: linha -> agrupador -> conta -> centro de custo
    pg.click("#dre-l-0")
    pg.click("#dre-a-0-0")
    pg.wait_for_selector("#dre-corpo tr[data-r='411803'] button.drebt")
    pg.click("#dre-corpo tr[data-r='411803'] button.drebt")
    pg.wait_for_selector("tr.dre-cc button.drevalor")
    return pg, vistas


def _cc(pg, i=0):
    """A i-ésima linha de centro de custo.

    Locator e não `tr.dre-cc:first-of-type`: `:first-of-type` fala do TIPO do
    elemento, não da classe — as linhas de centro nunca são o primeiro `<tr>`
    do corpo da tabela, e o seletor não casa nada.
    """
    return pg.locator("tr.dre-cc").nth(i)


def _botoes(pg, i=0):
    """Os valores clicáveis da linha: um por mês, e o Total no fim."""
    return _cc(pg, i).locator("button.drevalor")


# ------------------------------------------------------- a linha do centro
def test_o_centro_de_custo_e_linha_da_tabela_mes_a_mes(pagina):
    pg, _ = _abre(pagina)
    nomes = pg.eval_on_selector_all(
        "tr.dre-cc", "es => es.map(e => e.dataset.nome)")
    assert nomes == ["VEICULOS AGREGADOS · 101", "(sem centro de custo)"]
    # mesma contagem de células que a conta logo acima: uma a mais ou a menos
    # desalinha o cabeçalho inteiro
    n_conta = pg.eval_on_selector(
        "#dre-corpo tr[data-r='411803']", "e => e.children.length")
    n_cc = _cc(pg).evaluate("e => e.children.length")
    assert n_cc == n_conta, "centro com %d células, conta com %d" % (n_cc, n_conta)
    # e um valor clicável por MÊS, não um só do período inteiro
    assert _botoes(pg).count() == 4, "esperava três meses mais o Total"


def test_os_valores_do_centro_usam_as_celulas_da_propria_tabela(pagina):
    """A DRE mostra R$ MIL. Um centro em reais na mesma coluna faria a linha
    de baixo parecer mil vezes maior que a de cima."""
    pg, _ = _abre(pagina)
    txt = _cc(pg).evaluate("e => e.children[e.children.length-5].innerText")
    assert "364" in txt and "364.351" not in txt, \
        "o centro saiu em reais onde a tabela mostra R$ mil: %r" % txt


def test_a_linha_do_centro_some_com_o_agrupador(pagina):
    """Órfã embaixo de um nível fechado é pior que ausente: ela some do
    contexto e continua somando na leitura de quem passa o olho."""
    pg, _ = _abre(pagina)
    assert _cc(pg).is_visible()
    pg.click("#dre-a-0-0")                       # recolhe o agrupador
    assert not _cc(pg).is_visible(), "a linha de centro ficou órfã"


# ------------------------------------------------------------- o modal
def test_o_recorte_do_modal_vem_do_mes_clicado(pagina):
    pg, vistas = _abre(pagina)
    _botoes(pg).nth(1).click()                   # 0=jun, 1=jul, 2=ago, 3=total
    pg.wait_for_selector("#dre-lanc-corpo table")
    assert vistas, "o modal não consultou o razão"
    assert "de=2026-07-01" in vistas[-1] and "ate=2026-08-01" in vistas[-1], \
        vistas[-1]
    assert "07/2026" in pg.inner_text("#modalBox"), \
        "o modal não diz de que mês é a lista"


def test_o_valor_abre_o_razao_em_modal(pagina):
    pg, _ = _abre(pagina)
    assert _botoes(pg).first.evaluate("e => e.tagName") == "BUTTON", \
        "o valor precisa ser botão: quem confere por teclado também clica"
    _botoes(pg).last.click()                     # o Total do período
    pg.wait_for_selector("#modalBg.aberto")
    pg.wait_for_selector("#dre-lanc-corpo table")
    txt = pg.inner_text("#modalBox")
    assert "VEICULOS AGREGADOS" in txt, "o modal não diz de que centro é a lista"
    assert "PEDAGIO CONTRATO DE TRANSPORTE AGREGADOS" in txt, \
        "o modal não diz de que conta é a lista"
    assert "04/08/2026" in txt and "SEM PARAR" in txt
    # a lista não fica presa dentro da linha da tabela
    assert pg.eval_on_selector_all("tr.drill-lanc", "es => es.length") == 0


def test_o_teto_de_500_se_declara_e_alcanca_a_exportacao(pagina):
    """Lista cortada em silêncio faz quem confere culpar o número certo — e
    quem exporta manda a planilha incompleta sem saber."""
    pg, _ = _abre(pagina, lanc={**_lanc(2), "truncou": True})
    _botoes(pg).last.click()
    pg.wait_for_selector("#dre-lanc-corpo table")
    # NO AVISO, e não no modal inteiro: o botão "Exportar Excel" contém a
    # palavra "exporta", e o guard passava mesmo com o aviso mudo.
    aviso = pg.inner_text("#dre-lanc-corpo .avisofaixa").lower()
    assert "500" in aviso and "não fecha" in aviso
    assert "exporta" in aviso, "o aviso não alcança a exportação"


def test_a_soma_do_modal_e_debito_menos_credito(pagina):
    pg, _ = _abre(pagina)
    _botoes(pg).last.click()
    pg.wait_for_selector("#dre-lanc-corpo table")
    # 369.230,68 - 376.348,52 = -7.117,84
    assert "7.117,84" in pg.inner_text("#dre-lanc-corpo"), \
        "a soma somou crédito como se fosse débito"


# ---------------------------------------------------------- paginação
def test_a_lista_pagina_de_30_em_30(pagina):
    pg, _ = _abre(pagina, lanc=_lanc(75))
    _botoes(pg).last.click()
    pg.wait_for_selector("#dre-lanc-corpo table")
    linhas = "#dre-lanc-corpo tbody tr"
    assert pg.eval_on_selector_all(linhas, "es => es.length") == 30
    txt = pg.inner_text("#dre-lanc-corpo")
    assert "1–30 de 75" in txt and "página 1 de 3" in txt
    # a soma e a contagem são da lista INTEIRA, não da página visível
    assert "75 lançamento(s)" in txt

    pg.click("#dre-lanc-corpo button:has-text('próxima')")
    assert "31–60 de 75" in pg.inner_text("#dre-lanc-corpo")
    pg.click("#dre-lanc-corpo button:has-text('próxima')")
    txt = pg.inner_text("#dre-lanc-corpo")
    assert "61–75 de 75" in txt
    assert pg.eval_on_selector_all(linhas, "es => es.length") == 15
    assert pg.eval_on_selector(
        "#dre-lanc-corpo button:has-text('próxima')", "e => e.disabled"), \
        "a última página ainda oferece 'próxima'"


def test_uma_pagina_so_nao_mostra_paginador(pagina):
    pg, _ = _abre(pagina, lanc=_lanc(12))
    _botoes(pg).last.click()
    pg.wait_for_selector("#dre-lanc-corpo table")
    assert "página 1 de" not in pg.inner_text("#dre-lanc-corpo")


# ---------------------------------------------------------- exportação
def test_a_exportacao_leva_a_lista_inteira_e_nao_a_pagina(pagina):
    pg, _ = _abre(pagina, lanc=_lanc(75))
    _botoes(pg).last.click()
    pg.wait_for_selector("#dre-lanc-corpo table")
    with pg.expect_download() as baixando:
        pg.click("#dre-lanc-corpo button:has-text('Exportar Excel')")
    caminho = baixando.value.path()
    txt = caminho.read_text(encoding="utf-8-sig")
    linhas = [x for x in txt.splitlines() if x.strip()]
    assert len(linhas) == 76, "cabeçalho + 75 lançamentos, achei %d" % len(linhas)
    assert linhas[0].split(";") == [
        "Data", "Conta", "Centro de custo", "Histórico", "Débito", "Crédito"]
    # o Excel pt-BR só SOMA a coluna se o número vier com vírgula decimal
    assert "369230,68" in linhas[1], linhas[1]
    assert "VEICULOS AGREGADOS" in linhas[1]
