"""A página inicial (Radar do Transporte) contra o index.html real.

O DUBLÊ DA ROTA É A SAÍDA REAL DO PAINEL: `radar_payload.json` foi gerado
rodando `api.radar.painel.painel()` sobre as amostras de `tests/radar/dados`
(os corpos que ANP, Yahoo, Banco Central, Google e TomTom devolveram em
11/09/2026), e `tests/radar/test_registro_e_agendador.py` confere que as chaves
dele continuam sendo as da rota. Payload escrito à mão aqui provaria que a
tela lê o que o teste inventou.

E A RÉGUA DE ALTURA RODA COM ESTE PAYLOAD CHEIO, não com o `{}` do
`medir_paineis`: a aba Decidir passava com 854px no esqueleto e ia a 1.303px
com os doze meses reais.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from tests.frontend.conftest import USUARIO

PAYLOAD = json.loads((Path(__file__).parent / "radar_payload.json").read_text(encoding="utf-8"))

#: Quem não tem perfil nenhum — e é para essa pessoa que a página existe.
SEM_PERFIL = {**USUARIO, "admin": False, "perfil": "Operacao", "telas": []}


def _abrir(pg, base_url, quem=USUARIO, payload=None, hash_="#radar"):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = quem
        elif "/api/radar" in u:
            corpo = PAYLOAD if payload is None else payload
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html{hash_}")
    pg.wait_for_selector("#kpis-radar .kpi", timeout=20000)
    return erros


def test_os_quatro_cartoes_trazem_o_numero_e_a_comparacao(pagina):
    pg, base = pagina
    erros = _abrir(pg, base)
    txt = pg.inner_text("#kpis-radar")
    assert "R$ 6,88/l" in txt and "R$ 6,47/l" in txt
    assert "US$ 103,68" in txt and "R$ 5,0949" in txt
    assert "PTAX" in txt, "a PTAX oficial viaja ao lado do dólar de agora"
    assert pg.locator("#kpis-radar .kpi").count() == 4
    assert pg.locator("#kpis-radar .trend").count() >= 3, "número-chave sem comparação"
    assert not erros, erros


def test_os_dois_graficos_desenham_com_largura_de_verdade(pagina):
    pg, base = pagina
    _abrir(pg, base)
    for alvo in ("#chartRadarDiesel svg", "#chartRadarBrent svg"):
        pg.wait_for_selector(alvo, timeout=20000)
        assert pg.locator(alvo).bounding_box()["width"] > 200, alvo


def test_a_noticia_abre_NO_VEICULO_em_outra_aba(pagina):
    pg, base = pagina
    _abrir(pg, base)
    esperado = len(PAYLOAD["noticias"]["trc"]["itens"])
    links = pg.locator("#rd-feed-trc a.rd-item")
    assert links.count() == esperado > 0
    for i in range(links.count()):
        a = links.nth(i)
        assert a.get_attribute("target") == "_blank"
        assert "noopener" in (a.get_attribute("rel") or "")
        assert (a.get_attribute("href") or "").startswith("https://")


def test_a_aba_diz_quantas_manchetes_tem_sem_precisar_entrar(pagina):
    pg, base = pagina
    _abrir(pg, base)
    for tema in ("trc", "diesel", "reforma", "antt"):
        total = PAYLOAD["noticias"][tema]["total"]
        assert pg.inner_text(f"#rd-n-{tema}") == (str(total) if total else "")


def test_a_rodovia_fechada_aparece_com_o_corredor(pagina):
    pg, base = pagina
    _abrir(pg, base)
    lista = pg.inner_text("#rd-rod-lista")
    assert "BR-101" in lista and "Via fechada" in lista
    assert "Curitiba" in lista
    assert pg.inner_text("#rd-n-rodoc") == str(len(PAYLOAD["rodovias"]["itens"]))


def test_o_piso_da_ANTT_mostra_a_resolucao_vigente(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert "6.084/2026" in pg.inner_text("#rd-antt-hint")
    assert pg.locator("#rd-antt tbody tr").count() == 4


# ---------------------------------------------------- a página de TODO mundo

def test_quem_nao_tem_perfil_nenhum_ENTRA_pela_pagina_inicial(pagina):
    """Sem hash, sem perfil: antes, quem não tinha a Visão Geral caía na
    primeira tela da lista em que tivesse acesso."""
    pg, base = pagina
    erros = _abrir(pg, base, quem=SEM_PERFIL, hash_="")
    assert "on" in (pg.get_attribute("#view-radar", "class") or "")
    assert pg.is_visible('nav a[data-view="radar"]')
    assert pg.is_visible('nav a[data-view="apps"]'), (
        "a tela Aplicativos é de todo usuário logado e sumia do menu de quem "
        "não é administrador")
    assert not pg.is_visible('nav a[data-view="home"]')
    assert not erros, erros


# ------------------------------------------------------------ a honestidade

def test_fonte_atrasada_ACENDE_a_tarja_dizendo_qual(pagina):
    pg, base = pagina
    p = copy.deepcopy(PAYLOAD)
    p["coleta"]["brent"].update(estado="erro", ok=False, erro="HTTPError 429")
    _abrir(pg, base, payload=p)
    pg.wait_for_selector("#rd-tarja:not([hidden])", timeout=5000)
    t = pg.inner_text("#rd-tarja")
    assert "Brent (Yahoo)" in t and "HTTPError 429" in t
    assert "t-dang" in (pg.get_attribute("#rd-tarja", "class") or "")


def test_tudo_em_dia_NAO_mostra_tarja(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert pg.locator("#rd-tarja").is_hidden()


def test_sem_TomTom_a_aba_de_ocorrencias_explica_e_nao_finge_estrada_livre(pagina):
    pg, base = pagina
    p = copy.deepcopy(PAYLOAD)
    p["rodovias"].update(configurado=False, itens=[], bloqueios=0)
    _abrir(pg, base, payload=p)
    assert "TomTom não está configurada" in pg.inner_text("#rd-rod-lista")


def test_passada_a_revisao_da_ANTT_a_tela_pede_conferencia(pagina):
    pg, base = pagina
    p = copy.deepcopy(PAYLOAD)
    p["antt"]["revisao_vencida"] = True
    _abrir(pg, base, payload=p)
    assert pg.locator("#rd-antt .toast.t-warn").count() == 1


# -------------------------------------------------------------- a régua

_ALTURA = ("() => { const c = document.getElementById('content'); if(!c) return 0;"
           " const b = c.querySelector('#banner');"
           " const fora = (b && b.offsetParent !== null) ? Math.round(b.getBoundingClientRect().height) + 14 : 0;"
           " return Math.round(c.scrollHeight) - fora; }")
_LADO = "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"


def test_cabe_em_UMA_tela_com_o_payload_cheio(pagina):
    pg, base = pagina
    pg.set_viewport_size({"width": 1500, "height": 1000})
    _abrir(pg, base)
    pg.wait_for_selector("#chartRadarBrent svg", timeout=20000)
    altura = pg.evaluate(_ALTURA)
    assert altura <= 900, f"a página inicial tem {altura}px com dado real — a régua é 900"
    assert pg.evaluate(_LADO) == 0, "a página rola para o lado"


def test_no_celular_nao_rola_para_o_lado(pagina):
    pg, base = pagina
    pg.set_viewport_size({"width": 400, "height": 860})
    _abrir(pg, base)
    assert pg.evaluate(_LADO) == 0
