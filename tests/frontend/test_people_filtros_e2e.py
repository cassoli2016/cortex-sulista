# -*- coding: utf-8 -*-
"""People Analytics no navegador: os filtros de MODALIDADE e de FILIAL.

Pedido de quem opera (15/09/2026): recortar a tela por ADM, OPER e MOT e por
filial. O que este arquivo segura:

1. **Trocar o filtro refaz a consulta** com o parâmetro novo — mediana e massa
   não se recalculam a partir do agregado já recebido.
2. **A tela diz o recorte que está valendo**, na linha abaixo dos chips, e
   adota o que o SERVIDOR aplicou: filial que ele não reconhece volta para
   "Todas", em vez de um seletor mostrando uma coisa e os números outra.
3. **A contagem de cada opção vem do servidor** e aparece no chip e no
   seletor — é o número que a tela vai mostrar se a pessoa clicar.
4. A linha de filtros **quebra no celular** e não empurra a página para o lado.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from tests.frontend.conftest import USUARIO

USER = {**USUARIO, "admin": False, "perfil": "Recursos Humanos",
        "telas": ["people"], "id": 9}

# As unidades e as contagens do cadastro real em 15/09/2026.
FILIAIS = ["FILIAL SBC", "FILIAL CURITIBA", "MATRIZ"]
MODAIS = {"ADM": 29, "OPER": 83, "MOT": 81}


def _payload(q: dict) -> dict:
    modal = (q.get("modalidade") or ["todas"])[0]
    filial = (q.get("filial") or [""])[0]
    # o servidor devolve o recorte que APLICOU (api/people.get_people)
    if filial not in FILIAIS:
        filial = ""
    if modal not in MODAIS:
        modal = "todas"
    n = 20 if filial else MODAIS.get(modal, sum(MODAIS.values()))
    return {
        "escopo": "todos",
        "filtros": {"escopo": "todos", "modalidade": modal, "filial": filial},
        "modalidades": [{"modalidade": k, "n": (7 if filial else v), "total": v}
                        for k, v in MODAIS.items()],
        "filiais": [{"filial": f, "n": 58 if f == "FILIAL SBC" else 10, "total": 58}
                    for f in FILIAIS],
        "lideranca": {"n": 3, "massa": 0, "pct_pessoas": 1.5, "pct_massa": 4.0,
                      "quadro_total": n, "por_liderado": 5.0, "cargos": [],
                      "niveis": [], "limitrofes": []},
        "kpis": {"ativos": n, "afastados": 0, "afastados_massa": 0, "massa": 0,
                 "salario_medio": 0, "salario_mediano": 0, "casa_mediana": 2.7,
                 "idade_mediana": 39.6, "mulheres": 0, "pct_mulheres": 0,
                 "sessenta_mais": 0, "pct_sessenta": 0, "menos_1_ano": 0,
                 "pct_menos_1_ano": 0, "cargos": 0, "cargos_unicos": 0,
                 "areas": 1, "afast_longos": 0, "afast_obitos": 0},
        "piramide": [], "tempo_casa": [], "por_area": [], "cargos": [],
        "cargos_unicos": [], "afastamentos": [], "afast_obitos": [],
        "por_motivo": {}, "fonte": "dublê", "atualizado_em": "2026-09-15 10:00"}


def _abrir(pg, base_url, largura=1440):
    pedidos: list[dict] = []

    def rota(route):
        u = urlparse(route.request.url)
        if u.path.endswith("/api/auth/me"):
            corpo = {"usuario": USER, "ok": True, **USER}
        elif u.path.endswith("/api/rh/people"):
            q = parse_qs(u.query, keep_blank_values=True)
            pedidos.append(q)
            corpo = _payload(q)
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.set_viewport_size({"width": largura, "height": 900})
    pg.route("**/api/**", rota)
    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("%s/static/index.html#people" % base_url)
    pg.wait_for_selector("#view-people.on", timeout=15000)
    pg.wait_for_selector("#ppl-modal button .n", timeout=15000)
    return pedidos, erros


def _hint(pg) -> str:
    return pg.text_content("#ppl-escopo-hint") or ""


def test_os_chips_de_modalidade_e_o_seletor_de_filial_trazem_a_contagem(pagina):
    pg, base_url = pagina
    pedidos, erros = _abrir(pg, base_url)
    chips = pg.eval_on_selector_all(
        "#ppl-modal button", "els => els.map(e => e.textContent.trim())")
    assert chips == ["Todas193", "ADM29", "OPER83", "MOT81"], chips
    opcoes = pg.eval_on_selector_all(
        "#fPplFilial option", "els => els.map(e => e.textContent.trim())")
    assert "FILIAL SBC (58)" in opcoes and opcoes[0].startswith("Todas"), opcoes
    # a primeira consulta já leva os dois parâmetros, vazios
    assert pedidos[0]["modalidade"] == ["todas"] and pedidos[0]["filial"] == [""]
    # a regra de CSS VALE (e não só existe): o select não herda a caixa-alta
    # do rótulo, que é o que `.view select` e o label disputam
    estilo = pg.eval_on_selector(
        "#fPplFilial", "e => [getComputedStyle(e).textTransform, getComputedStyle(e).fontSize]")
    assert estilo == ["none", "13px"], estilo
    assert not erros, erros


def test_clicar_em_MOT_refaz_a_consulta_e_diz_o_recorte(pagina):
    pg, base_url = pagina
    pedidos, erros = _abrir(pg, base_url)
    antes = len(pedidos)
    pg.click("#ppl-modal button[onclick=\"pplModal('MOT')\"]")
    pg.wait_for_function(
        "() => document.getElementById('ppl-escopo-hint').textContent.includes('modalidade MOT')")
    # o KPI do quadro passa a mostrar os 81 do dublê — a resposta chegou e pintou
    pg.wait_for_function("() => document.querySelector('#kpis-people').textContent.includes('81')")
    assert len(pedidos) > antes and pedidos[-1]["modalidade"] == ["MOT"]
    classe = pg.get_attribute("#ppl-modal button[onclick=\"pplModal('MOT')\"]", "class")
    assert "on" in (classe or "").split()
    assert "motoristas, pela lotação" in _hint(pg)
    assert not erros, erros


def test_escolher_a_filial_refaz_a_consulta_e_o_seletor_continua_nela(pagina):
    pg, base_url = pagina
    pedidos, erros = _abrir(pg, base_url)
    pg.select_option("#fPplFilial", "FILIAL SBC")
    pg.wait_for_function(
        "() => document.getElementById('ppl-escopo-hint').textContent.includes('FILIAL SBC')")
    pg.wait_for_function("() => document.querySelector('#kpis-people').textContent.includes('20')")
    assert pedidos[-1]["filial"] == ["FILIAL SBC"]
    # o re-render reconstrói as opções (as contagens mudam) e não pode perder a escolha
    assert pg.eval_on_selector("#fPplFilial", "e => e.value") == "FILIAL SBC"
    assert not erros, erros


def test_filial_que_o_servidor_nao_reconhece_volta_para_todas(pagina):
    """O seletor e a linha de recorte adotam o que o servidor APLICOU."""
    pg, base_url = pagina
    pedidos, erros = _abrir(pg, base_url)
    pg.evaluate("pplFilial('FILIAL QUE NAO EXISTE')")
    pg.wait_for_function(
        "() => !document.getElementById('ppl-escopo-hint').textContent.includes('NAO EXISTE')",
        timeout=10000)
    assert pedidos[-1]["filial"] == ["FILIAL QUE NAO EXISTE"]
    assert pg.eval_on_selector("#fPplFilial", "e => e.value") == ""
    assert pg.evaluate("PPL_FILIAL") == ""
    assert not erros, erros


def test_a_linha_de_filtros_quebra_no_celular_sem_empurrar_a_pagina(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url, largura=390)
    direita = pg.eval_on_selector(
        ".ppl-filtros", "e => Math.max(...[...e.querySelectorAll('button, select')]"
                        ".map(x => x.getBoundingClientRect().right))")
    assert direita <= 390, f"um controle dos filtros termina em {direita}px, fora da tela"
    sobra = pg.eval_on_selector(
        "#view-people", "e => e.scrollWidth - e.clientWidth")
    assert sobra == 0, f"a tela rola {sobra}px para o lado"
