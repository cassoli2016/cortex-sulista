# -*- coding: utf-8 -*-
"""O painel de TV do RH (`tvrh`) no navegador.

O dublê de segurança sai da própria `montar_seguranca`, e o resto tem a forma
de `api/rh/tv.painel`. Nomes inventados. As listas vêm no TETO REAL: 28
desligamentos num mês (nov/2025, o pico medido) e 12 admissões — o que um dia
comum não mostra é o que decide se o cartão corta e conta ou estoura.
"""
from __future__ import annotations

import copy
import json
from datetime import date

import pytest

from api.rh import tv
from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
HOJE = date.today()


def _pessoas(n, prefixo):
    return [{"nome": f"{prefixo} Pessoa Numero {i:02d} da Silva", "filial": "Matriz",
             "funcao": "Motorista Carreteiro", "data": HOJE.replace(day=1).isoformat(),
             "dia": min(28, HOJE.day + 1 + i % 6)} for i in range(n)]


def _payload():
    mes = HOJE.strftime("%Y-%m")
    ult = tv._meses(HOJE)[8]                       # os 3 últimos meses sem lançamento
    linhas = [{"mes": m, "indicador": 7, "acidentes": (i % 3), "classificacao": 1,
               "reclamacoesclientes": None} for i, m in enumerate(tv._meses(HOJE))]
    linhas += [{"mes": m, "indicador": 16, "acidentes": None, "classificacao": None,
                "reclamacoesclientes": i % 4} for i, m in enumerate(tv._meses(HOJE))]
    serie = [{"mes": m, "pct": 2.5 + i / 3, "parcial": m == mes} for i, m in enumerate(tv._meses(HOJE))]
    return json.loads(json.dumps({
        "hoje": HOJE.isoformat(),
        "gente": {"ativos": 194, "afastados": 14, "genero": {"masculino": 147, "feminino": 47},
                  "lideranca": {"lideres": 16, "colaboradores": 178},
                  "tempo_casa": [{"faixa": "Até 1 ano", "n": 18}, {"faixa": "1 a 3 anos", "n": 87},
                                 {"faixa": "3 a 5 anos", "n": 29}, {"faixa": "Mais de 5 anos", "n": 60}],
                  "por_filial": [{"filial": "Matriz", "n": 83}, {"filial": "SBC", "n": 59},
                                 {"filial": "Cruzeiro", "n": 32}, {"filial": "Joinville", "n": 16},
                                 {"filial": "Pouso Alegre", "n": 4}],
                  "por_departamento": [{"departamento": "Operacional", "n": 83},
                                       {"departamento": "Motorista", "n": 82},
                                       {"departamento": "Administrativo", "n": 29}]},
        "mes": {"mes": mes,
                "aniversariantes": {"total": 17, "hoje": _pessoas(3, "Hoje"),
                                    "proximos_7": _pessoas(9, "Prox")},
                "admitidos": _pessoas(12, "Adm"), "desligados": _pessoas(28, "Desl"),
                "tempo_de_casa": [{"nome": f"Casa {i}", "filial": "SBC", "dia": 3, "anos": a}
                                  for i, a in enumerate((20, 10, 5, 5, 1, 1, 1, 1, 1, 1))]},
        "seguranca": tv.montar_seguranca(linhas, {7: ult, 16: ult}, HOJE, fatais=[]),
        "indicadores": {
            "turnover": {"serie": [{**s, "admissoes": 3, "desligamentos": 8} for s in serie], "ativos": 194},
            "absenteismo": {"serie": serie},
            "banco_horas": {"credor_h": 1158.2, "credores": 45, "devedor_h": -965.1, "devedores": 45,
                            "liquido_h": 193.1, "pessoas": 98},
            "hora_extra": {"competencia": "2026-08", "horas": 5988.6, "pessoas": 150},
            "ferias": {"em_dobra": 1, "alerta": 2, "em_ferias": 10},
            "cnh": {"vencidas": 0, "vence_30": 1},
            "experiencia": {"vencendo": 4, "em_experiencia": 9, "aviso_dias": 15}},
    }, default=str))


