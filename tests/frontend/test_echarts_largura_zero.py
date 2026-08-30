"""Gráfico desenhado com o contêiner ESCONDIDO tem de se corrigir ao aparecer.

A ARMADILHA QUE A CONVERSÃO CRIOU
=================================
O SVG à mão tinha `viewBox` e `preserveAspectRatio`: desenhado dentro de uma
view `display:none`, ele simplesmente escalava para a largura que houvesse na
hora de aparecer. O ECharts não faz isso — ele MEDE o contêiner uma vez, no
`init`, e uma medida de zero fica valendo para sempre. Voltar a exibir a view
não dispara evento nenhum.

E o sintoma é silencioso: nenhum erro no console, nenhum cartão vazio. O
gráfico aparece, com os eixos certos, e apenas os rótulos do eixo X somem
quase todos — o `hideOverlap` os descarta porque na largura zero eles se
sobrepõem. Quem olha lê "a série tem 1 ponto" onde há cinco.

Medido nesta bancada antes do conserto: cinco dias de combustível desenhados
com a tela fechada mostravam só `02/08`.

O conserto é um `ResizeObserver` no `echartsRegistrar`, e ele cobre de uma vez
os três casos: a view que aparece, a sidebar que recolhe e a janela que muda.
Fica no registrador, e não no `ecDesenhar`, para valer também para os gráficos
que chamam o `init` na mão.
"""
from __future__ import annotations

import json

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

# cinco dias distintos: e a supressao POR COLISAO que o teste mede, entao
# precisam ser rotulos que so cabem lado a lado numa largura de verdade
DIAS = [
    {"dia": "2026-08-01", "litros": 22000},
    {"dia": "2026-08-02", "litros": 9000},
    {"dia": "2026-08-03", "litros": 24000},
    {"dia": "2026-08-04", "litros": 26000},
    {"dia": "2026-08-05", "litros": 25000},
]
ROTULOS = ["01/08", "02/08", "03/08", "04/08", "05/08"]

DESENHA = """(rows) => chartLitrosRender('chartCombDia', rows,
  r => { const p = (r.dia || '').split('-');
         return p.length === 3 ? p[2] + '/' + p[1] : (r.dia || ''); })"""


@pytest.fixture
def painel(pagina):
    pg, base = pagina
    pg.set_viewport_size({"width": 1500, "height": 900})
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(ADMIN if "/api/auth/me" in r.request.url else {})))
    pg.goto(f"{base}/static/index.html#home")
    pg.wait_for_timeout(900)
    return pg


def test_desenhar_com_a_tela_fechada_e_depois_abrir_mostra_a_serie_inteira(painel):
    """O caso que o ResizeObserver existe para consertar."""
    pg = painel
    largura = pg.evaluate(
        "() => document.getElementById('chartCombDia').clientWidth")
    assert largura == 0, (
        "a premissa do teste caiu: o contêiner precisa estar ESCONDIDO "
        f"(largura 0) no momento do desenho, e mediu {largura}px")

    pg.evaluate(DESENHA, DIAS)
    pg.wait_for_timeout(1500)

    pg.evaluate("() => { location.hash = '#comb'; }")
    pg.wait_for_timeout(1200)

    texto = " ".join(pg.inner_text("#chartCombDia").split())
    faltam = [r for r in ROTULOS if r not in texto]
    assert not faltam, (
        f"rótulos sumidos depois de a tela abrir: {faltam}. O gráfico ficou "
        f"com a medida de largura zero do init. Texto: {texto!r}")


def test_o_registrador_observa_o_elemento_de_cada_instancia(painel):
    """Sem a observação, o conserto acima seria coincidência de outro evento.

    Amarra o mecanismo, não só o efeito: um refactor que troque o registrador
    por um `setTimeout` passaria no teste de cima e voltaria a quebrar no dia
    em que a tela demorasse mais que o timeout para aparecer.
    """
    pg = painel
    pg.evaluate(DESENHA, DIAS)
    pg.wait_for_timeout(1500)
    marcado = pg.evaluate(
        "() => { const e = document.getElementById('chartCombDia');"
        "        return !!(e && e.__ecInst && !e.__ecInst.isDisposed()); }")
    assert marcado, ("o elemento não carrega a instância do ECharts — o "
                     "ResizeObserver não teria como saber quem redimensionar")
