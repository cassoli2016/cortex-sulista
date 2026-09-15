# -*- coding: utf-8 -*-
"""A tratativa da cobrança no index.html real: a coluna com a situação que o
SERVIDOR calculou, o resumo acima da tabela, o histórico ao abrir a linha e o
registro pelo modal — com o corpo que vai para a API conferido campo a campo.

Nomes e valores são de mentira — o repositório é público.
"""
from __future__ import annotations

import json
import re

from api.financeiro.cobranca_tratativa import CANAIS, TIPOS
from tests.frontend.test_cob_agrupamento_e2e import ADMIN, COB, _ir, _txt

REF_G, REF_A = "a" * 16, "b" * 16


def _ultima(id_, tipo, descricao, em, **kw):
    return {"id": id_, "tipo": tipo, "tipo_rotulo": TIPOS[tipo], "canal": kw.get("canal"),
            "canal_rotulo": CANAIS.get(kw.get("canal")) if kw.get("canal") else None,
            "descricao": descricao, "promessa_data": kw.get("p"),
            "promessa_valor": kw.get("pv"), "retorno_em": kw.get("r"),
            "titulos": kw.get("titulos", []), "vencido_ref": kw.get("vref", 350.0),
            "titulos_ref": 3, "autor_nome": "Ana Cobrança", "em": em}


HIST = [
    _ultima(2, "promessa", "Prometeu pagar as duas notas do Norte.",
            "2026-09-10T16:20:00-03:00", p="2026-09-12", pv=200.0,
            titulos=["101/1", "102/1"]),
    _ultima(1, "contato", "Falei com o financeiro deles.", "2026-09-08T09:05:00-03:00",
            canal="ligacao"),
]
NOVA = {"estado": "promessa", "nivel": "good", "rotulo": "promessa para 30/09", "total": 3,
        "ultima": _ultima(3, "promessa", "Nova promessa.", "2026-09-15T10:00:00-03:00",
                          p="2026-09-30"),
        "vencido_novo": None}


def _payload():
    d = json.loads(json.dumps(COB))
    g, a = d["clientes"]
    g["ref"], a["ref"] = REF_G, REF_A
    g["tratativa"] = {"estado": "promessa_vencida", "nivel": "bad",
                      "rotulo": "promessa vencida em 12/09", "total": 2,
                      "ultima": HIST[0], "vencido_novo": 150.0}
    a["tratativa"] = {"estado": "sem_tratativa", "nivel": "warn", "rotulo": "sem tratativa",
                      "total": 0, "ultima": None, "vencido_novo": None}
    d["tratativas"] = {"disponivel": True, "tipos": TIPOS, "canais": CANAIS, "parada_dias": 7,
                       "contagem": {"sem_tratativa": 1, "promessa_vencida": 1,
                                    "retorno_atrasado": 0, "parada": 0},
                       "valor": {"sem_tratativa": 460.0, "promessa_vencida": 500.0,
                                 "retorno_atrasado": 0.0, "parada": 0.0}}
    return d


def _montar(pg, posts, resposta_post=(200, {"ok": True, "entrada": NOVA["ultima"],
                                            "tratativa": NOVA})):
    def rota(route):
        req = route.request
        u = req.url
        if "/api/financeiro/cobranca/tratativas" in u and req.method == "POST":
            posts.append(json.loads(req.post_data))
            status, corpo = resposta_post
        elif "/api/financeiro/cobranca/tratativas" in u:
            status, corpo = 200, {"ref": REF_G, "historico": HIST}
        elif "/api/financeiro/cobranca" in u:
            status, corpo = 200, _payload()
        elif "/api/auth/me" in u:
            status, corpo = 200, ADMIN
        else:
            status, corpo = 200, {}
        route.fulfill(status=status, content_type="application/json", body=json.dumps(corpo))
    pg.route("**/api/**", rota)


