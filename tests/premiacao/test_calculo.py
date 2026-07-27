"""Regra de premiação por litros economizados (spec §1). Módulo puro."""
from __future__ import annotations

from api.premiacao.calculo import calcular

PARAMS = {"meta": 1.90, "preco_litro": 6.0, "pct_premiacao": 0.20, "km_minimo": 500.0}


def _mot(**kw):
    base = {"driverId": 1, "driverName": "3797 - GABRIEL", "documento": "18•••••05",
            "vehicles": [{"plate": "FQJ8H55", "model": "DAF"}],
            "nota": 80, "media": 2.10, "km": 5000.0, "indicators": {}}
    base.update(kw)
    return base


def test_exemplo_canonico_da_spec_sem_arredondamento_intermediario():
    """km 5.000 · meta 1,90 · média 2,10 · R$6/l · 20% → R$ 300,75.

    O doc do MVP mostra 300,60 porque arredonda o valor economizado para 1.503
    ANTES do percentual — a spec manda NÃO reproduzir esse arredondamento."""
    r = calcular([_mot()], PARAMS)
    l = r["linhas"][0]
    assert l["premio"] == 300.75
    assert round(l["litros_economizados"], 2) == 250.63
    assert l["elegivel"] is True


def test_media_abaixo_da_meta_da_premio_zero_mas_linha_aparece():
    r = calcular([_mot(media=1.70)], PARAMS)
    l = r["linhas"][0]
    assert l["premio"] == 0.0
    assert l["litros_economizados"] == 0.0
    assert len(r["linhas"]) == 1          # desempenho abaixo da meta é informação


def test_km_abaixo_do_minimo_nao_e_elegivel_nem_soma_no_premio_total():
    r = calcular([_mot(km=300.0)], PARAMS)
    l = r["linhas"][0]
    assert l["elegivel"] is False
    assert r["kpis"]["premio_total"] == 0.0   # não elegível não entra no total
    assert l["premio"] > 0                    # mas a linha mostra quanto SERIA


def test_km_minimo_zero_desliga_o_corte():
    r = calcular([_mot(km=10.0)], {**PARAMS, "km_minimo": 0})
    assert r["linhas"][0]["elegivel"] is True


def test_sem_media_fica_fora_das_linhas_e_e_contado():
    r = calcular([_mot(), _mot(driverId=2, media=None), _mot(driverId=3, media=0)], PARAMS)
    assert len(r["linhas"]) == 1
    assert r["sem_media"] == 2
    assert r["kpis"]["total_motoristas"] == 3
    assert r["kpis"]["com_media"] == 1


def test_kpis_agregados_e_media_da_frota_ponderada():
    """media_frota = km total ÷ litros consumidos totais (ponderada por km)."""
    r = calcular([_mot(), _mot(driverId=2, media=1.90, km=1900.0)], PARAMS)
    k = r["kpis"]
    # litros: 5000/2.1=2380.95 + 1900/1.9=1000 → media_frota = 6900/3380.95 = 2.0409...
    assert round(k["media_frota"], 4) == round(6900.0 / (5000.0 / 2.1 + 1000.0), 4)
    assert k["premiados"] == 1                # o 2º tem prêmio 0
    assert k["elegiveis"] == 2
    assert k["premio_total"] == 300.75
    assert k["meta"] == 1.90


def test_ordena_por_premio_depois_km():
    r = calcular([_mot(driverId=1, media=1.95, km=8000.0),
                  _mot(driverId=2, media=2.30, km=3000.0),
                  _mot(driverId=3, media=1.70, km=9000.0)], PARAMS)
    assert [l["driverId"] for l in r["linhas"]] == [2, 1, 3]


def test_campos_originais_motorista_sobrevivem_intactos_na_linha():
    """Verifica que todo campo original do motorista permanece inalterado na saída.

    A implementação usa **m para expandir; refactoring que montasse a linha manualmente
    e esquecesse um campo passaria verde na suíte sem este teste."""
    original = {
        "driverId": 42,
        "driverName": "5821 - JOÃO DA SILVA",
        "documento": "12•••••98",
        "vehicles": [
            {"plate": "ABC1234", "model": "SCANIA"},
            {"plate": "XYZ5678", "model": "VOLVO"}
        ],
        "nota": 92,
        "media": 2.15,
        "km": 6200.0,
        "indicators": {
            "acidentes": 0,
            "multas": 2,
            "defeitos": 1
        }
    }
    r = calcular([original], PARAMS)
    assert len(r["linhas"]) == 1
    linha = r["linhas"][0]

    # Verifica que todos os campos originais estão presentes e iguais
    assert linha["driverId"] == 42
    assert linha["driverName"] == "5821 - JOÃO DA SILVA"
    assert linha["documento"] == "12•••••98"
    assert linha["vehicles"] == [
        {"plate": "ABC1234", "model": "SCANIA"},
        {"plate": "XYZ5678", "model": "VOLVO"}
    ]
    assert linha["nota"] == 92
    assert linha["media"] == 2.15
    assert linha["km"] == 6200.0
    assert linha["indicators"] == {"acidentes": 0, "multas": 2, "defeitos": 1}

    # Verifica que os 5 campos calculados existem
    assert "litros_meta" in linha
    assert "litros_consumidos" in linha
    assert "litros_economizados" in linha
    assert "premio" in linha
    assert "elegivel" in linha
