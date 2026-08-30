"""Coleta vazia NUNCA vira snapshot — nem por cima de um bom, nem no lugar do
que não existe.

O QUE ACONTECEU DE VERDADE (descoberto em 30/08/2026)
====================================================
O comparativo mensal mostrava ZERO em fevereiro, março, abril, maio e junho de
2026. A Gobrax tinha os cinco meses inteiros (37, 48, 66, 69 e 74 motoristas
com km). O que havia em disco eram snapshots gravados por um backfill de
27/07 16:48 com `drivers: []` e — o detalhe que fechava a armadilha —
`parcial: false`, isto é, marcados como COMPLETOS.

O estrago tem duas partes, e a segunda é a pior:
1. cinco meses apareciam vazios num card que decide premiação;
2. o snapshot vazio BLOQUEAVA a recoleta, porque `_precisa_recoletar` só olha
   se o arquivo existe. O mês estava "coletado". Só uma recoleta forçada à mão
   trouxe o dado de volta.

O guard existia pela metade: `if not novo.get("drivers") and snap_relido and
snap_relido.get("drivers")` só protegia quem JÁ TINHA snapshot bom. O ramo sem
snapshot anterior — que é exatamente o do backfill de mês nunca coletado —
caía no `else` e gravava. Pior: gravava `{"drivers": []}` sem a chave `month`,
o que hoje estouraria `KeyError` dentro do `gravar_snapshot`, ou seja 500 na
tela em vez de dado errado.

É a mesma família do "zero que é ausência de lançamento não é desempenho":
mês sem coleta não é mês sem prêmio, e a diferença entre os dois é a única
coisa que importa aqui.
"""
from __future__ import annotations

import pytest

from api import credenciais
from api.premiacao import coleta, params, servico


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch, tmp_path):
    monkeypatch.setattr(credenciais, "CAMINHO", tmp_path / "credenciais.json")
    monkeypatch.setenv("GOBRAX_TOKEN", "token-de-teste")
    monkeypatch.setattr(servico, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(coleta, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(servico, "_novo_cliente", lambda: object())
    monkeypatch.setattr(servico, "params_da_competencia",
                        lambda mes: params.ler_params())
    return tmp_path


def _vazia(monkeypatch):
    def coletar(mes, cliente=None, agora=None):
        raise coleta.ColetaVazia(f"nada para {mes}")
    monkeypatch.setattr(coleta, "coletar_mes", coletar)


def _snapshot(mes, coletado_em, n=3):
    return {"month": mes, "source": "gobrax-api-overview", "regra_fonte": "nota_km",
            "coletado_em": coletado_em, "parcial": False,
            "drivers": [{"driverId": i, "driverName": f"M{i}", "km": 5000.0,
                         "nota": 90.0} for i in range(n)]}


# ── o ramo que faltava: mês NUNCA coletado ──────────────────────────────────


def test_mes_novo_com_coleta_vazia_NAO_GRAVA_snapshot(monkeypatch, _ambiente):
    _vazia(monkeypatch)
    servico.obter("2026-04")
    assert coleta.ler_snapshot("2026-04", _ambiente) is None, (
        "gravou um snapshot vazio: o mês fica registrado como coletado e a "
        "recoleta nunca mais acontece — foi assim que fev a jun/26 sumiram")


def test_e_a_tela_ABRE_dizendo_por_que_esta_vazia(monkeypatch, _ambiente):
    """Não estourar é metade; a outra metade é a pessoa saber o que houve.
    Tela vazia sem aviso lê-se como "ninguém rodou"."""
    _vazia(monkeypatch)
    r = servico.obter("2026-04")
    assert r["configurado"] is True
    assert r["linhas"] == []
    assert "não trouxe motorista" in (r["aviso"] or "")


def test_o_mes_seguinte_ainda_pode_ser_coletado(monkeypatch, _ambiente):
    """Consequência direta de não ter gravado: a próxima passagem tenta de
    novo, em vez de achar que o mês está pronto."""
    _vazia(monkeypatch)
    servico.obter("2026-04")
    monkeypatch.setattr(coleta, "coletar_mes",
                        lambda mes, cliente=None, agora=None: _snapshot(
                            mes, "2026-08-30 10:00", n=5))
    r = servico.obter("2026-04")
    assert len(r["linhas"]) == 5
    assert coleta.ler_snapshot("2026-04", _ambiente) is not None


# ── o ramo que já existia, e continua ───────────────────────────────────────


def test_coleta_vazia_NAO_SOBRESCREVE_snapshot_bom(monkeypatch, _ambiente):
    coleta.gravar_snapshot(_snapshot("2026-06", "2026-07-01 08:00"), _ambiente)
    _vazia(monkeypatch)
    r = servico.obter("2026-06", force=True)
    assert len(r["linhas"]) == 3
    assert "mantido o snapshot" in (r["aviso"] or "")
    assert len(coleta.ler_snapshot("2026-06", _ambiente)["drivers"]) == 3


def test_o_index_nao_ganha_linha_de_mes_vazio(monkeypatch, _ambiente):
    """O index alimenta o seletor de mês e o comparativo. Um mês com zero
    motorista ali vira barra zerada no gráfico — que lê-se como queda."""
    _vazia(monkeypatch)
    servico.obter("2026-04")
    assert [i["month"] for i in coleta.ler_index(_ambiente)] == []
