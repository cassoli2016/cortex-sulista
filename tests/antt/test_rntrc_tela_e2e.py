"""A tela do RNTRC contra o index.html real, com payload do serviço."""
from __future__ import annotations

import json
from pathlib import Path

from api.antt.rntrc_servico import conferir, ordenar, resumir
from tests.frontend.conftest import USUARIO

HTML = Path(__file__).resolve().parent.parent.parent / "api" / "static" / "index.html"
S = HTML.read_text(encoding="utf-8")

BASE = {"7600540": {"rntrc": "7600540", "situacao": "ATIVO", "categoria": "ETC",
                    "uf": "SP", "nome": "ALFA", "data_situacao": "01/07/2026"},
        "6242260": {"rntrc": "6242260", "situacao": "PENDENTE", "categoria": "TAC",
                    "uf": "RS", "nome": "JOAO", "data_situacao": "28/08/2025"}}

CONTRATADOS = [
    {"codigo": "C1", "rntrc": "07600540", "nome": "TRANSPORTES ALFA",
     "pessoa": "PJ", "viagens": 320, "pago": 525863.0, "ultima_viagem": "2026-08-01"},
    {"codigo": "C2", "rntrc": "006242260", "nome": "JOAO DA SILVA",
     "pessoa": "PF", "viagens": 603, "pago": 1058578.0, "ultima_viagem": "2026-08-10"},
    {"codigo": "C3", "rntrc": "9999999", "nome": "SUMIDO LTDA",
     "pessoa": "PJ", "viagens": 85, "pago": 184169.0, "ultima_viagem": "2026-07-20"},
]


def test_view_registrada_no_roteador_e_nos_mapas():
    bloco = S.split("const VIEWS = {", 1)[1].split("};", 1)[0]
    assert "anrntrc:" in bloco
    assert "anrntrc:loadAnrntrc" in S
    assert "anrntrc:DATAANRNTRC" in S


def test_tela_entra_no_menu_e_na_gaveta():
    assert 'data-view="anrntrc"' in S
    drawer = S.split('<div class="drawer"', 1)[1]
    assert 'href="#anrntrc"' in drawer


def test_a_tela_recorta_pelo_periodo_compartilhado():
    """A barra aparece PORQUE agora ela tem campo.

    O teste anterior exigia o contrário, e a razão dele era boa: "o período é
    fixo em 12 meses; barra sem campo confunde". Repare na premissa — a barra
    era escondida por estar VAZIA, que é o mesmo defeito que a Validação de
    Pedágio tinha, resolvido pelo outro lado.

    Em 31/08/2026 a tela passou a recortar por período, com os MESMOS campos do
    Piso Mínimo: são duas telas da ANTT sobre a mesma viagem contratada, e
    vocabulário diferente faria o usuário achar que o recorte mudou ao trocar
    de tela. A rota já aceitava `dt_de`/`dt_ate` desde sempre, e o padrão de 12
    meses continua valendo quando os campos estão vazios.
    """
    bloco = S.split("function semFilterbar(v){", 1)[1].split("\n}", 1)[0]
    assert "anrntrc" not in bloco, "a barra voltou a ser escondida nesta tela"
    # e o que a tela MANDA tem de chegar na rota, senão o filtro é enfeite
    qs = S.split("function qsView(k){", 1)[1]
    trecho = qs.split("k==='anrntrc'", 1)[1].split("} else if", 1)[0]
    assert "dt_de" in trecho and "dt_ate" in trecho


def _abrir(pg, base_url):
    conf = ordenar(conferir(CONTRATADOS, BASE))
    dados = {"kpis": resumir(conf), "transportadores": conf,
             "sync": {"competencia": "2026-07", "quando": "2026-08-18 10:00",
                      "linhas": 3},
             "dt_de": "2025-08-18", "dt_ate": "2026-08-18", "fonte": "teste"}

    def rota(route):
        u = route.request.url
        corpo = USUARIO if "/api/auth/me" in u else (
            dados if "antt/rntrc" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#anrntrc")
    pg.wait_for_selector("#kpis-anrntrc .kpi", timeout=20000)
    return dados, erros


def test_tela_abre_sem_erro_de_javascript(pagina):
    pg, base = pagina
    _, erros = _abrir(pg, base)
    assert erros == []


def test_quatro_kpis_com_o_valor_em_risco(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert pg.eval_on_selector_all("#kpis-anrntrc .kpi", "e=>e.length") == 4
    assert "1.242.747" in pg.inner_text("#kpis-anrntrc")  # 1.058.578 + 184.169


def test_quem_esta_em_risco_aparece_primeiro(pagina):
    pg, base = pagina
    _abrir(pg, base)
    primeira = pg.inner_text("#anrntrc-lista tr")
    assert "JOAO DA SILVA" in primeira   # maior valor entre os de risco


def test_situacao_tem_rotulo_humano(pagina):
    pg, base = pagina
    _abrir(pg, base)
    texto = pg.inner_text("#anrntrc-lista")
    assert "pendente" in texto
    assert "fora da base" in texto
    assert "sem_base" not in texto


def test_tela_mostra_a_competencia_da_base(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert "2026-07" in pg.inner_text("#anrntrc-sync")
