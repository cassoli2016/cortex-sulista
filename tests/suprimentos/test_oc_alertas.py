"""O alerta de OC na Visão Geral: com a previsão igual à emissão em 80% das
OCs, 'atrasada' crua ficava permanentemente acesa — alarme que nunca apaga
ensina a ignorar o alarme. Agora o número vem da regra única (sem nota há
mais de 30 dias ou prazo informado vencido) e a fila ganha aviso próprio."""
from __future__ import annotations

from api import alertas, queries


def _silenciar_o_resto(monkeypatch):
    def fora(*a, **k):
        raise RuntimeError("fonte fora")
    for nome in ("get_programacao", "get_seguranca"):
        monkeypatch.setattr(queries, nome, fora)
    monkeypatch.setattr(alertas, "fontes_fora", lambda *a, **k: [], raising=False)


def _alertas(monkeypatch, vg):
    _silenciar_o_resto(monkeypatch)
    monkeypatch.setattr(queries, "get_visao_geral", lambda: vg)
    return {a["titulo"]: a for a in alertas.build_alertas()}


def test_atrasadas_e_fila_viram_dois_avisos_distintos(monkeypatch):
    a = _alertas(monkeypatch, {"oc_atrasadas": 3, "oc_atraso_valor": 1234.5, "oc_aprovacao": 7})
    assert "Ordens de compra atrasadas" in a
    t = a["Ordens de compra atrasadas"]
    assert t["nivel"] == "atencao" and "3 OC" in t["texto"] and "30 dias" in t["texto"]
    assert "1.234" in t["texto"] and "Sem nota" in t["texto"]
    f = a["OCs na fila do aprovador"]
    assert f["nivel"] == "info" and "7 OC" in f["texto"] and "Aprovações" in f["texto"]


def test_sem_pendencia_nao_ha_aviso(monkeypatch):
    a = _alertas(monkeypatch, {"oc_atrasadas": 0, "oc_atraso_valor": 0.0, "oc_aprovacao": 0})
    assert "Ordens de compra atrasadas" not in a and "OCs na fila do aprovador" not in a
