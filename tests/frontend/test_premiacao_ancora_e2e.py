# -*- coding: utf-8 -*-
"""Premiação: quando o mês corrente não tem dado, a tela DIZ que mostra outro.

15/09/2026: "a telemetria não está atualizando, os números não mudam". A
Gobrax devolvia os motoristas de setembro com km e nota zerados; o serviço
não grava mês zerado (certo — é dado de pagamento) e a tela, sem linha no
corrente, abria no último mês com dado. Abria CALADA: o seletor dizia
"Agosto / 2026" e mais nada, e quem esperava setembro concluía que o sistema
tinha travado. A âncora continua (tela vazia no dia 1º era o defeito
anterior); agora ela se declara, com o aviso do mês pedido junto.
"""
from __future__ import annotations

import json

from tests.frontend.test_premiacao_e2e import ADMIN, PAINEL, SERIE

AVISO_DO_SERVIDOR = ("a coleta não trouxe motorista nenhum para este mês — nada foi "
                     "gravado, para o mês não ficar registrado como zero")
CORRENTE_VAZIO = {**PAINEL, "month": "2026-09", "parcial": True, "coletado_em": None,
                  "aviso": AVISO_DO_SERVIDOR, "linhas": [],
                  "kpis": {"premio_total": 0, "premiados": 0, "motoristas": 0, "km_total": 0}}


def _abrir(pg, base_url):
    pedidos: list[str] = []

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = ADMIN
        elif "/api/frota/premiacao/serie" in u:
            corpo = SERIE
        elif "/api/frota/premiacao" in u:
            pedidos.append(u)
            corpo = PAINEL if "mes=2026-08" in u else CORRENTE_VAZIO
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#prem")
    pg.wait_for_function("() => (document.getElementById('prem-aviso')||{}).textContent")
    return pedidos, erros


def test_a_ancora_no_ultimo_mes_diz_que_o_corrente_nao_tem_dado(pagina):
    pg, base_url = pagina
    pedidos, erros = _abrir(pg, base_url)
    assert any("mes=2026-08" in u for u in pedidos), "a tela não ancorou no último mês com dado"
    aviso = pg.inner_text("#prem-aviso")
    assert "09/2026 ainda não tem km nem nota na Gobrax" in aviso, aviso
    assert "mostrando Agosto / 2026, o último mês com dados" in aviso, aviso
    assert "não trouxe motorista nenhum" in aviso, "o motivo do servidor foi engolido"
    assert pg.eval_on_selector("#fPremMes", "e => e.value") == "2026-08"
    assert not erros, erros


def test_o_aviso_da_ancora_so_vale_no_mes_em_que_ela_pousou(pagina):
    """Escolher outro mês no seletor não pode carregar o aviso junto."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.evaluate("""() => { const s = document.getElementById('fPremMes');
        s.value = '2026-07'; s.dataset.pronto = '2'; loadPrem(); }""")
    pg.wait_for_function(
        "() => !document.getElementById('prem-aviso').textContent.includes('ainda não tem')")