def _abre(pagina, largura=1920, altura=1080, payload=None):
    pg, base = pagina
    corpo = payload or _payload()

    def rota(r):
        u = r.request.url
        dado = ADMIN if "/api/auth/me" in u else (corpo if "/api/rh/tv" in u else {})
        r.fulfill(status=200, content_type="application/json", body=json.dumps(dado))
    pg.route("**/api/**", rota)
    pg.emulate_media(reduced_motion="reduce")
    pg.set_viewport_size({"width": largura, "height": altura})
    pg.goto(base + "/static/index.html#tvrh")
    pg.wait_for_selector("#tvrh-colab .tv-num")
    pg.wait_for_timeout(600)
    assert pg.evaluate("!!tvTour"), "o giro das lâminas não foi armado"
    pg.evaluate("clearInterval(tvTour)")
    return pg


# o cartão E a lista: a lista encolhe e esconde linha sem transbordar o
# cartão — medir só o cartão aprovou o corte calado na primeira versão
TRANSBORDA = """(r) => [...document.querySelectorAll('#' + r + ' .tv-card, #' + r + ' .tv-rh-lista')]
    .filter(c => c.scrollHeight > c.clientHeight + 2).map(c => c.id || c.closest('.tv-card').id)"""


@pytest.mark.parametrize("largura,altura", [(1920, 1080), (1600, 900)])
def test_as_tres_laminas_cabem_na_tv(pagina, largura, altura):
    pg = _abre(pagina, largura, altura)
    assert pg.evaluate("document.body.classList.contains('tvwall')")
    for i, raiz in enumerate(("tvrh-l1", "tvrh-l2", "tvrh-l3")):
        pg.evaluate(f"TVRH_IDX={i}; tvRhMostrar()")
        pg.wait_for_timeout(200)
        assert pg.evaluate(TRANSBORDA, raiz) == [], raiz
    assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
    assert pg.evaluate("document.documentElement.scrollHeight - document.documentElement.clientHeight") <= 0


def test_os_numeros_da_tv_antiga_chegam(pagina):
    pg = _abre(pagina)
    assert "194" in pg.inner_text("#tvrh-colab") and "14" in pg.inner_text("#tvrh-colab")
    filial = pg.inner_text("#tvrh-filial")
    assert "Matriz" in filial and "83" in filial and "Joinville" in filial
    assert "75,8%" in pg.inner_text("#tvrh-genero")


def test_com_vitima_fatal_vem_do_registro_e_diz_quando_nao_da_para_ler(pagina):
    pg = _abre(pagina)
    txt = pg.inner_text("#tvrh-acid-com")
    assert "vítima fatal" in txt.lower() and "registro do CÓRTEX" in txt and "lançado até" not in txt
    assert pg.evaluate("document.querySelectorAll('#tvrh-acid-com .tvd-col.sem').length") == 0


def test_registro_de_morte_ilegivel_diz_e_nao_mostra_zero(pagina):
    p = _payload()
    p["seguranca"] = tv.montar_seguranca([], {7: "2026-06", 16: "2026-06"}, HOJE, fatais=None)
    pg2 = _abre(pagina, payload=json.loads(json.dumps(p)))
    txt = pg2.inner_text("#tvrh-acid-com")
    assert "registro indisponível" in txt
    # sem registro legível o número é travessão, nunca um zero que ninguém mediu
    assert pg2.inner_text("#tvrh-acid-com .tv-num").strip() == "—"


def test_mes_sem_lancamento_e_travessao_e_o_rodape_diz_ate_quando(pagina):
    pg = _abre(pagina)
    for card in ("tvrh-acid-sem", "tvrh-rnc"):
        assert pg.evaluate(f"document.querySelectorAll('#{card} .tvd-col.sem').length") == 3, card
    assert "lançado até" in pg.inner_text("#tvrh-acid-sem")
    assert "lançados pela Qualidade até" in pg.inner_text("#tvrh-ticker")


def test_lista_longa_corta_e_conta(pagina):
    """28 desligamentos não cabem: o cartão mostra os que cabem e diz quantos
    ficaram de fora — e o número grande continua sendo 28."""
    pg = _abre(pagina)
    pg.evaluate("TVRH_IDX=1; tvRhMostrar()")
    txt = pg.inner_text("#tvrh-desl")
    assert "28" in txt
    visiveis = pg.evaluate("document.querySelectorAll('#tvrh-desl .tv-rh-lista > div:not(.tv-rh-mais)').length")
    assert 1 <= visiveis < 28
    assert f"e mais {28 - visiveis}" in txt


def test_a_parede_nao_mostra_dinheiro(pagina):
    pg = _abre(pagina)
    assert "R$" not in pg.inner_text("#view-tvrh")


