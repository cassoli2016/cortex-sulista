"""A tag ALERTA 90 DIAS na fila de agendamento de férias, contra o index.html real.

Pedido de quem opera (14/09/2026): marcar na fila quem fecha o 2º período — e,
na mesma data, paga o 1º em dobra — em até 90 dias. A REGRA é do servidor
(`queries_folha._linha`, campo `alerta`, guardada em `tests/rh/test_ferias.py`);
aqui se prova o que a pessoa VÊ: a tag na linha certa, a cor pela reta final,
o motivo quando as férias marcadas não resolvem, e a contagem no hint.
"""
from __future__ import annotations

import json

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}


def _linha(nome, dias, limite, alerta, agendado=False, gozo_ini=None, depois=False):
    return {"nome": nome, "chapa": "00" + str(abs(dias)), "funcao": "AUX",
            "filial": "MATRIZ", "admitido": "2023-01-01", "aquisitivo_fim": "2025-10-24",
            "limite": limite, "dias": dias, "gozo_ini": gozo_ini, "gozo_fim": None,
            "meses_2o": 10, "agendado": agendado, "agendado_depois": depois,
            "alerta": alerta,
            "estado": "dobra" if dias < 0 else "critica" if dias <= 30
                      else "atencao" if dias <= 90 else "ok"}


FILA = [
    _linha("ALICE RETA FINAL", 20, "2026-10-04", True),
    _linha("BETO TRES MESES", 75, "2026-11-28", True),
    _linha("CARLA AGENDOU A TEMPO", 40, "2026-10-24", False, True, "2026-10-01"),
    _linha("DANI AGENDOU TARDE", 40, "2026-10-24", True, True, "2026-11-10", depois=True),
    _linha("EDGAR FOLGADO", 200, "2027-04-02", False),
]
FER = {
    "dias": 90, "alerta_dias": 90, "colaboradores": [], "filtros": {}, "filiais": [],
    "agenda_mensal": [], "janela_futura": {"de": "2026-09-14", "ate": "2027-08-31"},
    "duplicadas": 0,
    "kpis": {"ativos": 5, "com_direito": 5, "sem_agenda": 3, "segundo_6": 5,
             "em_dobra": 0, "dobra_prazo": 4, "dobra_30": 1, "agendados": 2,
             "em_ferias_agora": 0, "ficha_parada": 0, "filiais": 1, "alerta": 3},
    "por_filial": [], "fila": FILA, "agenda": [], "fichas_paradas": [],
    "fonte": "t", "atualizado_em": "2026-09-14 09:00",
}


@pytest.fixture()
def tela(pagina):
    pg, base_url = pagina

    def rota(route):
        u = route.request.url
        c = (ADMIN if "/api/auth/me" in u
             else {} if "/ferias/custo" in u
             else FER if "/api/rh/ferias" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(c, ensure_ascii=False))

    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.route("**/api/**", rota)
    pg.goto(base_url + "/static/index.html#ferias")
    pg.wait_for_selector("#fer-fila tr", timeout=20000)
    pg.erros = erros
    return pg


def _linha_de(pg, nome):
    return pg.locator(f"#fer-fila tr:has-text('{nome}')")


def test_quem_fecha_o_2o_em_ate_90_dias_leva_a_TAG(tela):
    for nome in ("ALICE RETA FINAL", "BETO TRES MESES"):
        tag = _linha_de(tela, nome).locator(".fer-alerta")
        assert tag.count() == 1, f"{nome} sem a tag"
        assert tag.inner_text().strip() == "alerta 90 dias"
    assert not tela.erros, tela.erros


def test_fora_da_janela_e_agendado_a_tempo_NAO_levam_tag(tela):
    assert _linha_de(tela, "EDGAR FOLGADO").locator(".fer-alerta").count() == 0
    carla = _linha_de(tela, "CARLA AGENDOU A TEMPO")
    assert carla.locator(".fer-alerta").count() == 0
    assert "já agendado" in carla.inner_text()


def test_a_cor_diz_a_RETA_FINAL(tela):
    """Até 30 dias vermelha; de 31 a 90, âmbar — a mesma régua da coluna Prazo."""
    assert "b-dang" in _linha_de(tela, "ALICE RETA FINAL").locator(".fer-alerta").get_attribute("class")
    assert "b-warn" in _linha_de(tela, "BETO TRES MESES").locator(".fer-alerta").get_attribute("class")


def test_ferias_marcadas_DEPOIS_do_limite_mantem_a_tag_e_dizem_por_que(tela):
    """"Já agendado" daria por resolvido justamente quem vai custar o dobro."""
    dani = _linha_de(tela, "DANI AGENDOU TARDE")
    tag = dani.locator(".fer-alerta")
    assert tag.count() == 1
    assert "DEPOIS do limite" in tag.get_attribute("title")
    assert "já agendado" not in dani.inner_text()


def test_a_linha_da_tag_ganha_o_destaque_e_as_outras_nao(tela):
    assert "fim2" in (_linha_de(tela, "BETO TRES MESES").get_attribute("class") or "")
    assert "fim2" not in (_linha_de(tela, "EDGAR FOLGADO").get_attribute("class") or "")
    assert "fim2" not in (_linha_de(tela, "CARLA AGENDOU A TEMPO").get_attribute("class") or "")


def test_o_hint_da_fila_CONTA_os_alertas(tela):
    assert "3 no alerta de 90 dias" in tela.inner_text("#hintFerFila")
