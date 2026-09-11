# -*- coding: utf-8 -*-
"""A lentidão nos corredores pela velocidade da NOSSA frota (`api/radar/frota.py`).

11/09/2026: a franquia grátis de trânsito da TomTom é mensal e acabou na
primeira semana; quem opera pediu que o cartão "Rodovias agora" aparecesse e
estivesse certo, e escolheu a velocidade dos próprios caminhões como fonte.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from api import pglocal
from api.radar import coleta, frota, painel, rodovias

AGORA = datetime(2026, 9, 11, 15, 0)


def _serie(vel: dict):
    def ler(placas, agora):
        return {pl: [(agora - timedelta(minutes=m), float(v))
                     for m, v in zip((12, 6, 1), vel[pl])] for pl in placas if pl in vel}
    return ler


POS = {"posicoes": {
    "CTB0A01": {"lat": -25.43, "lon": -49.27, "fonte": "erp", "idade_min": 2.0},    # Curitiba
    "CTB0A02": {"lat": -25.50, "lon": -49.20, "fonte": "erp", "idade_min": 2.0},    # Curitiba
    "CTB0A03": {"lat": -25.40, "lon": -49.30, "fonte": "erp", "idade_min": 1.0},    # Curitiba
    "JOI0A01": {"lat": -26.30, "lon": -48.85, "fonte": "erp", "idade_min": 3.0},    # Joinville
    "FORA0A1": {"lat": -30.03, "lon": -51.23, "fonte": "erp", "idade_min": 2.0},    # Porto Alegre
    "VELHA0A": {"lat": -23.00, "lon": -45.50, "fonte": "erp", "idade_min": 180.0},  # Dutra, velha
}}
VEL = {"CTB0A01": (70, 72, 75), "CTB0A02": (30, 22, 18), "CTB0A03": (35, 30, 26),
       "JOI0A01": (0, 0, 0), "FORA0A1": (20, 20, 20), "VELHA0A": (25, 25, 25)}
VIAGENS = [{"placa": p} for p in POS["posicoes"]] + [{"placa": "SEMPOS01"}]


def _ler() -> dict:
    return {l["regiao"]: l for l in frota.ler(VIAGENS, POS, _serie(VEL), agora=AGORA)}


# ------------------------------------------------------------- a leitura

def test_conta_por_corredor_e_destaca_o_LENTO():
    r = _ler()
    ctb = r["curitiba"]
    assert (ctb["caminhoes"], ctb["andando"], ctb["lentos"], ctb["parados"]) == (3, 1, 2, 0)
    assert ctb["lento_max_min"] == 11, "o lento mais antigo: 12 min atrás até 1 min atrás"
    assert ctb["vel_lentos"] == 22, "mediana de 18 e 26 km/h"
    assert (r["joinville"]["parados"], r["joinville"]["lentos"]) == (1, 0)


def test_so_conta_quem_esta_NO_corredor_e_com_posicao_de_AGORA():
    r = _ler()
    assert r["dutra"]["caminhoes"] == 0, "posição de 3 h atrás não diz onde o caminhão está"
    assert sum(l["caminhoes"] for l in r.values()) == 4, "Porto Alegre e sem posição ficam fora"
    assert set(r) == {c[0] for c in rodovias.CORREDORES}, "os quatro, sempre — zero é resposta"


def test_sem_caminhao_nenhum_os_quatro_corredores_vem_ZERADOS():
    linhas = frota.ler([], {"posicoes": {}}, _serie({}), agora=AGORA)
    assert len(linhas) == 4
    assert all(l["caminhoes"] == 0 and l["lento_max_min"] is None for l in linhas)


# ------------------------------------------------------------- a coleta e a tela

def test_a_coleta_grava_o_RETRATO_e_a_tela_le(esquema_pg, rede, tomtom, relogio):
    r = coleta.coletar(esquema=esquema_pg, baixar=rede, consultar_tomtom=tomtom, so={"frota"})
    assert r == {"frota": "ok"}
    f = painel.painel(esquema_pg)["frota"]
    por = {c["regiao"]: c for c in f["corredores"]}
    assert (por["curitiba"]["andando"], por["curitiba"]["lentos"]) == (1, 1)
    assert por["joinville"]["parados"] == 1 and por["dutra"]["caminhoes"] == 0
    assert (f["caminhoes"], f["lentos"]) == (3, 1) and f["coletado_em"]


def test_falha_da_frota_NAO_apaga_o_retrato(esquema_pg, rede, tomtom, relogio, monkeypatch):
    coleta.coletar(esquema=esquema_pg, baixar=rede, consultar_tomtom=tomtom, so={"frota"})

    def quebra():
        raise RuntimeError("ERP fora")
    monkeypatch.setattr(frota, "_entradas", quebra)
    r = coleta.coletar(esquema=esquema_pg, baixar=rede, consultar_tomtom=tomtom,
                       so={"frota"}, forcar=True)
    assert r == {"frota": "erro"}
    p = painel.painel(esquema_pg)
    assert p["frota"]["lentos"] == 1, "o retrato de antes continua"
    assert p["coleta"]["frota"]["erro"], "e a falha fica dita"


def test_a_tabela_NAO_TEM_placa_motorista_nem_coordenada(esquema_pg):
    """A página é de todo usuário logado: só contagem. O guard lê o banco, não
    o texto do SQL — texto-fonte protege contra apagar, não contra acrescentar."""
    cols = {r["column_name"] for r in pglocal.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = 'rad_frota'", (esquema_pg,),
        esquema=esquema_pg)}
    assert cols, "a tabela não existe no schema do teste — a varredura passaria por vacuidade"
    proibidas = {c for c in cols
                 if any(p in c for p in ("placa", "veiculo", "motorista", "cpf", "lat", "lon"))}
    assert not proibidas, proibidas


def test_a_saude_e_o_copiloto_dizem_a_frota_so_em_CONTAGEM(esquema_pg, rede, tomtom, relogio):
    coleta.coletar(esquema=esquema_pg, baixar=rede, consultar_tomtom=tomtom)
    c = painel.cartao_saude(esquema_pg)
    assert c["status"] == "ok" and "frota nos corredores" in c["detalhe"], c
    r = painel.resumo_copiloto(esquema_pg)
    assert (r["rodovias_frota_caminhoes_agora"], r["rodovias_frota_lentos_agora"]) == (3, 1)
    assert not any("RAD0A" in str(v) for v in r.values()), "placa no snapshot"


# ------------------------------------------------------------- o orçamento da TomTom

def test_o_radar_para_de_consultar_a_TomTom_no_TETO_do_mes(esquema_pg, rede, tomtom, relogio):
    pglocal.executar(
        "INSERT INTO tt_chamadas (dia, recurso, chamadas, erros, ultima_em) "
        "VALUES (%s, 'radar_incidentes', %s, 0, now())",
        (date.today(), rodovias.TETO_MES - 2), esquema=esquema_pg)
    r = coleta.coletar(esquema=esquema_pg, baixar=rede, consultar_tomtom=tomtom, so={"rodovias"})
    assert r == {"rodovias": "erro"} and tomtom.chamadas == 0, "consultou além do teto"
    erro = painel.painel(esquema_pg)["coleta"]["rodovias"]["erro"]
    assert "franquia do mês da TomTom atingida" in erro, erro


def test_abaixo_do_teto_o_radar_consulta(esquema_pg, rede, tomtom, relogio):
    """O contrapeso: sem isto o teto poderia estar barrando sempre."""
    r = coleta.coletar(esquema=esquema_pg, baixar=rede, consultar_tomtom=tomtom, so={"rodovias"})
    assert r == {"rodovias": "ok"} and tomtom.chamadas == 4