def test_o_giro_passa_pelas_tres_laminas(pagina):
    pg = _abre(pagina)
    vistos = []
    for _ in range(3):
        vistos.append(pg.inner_text("#tvrh-lamina"))
        pg.evaluate("tvRhPasso()")
    assert vistos == ["Gente Sulista", "Segurança, qualidade e gente", "Indicadores de gente"]


def test_bloco_indisponivel_nao_apaga_a_parede(pagina):
    p = _payload()
    p["mes"] = {"erro": "indisponivel"}
    p["indicadores"]["turnover"] = {"erro": "indisponivel"}
    pg = _abre(pagina, payload=copy.deepcopy(p))
    assert "194" in pg.inner_text("#tvrh-colab")
    assert "indisponível" in pg.inner_text("#tvrh-desl")
    assert "indisponível" in pg.inner_text("#tvrh-turn")
    assert "RNC" in pg.inner_text("#tvrh-rnc")


def test_esta_no_submenu_de_paineis_e_na_gaveta(pagina):
    pg = _abre(pagina)
    assert pg.evaluate("!!document.querySelector('#subsTvGes a[href=\"#tvrh\"] .ic svg')")
    assert pg.evaluate("!!document.querySelector('.drawer a[href=\"#tvrh\"]')")


def test_no_celular_as_laminas_empilham_sem_cortar_nem_rolar_de_lado(pagina):
    """16/09/2026: "não encontrei no mobile". No celular não há carrossel: as
    três lâminas empilham, o link está na gaveta, e nenhum rótulo sai cortado."""
    pg = _abre(pagina, 390, 844)
    assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
    assert pg.evaluate("!!document.querySelector('.drawer a[href=\"#tvrh\"]')")
    visiveis = pg.evaluate("""() => ['tvrh-colab','tvrh-rnc','tvrh-turn'].map(id => {
        const r = document.getElementById(id).getBoundingClientRect(); return r.width > 300 && r.height > 100; })""")
    assert visiveis == [True, True, True], visiveis
    # mede com a fonte DA CASA: com a de reserva (mais estreita) o rótulo
    # cabia em 90 px e o guard aprovava o corte que a TV real mostra
    pg.evaluate("document.fonts.ready.then(() => true)")
    cortados = pg.evaluate("""() => [...document.querySelectorAll('#view-tvrh .tv-rh-bar b')]
        .filter(e => e.scrollWidth > e.clientWidth).map(e => e.textContent)   // 1 px já vira reticências""")
    assert cortados == [], cortados


CARTOES = ("tvrh-colab", "tvrh-filial", "tvrh-genero", "tvrh-tempo", "tvrh-depto", "tvrh-lider",
           "tvrh-acid-com", "tvrh-acid-sem", "tvrh-rnc", "tvrh-aniv", "tvrh-aniv-dia", "tvrh-adm",
           "tvrh-desl", "tvrh-turn", "tvrh-abs", "tvrh-pend", "tvrh-banco", "tvrh-he", "tvrh-casa")
SEM_ICONE = """(ids) => ids.filter(id => !document.querySelector('#' + id + ' .tv-label .tv-rh-ic svg'))"""


def test_todo_cartao_tem_o_seu_icone(pagina):
    """Pedido de quem opera (16/09/2026): ícones de acordo com o assunto. A
    lista de cartões é a da SEÇÃO, conferida contra o DOM — cartão novo sem
    ícone reprova aqui."""
    pg = _abre(pagina)
    no_dom = pg.evaluate("[...document.querySelectorAll('#view-tvrh .tv-card[id]')].map(c => c.id)")
    assert sorted(no_dom) == sorted(CARTOES), no_dom
    assert pg.evaluate(SEM_ICONE, list(CARTOES)) == []
    # um ícone por cartão, mesmo depois da recarga de 60 s redesenhar tudo
    pg.evaluate("loadTvRh()")
    pg.wait_for_timeout(500)
    assert pg.evaluate("document.querySelectorAll('#view-tvrh .tv-rh-ic').length") == len(CARTOES)


def test_cartao_indisponivel_tambem_tem_icone(pagina):
    p = _payload()
    p["mes"] = {"erro": "indisponivel"}
    p["indicadores"]["turnover"] = {"erro": "indisponivel"}
    pg = _abre(pagina, payload=json.loads(json.dumps(p)))
    assert pg.evaluate(SEM_ICONE, ["tvrh-desl", "tvrh-turn", "tvrh-casa"]) == []

