"""Serviço da premiação: TTL, lock, fallback e a guarda da coleta vazia.

Reescrito em 19/08/2026, quando a fonte passou a ser a API pública com token e a
regra passou a ser nota × km. O que se preserva aqui é a RESILIÊNCIA — a parte
que já custou um mês de dados de pagamento quando falhou.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

import pytest

from api import credenciais
from api.gobrax import cliente as gbx
from api.premiacao import coleta, params, servico


@pytest.fixture(autouse=True)
def _com_token(monkeypatch, tmp_path):
    # O COFRE VENCE A VARIÁVEL DE AMBIENTE (api/credenciais.py). Sem apontar o
    # cofre para o tmp_path, "sem token" só limpava METADE das fontes: na
    # máquina que tem `data/credenciais.json` de verdade — o servidor — o
    # token continuava valendo e o teste do modo não-configurado falhava.
    monkeypatch.setattr(credenciais, "CAMINHO", tmp_path / "credenciais.json")
    monkeypatch.setenv("GOBRAX_TOKEN", "token-de-teste")
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(coleta, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_novo_cliente", lambda: object())
    params.salvar_params({"valor_por_km": 0.10, "nota_minima": 70.0,
                          "km_minimo": 1500.0}, tmp_path / "params.json")
    monkeypatch.setattr(params, "PARAMS_PATH", tmp_path / "params.json")
    # ESTE ARQUIVO TESTA O SERVIÇO, NÃO A CONFIGURAÇÃO. `params_da_competencia`
    # consulta `prem_versoes` no banco local, e sem este monkeypatch o teste
    # leria a configuração DE PRODUÇÃO — passaria por coincidência (os padrões
    # dos dois armazéns são iguais) e quebraria no dia em que alguém mudasse o
    # valor por km na tela. A leitura por competência tem teste próprio, com
    # esquema de verdade, em `test_params_competencia.py`.
    monkeypatch.setattr(servico, "params_da_competencia",
                        lambda mes: params.ler_params())
    return tmp_path


def _snapshot(mes, coletado_em, km=5000.0, nota=90.0, parcial=False):
    return {"month": mes, "source": "gobrax-api-overview", "regra_fonte": "nota_km",
            "coletado_em": coletado_em, "parcial": parcial,
            "drivers": [{"driverId": 1, "driverName": "GABRIEL", "km": km,
                         "nota": nota}]}


def test_snapshot_do_mes_fechado_e_servido_sem_recoletar(monkeypatch, _com_token):
    coleta.gravar_snapshot(_snapshot("2026-06", "2026-07-01 08:00"), _com_token)

    def nao_pode(*a, **kw):
        raise AssertionError("mês fechado com snapshot não deve recoletar")

    monkeypatch.setattr(coleta, "coletar_mes", nao_pode)
    r = servico.obter("2026-06", agora=datetime(2026, 8, 1, 9, 0))
    assert r["kpis"]["premiados"] == 1
    assert r["kpis"]["premio_total"] == 450.0     # 5000 × 0,10 × 0,90


def test_mes_corrente_com_snapshot_velho_recoleta(monkeypatch, _com_token):
    coleta.gravar_snapshot(_snapshot("2026-08", "2026-08-19 08:00", parcial=True),
                           _com_token)
    chamou = []

    def coletar(mes, cliente=None, agora=None):
        chamou.append(mes)
        return _snapshot(mes, "2026-08-19 14:00", km=6000.0, parcial=True)

    monkeypatch.setattr(coleta, "coletar_mes", coletar)
    servico.obter("2026-08", agora=datetime(2026, 8, 19, 14, 0))
    assert chamou == ["2026-08"]


def test_coleta_vazia_nao_sobrescreve_snapshot_com_dados(monkeypatch, _com_token):
    """A frota oscila na plataforma durante remanejo e a coleta pode voltar
    vazia. Snapshot é dado de pagamento: mantém o anterior e avisa."""
    coleta.gravar_snapshot(_snapshot("2026-08", "2026-08-19 08:00", parcial=True),
                           _com_token)

    def vazia(mes, cliente=None, agora=None):
        raise coleta.ColetaVazia("sem motoristas")

    monkeypatch.setattr(coleta, "coletar_mes", vazia)
    r = servico.obter("2026-08", force=True, agora=datetime(2026, 8, 19, 14, 0))
    assert r["kpis"]["premiados"] == 1          # o snapshot bom sobreviveu
    assert r["aviso"] and "vazia" in r["aviso"]


def test_api_fora_do_ar_serve_snapshot_antigo_com_aviso(monkeypatch, _com_token):
    coleta.gravar_snapshot(_snapshot("2026-08", "2026-08-19 08:00", parcial=True),
                           _com_token)

    def caiu(mes, cliente=None, agora=None):
        raise gbx.GobraxIndisponivel("timeout")

    monkeypatch.setattr(coleta, "coletar_mes", caiu)
    r = servico.obter("2026-08", force=True, agora=datetime(2026, 8, 19, 14, 0))
    assert r["kpis"]["premiados"] == 1
    assert r["aviso"]


def test_api_fora_do_ar_sem_snapshot_anterior_propaga(monkeypatch, _com_token):
    def caiu(mes, cliente=None, agora=None):
        raise gbx.GobraxIndisponivel("timeout")

    monkeypatch.setattr(coleta, "coletar_mes", caiu)
    with pytest.raises(gbx.GobraxIndisponivel):
        servico.obter("2026-08", agora=datetime(2026, 8, 19, 14, 0))


def test_duas_chamadas_concorrentes_coletam_uma_vez_so(monkeypatch, _com_token):
    """O lock existe para não disparar duas coletas simultâneas da mesma API."""
    contador = []

    def lenta(mes, cliente=None, agora=None):
        contador.append(mes)
        time.sleep(0.2)
        return _snapshot(mes, "2026-08-19 14:00", parcial=True)

    monkeypatch.setattr(coleta, "coletar_mes", lenta)
    erros = []

    def roda():
        try:
            servico.obter("2026-08", force=True, agora=datetime(2026, 8, 19, 14, 0))
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    t1, t2 = threading.Thread(target=roda), threading.Thread(target=roda)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert not erros
    assert len(contador) == 1


def test_sem_token_a_tela_recebe_modo_nao_configurado(monkeypatch, _com_token):
    """E a resposta diz o NOME da variável que falta, nunca o valor."""
    monkeypatch.delenv("GOBRAX_TOKEN", raising=False)
    r = servico.obter("2026-08", agora=datetime(2026, 8, 19, 14, 0))
    assert r["configurado"] is False
    assert r["variaveis"] == ["GOBRAX_TOKEN"]


def test_a_regra_do_mes_viaja_no_payload(monkeypatch, _com_token):
    """A tela precisa dizer qual critério está exibindo: mês antigo continua
    mostrando o valor com que foi pago."""
    snap = _snapshot("2026-06", "2026-07-01 08:00")
    snap["regra_fonte"] = "litros_economizados"
    coleta.gravar_snapshot(snap, _com_token)
    monkeypatch.setattr(coleta, "coletar_mes",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError()))
    r = servico.obter("2026-06", agora=datetime(2026, 8, 1, 9, 0))
    assert r["regra"] == "litros_economizados"
