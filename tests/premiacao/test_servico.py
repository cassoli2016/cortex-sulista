"""Serviço de premiação (Task 5): orquestra params + gobrax/coleta + cálculo
com TTL/lock/fallback. Sem rede real — `_novo_cliente` é sempre monkeypatchado
para um FakeCliente (Task 4) ou uma função que quebra se for chamada.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from api.premiacao import coleta, gobrax, params, servico
from tests.premiacao.test_coleta import FakeCliente


def _snapshot(mes: str, coletado_em: str, media=2.0, km=4000.0, parcial=False) -> dict:
    return {
        "source": "gobrax-v3",
        "customerId": 1,
        "month": mes,
        "periodStart": f"{mes}-01T00:00:00Z",
        "periodEnd": f"{mes}-28T23:59:59Z",
        "coletado_em": coletado_em,
        "parcial": parcial,
        "frota_telemetria": {"veiculos": 1, "com_motorista": 1},
        "drivers": [{
            "driverId": 1, "driverName": "3797 - GABRIEL",
            "documento": "18••••••805", "vehicles": [{"plate": "AAA1A11", "model": "DAF XF"}],
            "nota": 80, "media": media, "km": km,
            "indicators": {"scores": {}, "percentages": {}, "extra": {}},
        }],
    }


def _cliente_quebra():
    raise AssertionError("não deveria coletar — snapshot já é válido")


def test_sem_credenciais_devolve_configurado_false(monkeypatch, tmp_path):
    monkeypatch.delenv("GOBRAX_EMAIL", raising=False)
    monkeypatch.delenv("GOBRAX_SENHA", raising=False)
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)

    resultado = servico.obter()

    assert resultado == {
        "configurado": False,
        "variaveis": ["GOBRAX_EMAIL", "GOBRAX_SENHA"],
        "index": [],
    }
    # nenhum valor de ambiente vaza na resposta
    assert "GOBRAX_EMAIL=" not in str(resultado) and "@" not in str(resultado)


def test_mes_fechado_com_snapshot_nao_recoleta(monkeypatch, tmp_path):
    monkeypatch.setenv("GOBRAX_EMAIL", "e@x.com")
    monkeypatch.setenv("GOBRAX_SENHA", "s3nh4")
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_preco_diesel", lambda mes: 4.91)
    monkeypatch.setattr(servico, "_novo_cliente", _cliente_quebra)

    coleta.gravar_snapshot(_snapshot("2026-06", "2026-07-01 08:00"), tmp_path)

    resultado = servico.obter("2026-06", agora=datetime(2026, 7, 27, 9, 0))

    assert resultado["configurado"] is True
    assert resultado["month"] == "2026-06"
    assert resultado["coletado_em"] == "2026-07-01 08:00"
    assert resultado["aviso"] is None
    assert resultado["referencias"]["preco_diesel_interno"] == 4.91


def test_mes_corrente_com_snapshot_velho_recoleta(monkeypatch, tmp_path):
    monkeypatch.setenv("GOBRAX_EMAIL", "e@x.com")
    monkeypatch.setenv("GOBRAX_SENHA", "s3nh4")
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_preco_diesel", lambda mes: 4.91)

    agora = datetime(2026, 7, 27, 10, 0)
    coleta.gravar_snapshot(_snapshot("2026-07", "2026-07-27 08:00", parcial=True), tmp_path)

    cliente = FakeCliente()
    monkeypatch.setattr(servico, "_novo_cliente", lambda: cliente)
    resultado = servico.obter(agora=agora)  # snapshot com 2h -> recoleta

    assert cliente.chamadas, "snapshot com mais de 1h deveria disparar recoleta"
    assert resultado["coletado_em"] == agora.strftime("%Y-%m-%d %H:%M")
    assert resultado["aviso"] is None

    # snapshot fresco (<1h): uma nova chamada NÃO pode recoletar de novo
    monkeypatch.setattr(servico, "_novo_cliente", _cliente_quebra)
    resultado2 = servico.obter(agora=agora + timedelta(minutes=5))
    assert resultado2["coletado_em"] == resultado["coletado_em"]


def test_gobrax_fora_serve_snapshot_antigo_com_aviso(monkeypatch, tmp_path):
    monkeypatch.setenv("GOBRAX_EMAIL", "e@x.com")
    monkeypatch.setenv("GOBRAX_SENHA", "s3nh4")
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_preco_diesel", lambda mes: 4.91)

    agora = datetime(2026, 7, 27, 10, 0)
    coleta.gravar_snapshot(_snapshot("2026-07", "2026-07-27 08:00", parcial=True), tmp_path)

    def _quebra():
        raise gobrax.GobraxIndisponivel("API Gobrax fora do ar.")
    monkeypatch.setattr(servico, "_novo_cliente", _quebra)

    resultado = servico.obter(agora=agora)  # snapshot velho + Gobrax fora -> fallback

    assert resultado["configurado"] is True
    assert resultado["aviso"] == "coletado em 2026-07-27 08:00 — não foi possível atualizar"
    assert resultado["coletado_em"] == "2026-07-27 08:00"
    assert resultado["linhas"], "linhas devem vir do snapshot antigo"


def test_calculo_aplicado_com_params_atuais(monkeypatch, tmp_path):
    monkeypatch.setenv("GOBRAX_EMAIL", "e@x.com")
    monkeypatch.setenv("GOBRAX_SENHA", "s3nh4")
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_preco_diesel", lambda mes: 4.91)
    monkeypatch.setattr(servico, "_novo_cliente", _cliente_quebra)
    monkeypatch.setattr(params, "PARAMS_PATH", tmp_path / "premiacao_params.json")
    params.salvar_params({"meta": 1.9, "preco_litro": 6.0, "pct_premiacao": 0.2, "km_minimo": 0})

    coleta.gravar_snapshot(
        _snapshot("2026-06", "2026-07-01 08:00", media=2.10, km=5000.0), tmp_path)

    resultado = servico.obter("2026-06", agora=datetime(2026, 7, 27, 9, 0))

    assert resultado["linhas"][0]["premio"] == 300.75
    assert resultado["kpis"]["premio_total"] == 300.75
    assert resultado["sem_media"] == 0
    assert resultado["referencias"]["media_frota"] == resultado["kpis"]["media_frota"]
