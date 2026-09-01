# -*- coding: utf-8 -*-
"""O compositor dos ciclos da programação (v0.200.0).

Dublê na ORDEM DE GRANDEZA real: descarga ~3,6h, deslocamento ~15h — dublê
de brinquedo (0,1h) esconderia erro de unidade (minuto × hora).
"""
from __future__ import annotations

from api.programacao_ciclos import (CAP_DESCARGA_H, N_MIN, montar_ciclos)


def _viagens(n, ori="JOINVILLE/SC", dst="SAO BERNARDO DO CAMPO/SP",
             desloc_h=12.0, com_eventos=True):
    """n viagens da mesma rota, com eventos SAC quando pedido."""
    vs, evs, dests = [], {}, {}
    for i in range(n):
        k = f"1|1|1|1|0|{i}"
        vs.append({"k": k, "ori": ori, "dst": dst,
                   "dtsaida": "2026-08-10 06:00:00",
                   "dtchegada": f"2026-08-10 {int(6+desloc_h):02d}:00:00",
                   "km": 548.0})
        if com_eventos:
            evs[k] = {"cc": "2026-08-10 03:00:00", "sc": "2026-08-10 06:00:00",
                      "cd": f"2026-08-10 {int(6+desloc_h):02d}:00:00",
                      "fd": f"2026-08-10 {int(6+desloc_h)+3:02d}:30:00"}
            dests[k] = "LEAR - SBC"
    return vs, evs, dests


def test_mediana_e_p90_por_rota_com_ciclo_composto():
    vs, evs, dests = _viagens(20)
    d = montar_ciclos(vs, evs, dests)
    r = d["rotas"][0]
    assert r["n"] == 20
    assert r["desloc_med_h"] == 12.0
    assert r["carreg_med_h"] == 3.0                    # 394→395
    assert r["descarga_med_h"] == 3.5                  # 396→397
    assert r["ciclo_med_h"] == 12.0 + 3.0 + 3.5        # só MEDIANAS compõem
    assert r["descarga_fonte"] == "cidade"   # rota agrega vários destinatários
    assert d["kpis"]["descarga_mediana_h"] == 3.5


def test_rota_com_menos_de_10_amostras_nao_vira_numero():
    vs, evs, dests = _viagens(N_MIN - 1)
    d = montar_ciclos(vs, evs, dests)
    assert d["rotas"] == []                            # n/d, nunca inventado
    assert d["kpis"]["rotas_com_historico"] == 0


def test_descarga_acima_do_cap_fisico_sai_da_amostra():
    """min(396)→max(397) atravessando dias é artefato de pareamento (2,3%
    medidos) — 30h de 'descarga' não entra na mediana."""
    vs, evs, dests = _viagens(20)
    for k in list(evs)[:10]:
        evs[k]["fd"] = "2026-08-12 10:00:00"           # ~37h depois do cd
    d = montar_ciclos(vs, evs, dests)
    assert d["rotas"][0]["descarga_med_h"] == 3.5      # só as 10 sadias
    assert d["rotas"][0]["descarga_n"] == 10


def test_fallback_de_descarga_diz_a_fonte():
    """Sem destinatário com amostra, cai para cidade; sem cidade, global —
    e a FONTE vai no payload (número que muda de fonte sem avisar é número
    em que ninguém confia)."""
    vs, evs, dests = _viagens(20)
    vs_poucos, evs_p, dests_p = _viagens(N_MIN - 1, ori="OUTRA/SP", dst="RARA/RJ")
    d = montar_ciclos(vs + vs_poucos, {**evs, **evs_p}, {})
    assert d["rotas"][0]["descarga_fonte"] == "cidade"
    # destino sem amostra local (n<10) cai para a mediana GLOBAL, dito
    vs2, evs2, _ = _viagens(N_MIN, ori="JOINVILLE/SC", dst="SEM-SAC/MG",
                            com_eventos=False)
    for i, v in enumerate(vs2):
        v["k"] = f"g{i}"
    d2 = montar_ciclos(vs + vs2, evs, {})
    rota2 = next(r for r in d2["rotas"] if r["dst"] == "SEM-SAC/MG")
    assert rota2["descarga_fonte"] == "global"


def test_destino_lento_exige_o_dobro_da_mediana_global():
    vs, evs, dests = _viagens(20)
    vs2, evs2, dests2 = _viagens(15, ori="CURITIBA/PR", dst="CONTAGEM/MG")
    for k in list(evs2):
        k2 = "L" + k
        vs2[[v["k"] for v in vs2].index(k)]["k"] = k2
        evs2[k2] = {**evs2.pop(k),
                    "cd": "2026-08-10 21:00:00", "fd": "2026-08-11 13:30:00"}
        dests2[k2] = dests2.pop(k).replace("LEAR - SBC", "SUPERMERCADOS BH")
    d = montar_ciclos(vs + vs2, {**evs, **evs2}, {**dests, **dests2},
                      freetimes={"SUPERMERCADOS BH": 4.0})
    lentos = d["destinos_lentos"]
    assert len(lentos) == 1
    assert "SUPERMERCADOS BH" in lentos[0]["destinatario"]
    assert lentos[0]["descarga_med_h"] == 16.5
    assert lentos[0]["freetime_h"] == 4.0              # estadia sistemática à mostra


def test_sabotagem_deslocamento_negativo_nao_conta():
    """Chegada antes da saída é dado furado — sai da régua e é CONTADO."""
    vs, evs, dests = _viagens(20)
    vs[0]["dtchegada"] = "2026-08-10 04:00:00"         # antes da saída
    d = montar_ciclos(vs, evs, dests)
    assert d["kpis"]["fora_da_regua"] == 1
    assert d["rotas"][0]["n"] == 20                    # a viagem conta no volume
    assert d["rotas"][0]["desloc_med_h"] == 12.0       # mas não na mediana
