"""A tag de alerta na fila de agendamento de férias, contra o index.html real.

Pedido de quem opera (14/09/2026): marcar na fila quem está a 90 dias do
ÚLTIMO DIA PARA SAIR de férias — 30 dias que terminem no limite, porque dia
gozado depois dele é pago em dobro (Súmula 81 do TST). A REGRA é do servidor
(`queries_folha._linha`, campos `alerta`/`saida_ate`/`dias_saida`, guardada
em `tests/rh/test_ferias.py`); aqui se prova o que a pessoa VÊ: a tag com a
data de saída, a cor pela reta final, a saída que já venceu, o motivo quando
as férias marcadas não resolvem, e a contagem no hint.
"""
from __future__ import annotations

import json

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}


def _linha(nome, dias, limite, saida, alerta, agendado=False, gozo=(None, None),
           depois=False):
    return {"nome": nome, "chapa": "00" + str(abs(dias)), "funcao": "AUX",
            "filial": "MATRIZ", "admitido": "2023-01-01", "aquisitivo_fim": "2025-10-24",
            "limite": limite, "dias": dias, "saida_ate": saida, "dias_saida": dias - 29,
            "gozo_ini": gozo[0], "gozo_fim": gozo[1],
            "meses_2o": 10, "agendado": agendado, "agendado_depois": depois,
            "alerta": alerta,
            "estado": "dobra" if dias < 0 else "critica" if dias <= 30
                      else "atencao" if dias <= 90 else "ok"}


FILA = [
    _linha("GABI SAIDA VENCIDA", 10, "2026-09-24", "2026-08-26", True),
    _linha("ALICE RETA FINAL", 45, "2026-10-29", "2026-09-30", True),
    _linha("BETO TRES MESES", 100, "2026-12-23", "2026-11-24", True),
    _linha("CARLA AGENDOU A TEMPO", 40, "2026-10-24", "2026-09-25", False, True,
           ("2026-09-20", "2026-10-19")),
    _linha("DANI TERMINA DEPOIS", 40, "2026-10-24", "2026-09-25", True, True,
           ("2026-10-10", "2026-11-08"), depois=True),
    _linha("EDGAR FOLGADO", 200, "2027-04-02", "2027-03-04", False),
]
FER = {
    "dias": 90, "alerta_dias": 90, "colaboradores": [], "filtros": {}, "filiais": [],
    "agenda_mensal": [], "janela_futura": {"de": "2026-09-14", "ate": "2027-08-31"},
    "duplicadas": 0,
    "kpis": {"ativos": 6, "com_direito": 6, "sem_agenda": 4, "segundo_6": 6,
             "em_dobra": 0, "dobra_prazo": 4, "dobra_30": 1, "agendados": 2,
             "em_ferias_agora": 0, "ficha_parada": 0, "filiais": 1, "alerta": 4},
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


def _tag(pg, nome):
    return _linha_de(pg, nome).locator(".fer-alerta")


def test_a_tag_diz_o_ULTIMO_DIA_PARA_SAIR(tela):
    assert _tag(tela, "ALICE RETA FINAL").inner_text().strip() == "sair até 30/09"
    assert _tag(tela, "BETO TRES MESES").inner_text().strip() == "sair até 24/11"
    assert not tela.erros, tela.erros


def test_saida_que_ja_passou_com_o_limite_por_vir_diz_SAIDA_VENCIDA(tela):
    """30 dias já não cabem antes do limite: a tag não pode seguir mostrando
    uma data de saída que ficou para trás."""
    tag = _tag(tela, "GABI SAIDA VENCIDA")
    assert tag.inner_text().strip() == "saída vencida"
    assert "b-dang" in tag.get_attribute("class")
    assert "pago em DOBRO" in tag.get_attribute("title")


def test_fora_da_janela_e_agendado_a_tempo_NAO_levam_tag(tela):
    assert _tag(tela, "EDGAR FOLGADO").count() == 0
    carla = _linha_de(tela, "CARLA AGENDOU A TEMPO")
    assert carla.locator(".fer-alerta").count() == 0
    assert "já agendado" in carla.inner_text()


def test_a_cor_diz_a_RETA_FINAL_contada_da_SAIDA(tela):
    """Até 30 dias da saída, vermelha; de 31 a 90, âmbar. A ALICE está a 45
    dias do LIMITE e a 16 da SAÍDA: contada do limite ela seria âmbar."""
    assert "b-dang" in _tag(tela, "ALICE RETA FINAL").get_attribute("class")
    assert "b-warn" in _tag(tela, "BETO TRES MESES").get_attribute("class")


def test_ferias_que_TERMINAM_depois_do_limite_mantem_a_tag_e_dizem_por_que(tela):
    """Começar dentro do prazo não basta: dia gozado depois do limite sai em
    dobra, e "já agendado" daria por resolvido quem vai pagar essa ponta."""
    dani = _linha_de(tela, "DANI TERMINA DEPOIS")
    tag = dani.locator(".fer-alerta")
    assert tag.count() == 1
    assert "terminam em 08/11/2026" in tag.get_attribute("title")
    assert "DEPOIS do limite" in tag.get_attribute("title")
    assert "já agendado" not in dani.inner_text()


def test_a_linha_da_tag_ganha_o_destaque_e_as_outras_nao(tela):
    assert "fim2" in (_linha_de(tela, "BETO TRES MESES").get_attribute("class") or "")
    assert "fim2" not in (_linha_de(tela, "EDGAR FOLGADO").get_attribute("class") or "")
    assert "fim2" not in (_linha_de(tela, "CARLA AGENDOU A TEMPO").get_attribute("class") or "")


def test_o_hint_da_fila_CONTA_os_alertas(tela):
    assert "4 no alerta (saída em até 90 dias)" in tela.inner_text("#hintFerFila")
