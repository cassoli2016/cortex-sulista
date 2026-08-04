from __future__ import annotations

from api.alertas import _alertas_previsao


def _payload(prev, orc, avisos=()):
    return {"mes": "2026-08", "kpis": {"resultado_previsto": prev,
                                       "resultado_orcado": orc},
            "avisos": list(avisos)}


def test_previsto_negativo_e_critico():
    itens = _alertas_previsao(_payload(-50000.0, 100000.0))
    assert itens[0][0] == "critico" and "negativo" in itens[0][1].lower()


def test_abaixo_do_orcado_e_atencao():
    itens = _alertas_previsao(_payload(80000.0, 100000.0))
    assert itens[0][0] == "atencao" and "orçado" in itens[0][1].lower()


def test_acima_do_orcado_sem_alerta_de_resultado():
    assert _alertas_previsao(_payload(120000.0, 100000.0)) == []


def test_aviso_de_divergencia_vira_info():
    itens = _alertas_previsao(_payload(120000.0, 100000.0,
                                       ["Combustivel diverge: razao x abastecimentos"]))
    assert itens[0][0] == "info" and "combust" in itens[0][2].lower()
