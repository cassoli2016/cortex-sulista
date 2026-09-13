# -*- coding: utf-8 -*-
"""O cartão da Saúde é função pura sobre o diagnóstico, e cada limiar pede a
PRÓPRIA sabotagem (parâmetro é guard); o snapshot do Copiloto leva só
escalares — nenhum nome, CNPJ, código de produto ou placa."""
from __future__ import annotations

import pytest

from api import copiloto, servidor
from api.wms import painel, recebimento
from tests.wms.conftest import CNPJ_DEP, USUARIO


def _d(**k):
    base = {"ok": True, "armazens": 1, "ocupacao_pct": 40.0, "posicoes": 12,
            "tarefas_pendentes": 3, "ped_atrasados": 0, "vencidos": 0, "doca_24h": 0,
            "ultimo_movimento": "2026-09-12T10:00:00-03:00"}
    base.update(k)
    return base


def test_sem_tabela_e_erro_com_a_migration_no_texto():
    r = servidor._servico_wms_de({"ok": False, "sem_tabela": True})
    assert r["status"] == "erro" and "0090" in r["detalhe"]


def test_sem_armazem_e_info_e_nao_alarme():
    r = servidor._servico_wms_de(_d(armazens=0))
    assert r["status"] == "info" and "pronto" in r["detalhe"]


def test_normal_e_ok_com_os_numeros():
    r = servidor._servico_wms_de(_d())
    assert r["status"] == "ok"
    assert "ocupação 40%" in r["detalhe"] and "12 posição" in r["detalhe"]
    assert "último movimento 2026-09-12 10:00" in r["detalhe"]


@pytest.mark.parametrize("campo,texto", [
    ("ped_atrasados", "pedido(s) atrasado"),
    ("vencidos", "lote vencido"),
    ("doca_24h", "na doca há mais de 24 h"),
])
def test_cada_limiar_acende_sozinho(campo, texto):
    r = servidor._servico_wms_de(_d(**{campo: 2}))
    assert r["status"] == "alerta" and texto in r["detalhe"], r


def test_o_diagnostico_real_tem_as_chaves_que_o_cartao_le(armazem):
    d = painel.diagnostico()
    for c in ("armazens", "ocupacao_pct", "posicoes", "tarefas_pendentes",
              "ped_atrasados", "vencidos", "doca_24h", "ultimo_movimento"):
        assert c in d, c
    assert servidor._servico_wms_de(d)["status"] == "ok"


def test_o_copiloto_declara_a_fonte_e_ela_so_leva_escalar(armazem):
    r0 = recebimento.abrir({"armazem_id": armazem["id"], "doca_id": armazem["doca"],
                            "depositante_cnpj": CNPJ_DEP,
                            "itens": [{"produto_id": armazem["p1"], "qtd_nf": 2}]}, USUARIO)
    assert r0["status"] == "aberto"
    assert "wms_armazem" in copiloto._FONTES_ROTULO
    r = copiloto._fontes_do_snapshot()["wms_armazem"]()
    assert r["armazens"] == 1 and r["rec_abertos"] == 1
    for k, v in r.items():
        assert v is None or isinstance(v, (int, float)), (k, v)
    texto = str(r)
    assert CNPJ_DEP not in texto and "SCHULZ" not in texto and "961.0301" not in texto
