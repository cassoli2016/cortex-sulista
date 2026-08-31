"""O filtro por cliente da Antecipação, no navegador.

O payload do dublê é o payload REAL da tela, recortado no volume e preservado
na forma (`_payload.json`, capturado do ERP). Dublê otimista testa um backend
que não existe — foi assim que a suíte do WhatsApp passou inteira com a
produção quebrada, porque o falso omitia um campo que a Z-API sempre manda.

O que só se prova AQUI:

1. **A tela não estoura.** `ANTSAC` é um `const` de topo declarado depois do
   `qsView` que o lê; se algum caminho o alcançar antes da avaliação, é
   `ReferenceError` e o app inteiro cai.
2. **Os chips saem do UNIVERSO, não do resultado filtrado.** Com um cliente
   escolhido, os outros continuam no seletor — senão ninguém consegue
   marcá-los de volta.
3. **O rótulo do primeiro KPI muda com o filtro.** Sem filtro ele é a
   NECESSIDADE; com a pilha restrita passa a ser o que se CONSEGUE antecipar,
   e a necessidade não mudou. Manter "Precisa antecipar" diria que o buraco
   encolheu porque alguém desmarcou um cliente.
4. **O filtro chega na URL como raiz de CNPJ**, que é a chave do convênio — o
   ERP fatura por filial e casar por nome perderia metade do recebível.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.frontend.conftest import USUARIO

USER = {**USUARIO, "admin": False, "perfil": "Financeiro",
        "telas": ["antec"], "id": 7}

PAYLOAD = json.loads(
    (Path(__file__).resolve().parent / "antec_payload.json")
    .read_text(encoding="utf-8"))


def _rota(vistos=None):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = USER
        elif "/financeiro/antecipacao" in u:
            if vistos is not None:
                vistos.append(u)
            # O backend devolve em `parametros.sacados` o que recebeu; a tela
            # le DALI para decidir o rotulo, entao o duble tem de refletir.
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(u).query)
            sac = [x for x in (q.get("sacados", [""])[0] or "").split(",") if x]
            corpo = {**PAYLOAD,
                     "parametros": {**PAYLOAD["parametros"], "sacados": sac}}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))
    return rota


def _abrir(pg, base_url, vistos=None):
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.route("**/api/**", _rota(vistos))
    pg.goto(f"{base_url}/static/index.html#antec")
    pg.wait_for_selector("#kpis-antec .kpi", timeout=15000)
    pg.wait_for_selector("#fAntSacados .chip", timeout=10000)
    return erros


def test_a_tela_nao_estoura_com_o_filtro_novo(pagina):
    """`ANTSAC` é `const` de topo lido por `qsView`, que está antes dele no
    arquivo. Um erro na avaliação derruba o app inteiro, não só esta tela."""
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert erros == [], erros


def test_o_seletor_traz_todos_os_clientes_com_convenio(pagina):
    """Os cinco sacados com convênio, mais o "Todos"."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert "Todos" in pg.inner_text("#fAntSacados")
    raizes = {c.get_attribute("data-r")
              for c in pg.query_selector_all("#fAntSacados .chip[data-r]")}
    assert raizes == {"84683374", "02162259", "61156113", "00514820",
                      "36448137"}, raizes


def test_o_rotulo_encurta_mas_o_nome_INTEIRO_fica_no_tooltip(pagina):
    """Razão social não cabe num chip ("Adient do Brasil Bancos Automotivos"),
    então o sufixo jurídico sai e o resto é cortado. Nada se perde: o nome
    completo, o valor e a contagem de títulos ficam no `title` — encurtar sem
    guardar o original seria trocar legibilidade por informação.
    """
    pg, base_url = pagina
    _abrir(pg, base_url)
    chip = pg.query_selector('#fAntSacados .chip[data-r="61156113"]')
    assert "Iochpe Maxion" in chip.inner_text()
    # `S A` com espaço no meio é o caso real do cadastro, e uma alternância
    # só com `S/A`/`S.A.` deixaria passar exatamente esse
    assert "S A" not in chip.inner_text()
    assert "Iochpe Maxion S A" in chip.get_attribute("title")
    assert "título" in chip.get_attribute("title")


def test_o_chip_mostra_o_valor_elegivel_de_cada_cliente(pagina):
    """O seletor que diz quanto cada cliente tem deixa de ser só um filtro e
    passa a responder "de quem vale a pena antecipar" antes do clique."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    txt = pg.inner_text("#fAntSacados")
    assert "R$ 3,1 mi" in txt or "R$ 3.1 mi" in txt, txt


def test_escolher_um_cliente_manda_a_RAIZ_na_url(pagina):
    pg, base_url = pagina
    vistos = []
    _abrir(pg, base_url, vistos)
    pg.click('#fAntSacados .chip[data-r="84683374"]')
    pg.wait_for_timeout(600)
    assert any("sacados=84683374" in u for u in vistos), vistos[-2:]


def test_dois_clientes_vao_juntos_e_o_terceiro_continua_no_seletor(pagina):
    """É o pedido: selecionar MAIS DE UM. E os não escolhidos precisam
    continuar visíveis — montar o seletor do resultado filtrado faria o
    cliente sumir e ninguém conseguiria marcá-lo de volta."""
    pg, base_url = pagina
    vistos = []
    _abrir(pg, base_url, vistos)
    pg.click('#fAntSacados .chip[data-r="84683374"]')
    pg.wait_for_timeout(400)
    pg.click('#fAntSacados .chip[data-r="02162259"]')
    pg.wait_for_timeout(600)
    ultima = vistos[-1]
    assert "84683374" in ultima and "02162259" in ultima, ultima
    # o não escolhido segue no seletor, e os dois escolhidos aparecem marcados
    assert pg.query_selector('#fAntSacados .chip[data-r="61156113"]')
    marcados = pg.query_selector_all("#fAntSacados .chip.active")
    assert len(marcados) == 2, [m.inner_text() for m in marcados]


def test_com_filtro_o_KPI_muda_de_rotulo(pagina):
    """Sem filtro o número é a NECESSIDADE; com a pilha restrita ele é o que
    se CONSEGUE antecipar, e a necessidade não mudou."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert "Precisa antecipar" in pg.inner_text("#kpis-antec")
    pg.click('#fAntSacados .chip[data-r="84683374"]')
    pg.wait_for_timeout(700)
    txt = pg.inner_text("#kpis-antec")
    assert "Antecipável nos selecionados" in txt
    assert "1 cliente(s) escolhido(s)" in txt


def test_TODOS_limpa_a_escolha(pagina):
    pg, base_url = pagina
    vistos = []
    _abrir(pg, base_url, vistos)
    pg.click('#fAntSacados .chip[data-r="84683374"]')
    pg.wait_for_timeout(400)
    pg.click('#fAntSacados .chip:has-text("Todos")')
    pg.wait_for_timeout(600)
    assert "sacados=" not in vistos[-1], vistos[-1]
    assert "Precisa antecipar" in pg.inner_text("#kpis-antec")
