"""Serviço de premiação (Task 5): orquestra params + gobrax/coleta + cálculo
com TTL/lock/fallback. Sem rede real — `_novo_cliente` é sempre monkeypatchado
para um FakeCliente (Task 4) ou uma função que quebra se for chamada.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from api import db as api_db
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


def test_serie_le_so_snapshots_gravados_sem_recoletar(monkeypatch, tmp_path):
    # nem credenciais são setadas: serie() não olha gobrax.configurado() —
    # snapshots antigos servem igual, e _novo_cliente nunca pode ser chamado.
    monkeypatch.delenv("GOBRAX_EMAIL", raising=False)
    monkeypatch.delenv("GOBRAX_SENHA", raising=False)
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_novo_cliente", _cliente_quebra)
    monkeypatch.setattr(params, "PARAMS_PATH", tmp_path / "premiacao_params.json")

    coleta.gravar_snapshot(_snapshot("2026-06", "2026-06-30 08:00", media=2.0, km=4000.0), tmp_path)
    coleta.gravar_snapshot(
        _snapshot("2026-07", "2026-07-27 08:00", media=2.4, km=6000.0, parcial=True), tmp_path)

    resultado = servico.serie()

    assert resultado["meses"][0]["month"] == "2026-07"   # ordem decrescente (index)
    assert resultado["meses"][1]["month"] == "2026-06"
    assert len(resultado["meses"]) == 2
    jul = resultado["meses"][0]
    assert jul["parcial"] is True
    assert jul["media_frota"] == 2.4
    assert jul["meta"] == params.DEFAULTS["meta"]
    assert jul["premio_total"] is not None


def test_serie_ignora_mes_do_index_sem_snapshot_em_disco(monkeypatch, tmp_path):
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_novo_cliente", _cliente_quebra)

    coleta.gravar_snapshot(_snapshot("2026-06", "2026-06-30 08:00"), tmp_path)
    # index.json passa a citar um mês cujo arquivo de snapshot foi apagado —
    # serie() não pode quebrar nem inventar dado para ele.
    (tmp_path / "index.json").write_text(
        '[{"month":"2026-07","label":"Julho / 2026","drivers":1,"parcial":true},'
        '{"month":"2026-06","label":"Junho / 2026","drivers":1,"parcial":false}]',
        encoding="utf-8")

    resultado = servico.serie()

    assert [m["month"] for m in resultado["meses"]] == ["2026-06"]


def test_mes_fechado_com_snapshot_parcial_recoleta_uma_vez_e_fecha(monkeypatch, tmp_path):
    """I1: o snapshot de julho coletado em 27/07 com `parcial: true` nunca era
    recoletado depois que o mês fechou (01/08) — o prêmio ficava congelado 4
    dias mais cedo. Um snapshot `parcial` de um mês que já não é mais o
    corrente agora dispara UMA recoleta, que fecha o mês de verdade
    (`_period` devolve `parcial: false` para mês != mês corrente)."""
    monkeypatch.setenv("GOBRAX_EMAIL", "e@x.com")
    monkeypatch.setenv("GOBRAX_SENHA", "s3nh4")
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_preco_diesel", lambda mes: 4.91)

    coleta.gravar_snapshot(_snapshot("2026-07", "2026-07-27 12:40", parcial=True), tmp_path)

    cliente = FakeCliente()
    monkeypatch.setattr(servico, "_novo_cliente", lambda: cliente)

    resultado = servico.obter("2026-07", agora=datetime(2026, 8, 1, 9, 0))

    assert cliente.chamadas, "mês fechado com snapshot parcial deveria recoletar uma vez"
    assert resultado["parcial"] is False

    # depois de fechado, uma nova chamada não recoleta de novo
    monkeypatch.setattr(servico, "_novo_cliente", _cliente_quebra)
    resultado2 = servico.obter("2026-07", agora=datetime(2026, 8, 1, 9, 5))
    assert resultado2["parcial"] is False


def test_dois_atualizar_forcados_concorrentes_coletam_uma_vez(monkeypatch, tmp_path):
    """M2: dois POST /atualizar (force=True) simultâneos coletavam a Gobrax
    2x — o double-check dentro do lock é sempre verdadeiro com force=True e
    não filtrava nada. Fix: se o snapshot relido dentro do lock já mudou
    (outra chamada concorrente já coletou/gravou), usa o relido e NÃO
    recoleta de novo — mesmo com force."""
    monkeypatch.setenv("GOBRAX_EMAIL", "e@x.com")
    monkeypatch.setenv("GOBRAX_SENHA", "s3nh4")
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_preco_diesel", lambda mes: 4.91)
    monkeypatch.setattr(params, "PARAMS_PATH", tmp_path / "premiacao_params.json")

    contador = {"n": 0}
    trava = threading.Lock()

    class ClienteLento(FakeCliente):
        def get(self, path, req_params=None):
            if path == "/vehicles":
                with trava:
                    contador["n"] += 1
                time.sleep(0.2)  # simula rede lenta -> t2 chega enquanto t1 coleta
            return super().get(path, req_params)

    monkeypatch.setattr(servico, "_novo_cliente", lambda: ClienteLento())

    agora = datetime(2026, 7, 27, 10, 0)
    erros = []

    def chamar():
        try:
            servico.obter("2026-06", force=True, agora=agora)
        except Exception as exc:  # noqa: BLE001
            erros.append(exc)

    t1 = threading.Thread(target=chamar)
    t2 = threading.Thread(target=chamar)
    t1.start()
    time.sleep(0.05)
    t2.start()
    t1.join()
    t2.join()

    assert not erros
    assert contador["n"] == 1, "duas chamadas force concorrentes coletaram mais de uma vez"


def test_preco_diesel_cache_evita_segunda_consulta_no_ttl(monkeypatch):
    """M5: sem cache, todo GET pagava o custo cheio de bater no AVA — com o
    túnel fora isso é ~8-15s por chamada só para um número informativo."""
    servico._PRECO_CACHE.clear()
    contador = {"n": 0}

    def fake_query(sql, sql_params):
        contador["n"] += 1
        return [{"preco": 4.93}]
    monkeypatch.setattr(api_db, "query", fake_query)

    v1 = servico._preco_diesel("2026-06")
    v2 = servico._preco_diesel("2026-06")

    assert v1 == v2 == 4.93
    assert contador["n"] == 1, "segunda chamada dentro do TTL não deveria ir ao banco"


def test_preco_diesel_falha_loga_um_aviso_e_nao_propaga(monkeypatch, caplog):
    """M5: o `except Exception` engolia até erro de programação sem log —
    agora loga um aviso (rastreável) e continua devolvendo None (a tela não
    pode cair por causa de um número informativo)."""
    servico._PRECO_CACHE.clear()

    def fake_query(sql, sql_params):
        raise RuntimeError("tunel fora")
    monkeypatch.setattr(api_db, "query", fake_query)

    with caplog.at_level("WARNING", logger=servico.log.name):
        valor = servico._preco_diesel("2026-07")

    assert valor is None
    assert any("preco diesel indisponivel" in r.message for r in caplog.records)


def test_snapshot_sem_coletado_em_no_mes_fechado_nao_estoura(monkeypatch, tmp_path):
    """M10: snapshot sem `coletado_em` (dado externo corrompido/incompleto)
    não pode virar 500 — mês fechado sem `parcial` só serve como está."""
    monkeypatch.setenv("GOBRAX_EMAIL", "e@x.com")
    monkeypatch.setenv("GOBRAX_SENHA", "s3nh4")
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_preco_diesel", lambda mes: 4.91)
    monkeypatch.setattr(servico, "_novo_cliente", _cliente_quebra)

    snap = _snapshot("2026-06", "2026-07-01 08:00")
    del snap["coletado_em"]
    coleta.gravar_snapshot(snap, tmp_path)

    resultado = servico.obter("2026-06", agora=datetime(2026, 7, 27, 9, 0))

    assert resultado["configurado"] is True
    assert resultado["coletado_em"] is None


def test_snapshot_sem_coletado_em_no_mes_corrente_recoleta_sem_estourar(monkeypatch, tmp_path):
    """M10 no outro ramo: sem `coletado_em`, o mês CORRENTE é tratado como
    'muito velho' -> recoleta (não KeyError em `_coletado_ha_mais_de_1h`)."""
    monkeypatch.setenv("GOBRAX_EMAIL", "e@x.com")
    monkeypatch.setenv("GOBRAX_SENHA", "s3nh4")
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_preco_diesel", lambda mes: 4.91)

    snap = _snapshot("2026-07", "2026-07-27 08:00", parcial=True)
    del snap["coletado_em"]
    coleta.gravar_snapshot(snap, tmp_path)

    cliente = FakeCliente()
    monkeypatch.setattr(servico, "_novo_cliente", lambda: cliente)

    resultado = servico.obter(agora=datetime(2026, 7, 27, 10, 0))

    assert cliente.chamadas, "sem coletado_em no mês corrente deveria recoletar"
    assert resultado["configurado"] is True