def _abrir_linha_do_grupo(pg):
    pg.click("#cob-cli tr.forn-row >> nth=0")
    pg.wait_for_function("(document.querySelector('#cob-trat-hist-0')||{}).textContent"
                         "?.includes('Falei com o financeiro')", timeout=10000)


def test_a_coluna_e_o_resumo_mostram_a_situacao_do_servidor(pagina):
    pg, base = pagina
    _montar(pg, [])
    _ir(pg, base, "cob")
    assert "Tratativa" in _txt(pg, "#view-cob thead")
    grupo = _txt(pg, "#cob-trat-cel-0")
    assert "promessa vencida em 12/09" in grupo, grupo
    # o BRL da casa separa "R$" do número com espaço INQUEBRÁVEL
    assert re.search(r"\+R\$\s150(?!\d)", grupo), grupo
    assert "sem tratativa" in _txt(pg, "#cob-trat-cel-1")
    resumo = _txt(pg, "#cob-trat-resumo")
    assert "1 com promessa vencida" in resumo and "1 sem tratativa" in resumo


def test_abrir_a_linha_traz_o_historico_INTEIRO_do_mais_novo_ao_mais_antigo(pagina):
    pg, base = pagina
    _montar(pg, [])
    _ir(pg, base, "cob")
    _abrir_linha_do_grupo(pg)
    hist = _txt(pg, "#cob-trat-hist-0")
    assert hist.index("Prometeu pagar") < hist.index("Falei com o financeiro")
    assert "Ana Cobrança" in hist and "Ligação" in hist
    assert "títulos 101/1, 102/1" in hist and "vencido no registro" in hist


def test_registrar_promessa_pelo_modal_manda_o_corpo_certo_e_repinta(pagina):
    pg, base = pagina
    posts: list = []
    _montar(pg, posts)
    _ir(pg, base, "cob")
    _abrir_linha_do_grupo(pg)
    pg.click("#cob-det-0 .cob-trat-head button")
    pg.wait_for_selector("#modalBg.aberto")
    assert not pg.is_visible("#ct-prom"), "data e valor prometidos só aparecem para promessa"
    pg.select_option("#ct-tipo", "promessa")
    assert pg.is_visible("#ct-prom")
    pg.fill("#ct-desc", "Ligou o gerente e prometeu quitar o Sul no dia 30.")
    pg.fill("#ct-pdata", "2026-09-30")
    pg.fill("#ct-pvalor", "1.234,56")
    pg.check(".ct-tits input[value='103/1']")
    pg.click("#ct-salvar")
    pg.wait_for_selector("#modalBg.aberto", state="hidden")
    assert posts == [{"ref": REF_G, "tipo": "promessa", "canal": None,
                      "descricao": "Ligou o gerente e prometeu quitar o Sul no dia 30.",
                      "retorno_em": None, "titulos": ["103/1"],
                      "promessa_data": "2026-09-30", "promessa_valor": 1234.56}]
    assert "promessa para 30/09" in _txt(pg, "#cob-trat-cel-0")
    assert "1 com promessa vencida" not in _txt(pg, "#cob-trat-resumo")


def test_a_recusa_do_servidor_aparece_no_modal_que_fica_aberto(pagina):
    pg, base = pagina
    msg = "Promessa de pagamento precisa da data prometida."
    _montar(pg, [], resposta_post=(409, {"erro": "recusado", "mensagem": msg}))
    _ir(pg, base, "cob")
    _abrir_linha_do_grupo(pg)
    pg.click("#cob-det-0 .cob-trat-head button")
    pg.wait_for_selector("#modalBg.aberto")
    pg.select_option("#ct-tipo", "promessa")
    pg.fill("#ct-desc", "Sem data.")
    pg.click("#ct-salvar")
    pg.wait_for_function("(document.getElementById('m-err')||{}).textContent", timeout=5000)
    assert _txt(pg, "#m-err") == msg
    assert pg.is_visible("#modalBg.aberto")
