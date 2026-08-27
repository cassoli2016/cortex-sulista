"""Conciliação nativa do ERP: as DUAS marcas de "conciliado", que discordam.

`extratobancario.situacao` é a marca da tela nativa do AVA e parou em agosto de
2023. `extratobancario_contacorrente` é o vínculo com o razão e continua sendo
alimentado todo dia. Contar só a situação punha 2.856 linhas já vinculadas na
conta de pendentes.
"""
from __future__ import annotations

import pytest

from api.extrato import servico
from api.extrato.servico import conciliacao_nativa


def _linha(situacao, vinculada, qtd, cred=0.0, deb=0.0):
    return {"situacao": situacao, "vinculada": vinculada, "qtd": qtd,
            "creditos": cred, "debitos": deb}


# Os numeros sao os reais de 27/08/2026.
RESUMO = [
    _linha(1, False, 24725, 500_000_000.0, 432_088_882.61),
    _linha(1, True, 2856, 49_313_766.04, 12_620_796.45),
    _linha(2, False, 1425, 17_000_000.0, 19_000_000.0),
    _linha(2, True, 179, 2_634_724.89, 2_389_487.78),
    _linha(3, False, 102, 482.63, 371.77),
    _linha(4, False, 68, 8_586_495.66, 233_234.53),
]
CONTAS = [{"banco": 237, "banco_nome": "BANCO BRADESCO S.A.", "agencia": "36455",
           "conta": "1239066", "total": 29355, "pendentes": 24725,
           "valor_pendente": 932_088_882.61, "marcadas": 1604, "vinculadas": 2856,
           "pendente_mais_antigo": "2023-05-18", "ultimo_movimento": "2026-08-26"}]
MENSAL = [{"mes": "2026-08", "pendentes": 391, "conciliados": 0,
           "vinculados": 17, "valor_pendente": 16_168_824.29}]
ATIVIDADE = [{"ultima_marcacao": "2023-08-28", "ultimo_vinculo": "2026-08-27",
              "ultima_carga": "2026-08-27"}]


@pytest.fixture
def _erp(monkeypatch):
    def query(sql, params=None):
        if "GROUP BY 1,2" in sql:
            return RESUMO
        if "banco_nome" in sql:
            return CONTAS
        if "to_char" in sql:
            return MENSAL
        if "ultima_marcacao" in sql:
            return ATIVIDADE
        return []

    monkeypatch.setattr(servico.db, "query", query)


def test_pendente_exclui_quem_ja_tem_vinculo(_erp):
    """O achado: 2.856 linhas ligadas ao razão contadas como pendentes."""
    k = conciliacao_nativa()["kpis"]
    assert k["pendentes"] == 24725
    assert k["pendentes_pela_situacao"] == 27581, "a leitura antiga, para comparar"
    assert k["pendentes_pela_situacao"] - k["pendentes"] == 2856


def test_o_valor_pendente_acompanha_o_novo_recorte(_erp):
    k = conciliacao_nativa()["kpis"]
    assert k["valor_pendente"] == pytest.approx(932_088_882.61)


def test_as_duas_marcas_viajam_separadas(_erp):
    """Somá-las num número só esconderia que uma delas foi abandonada."""
    k = conciliacao_nativa()["kpis"]
    assert k["marcadas"] == 1604
    assert k["vinculadas"] == 2856


def test_as_datas_das_duas_marcas_ficam_visiveis(_erp):
    k = conciliacao_nativa()["kpis"]
    assert k["ultima_marcacao"] == "2023-08-28"
    assert k["ultimo_vinculo"] == "2026-08-27"


def test_o_total_continua_sendo_o_feed_inteiro(_erp):
    k = conciliacao_nativa()["kpis"]
    assert k["total"] == 29355
    assert k["pendentes"] + k["marcadas"] + k["vinculadas"] + 102 + 68 == 29355


def test_resumo_por_situacao_diz_quantas_tem_vinculo(_erp):
    """A linha "Pendente" precisa dizer que 2.856 das suas 27.581 já estão
    ligadas ao razão — senão o resumo contradiz o KPI logo acima."""
    r = {x["situacao"]: x for x in conciliacao_nativa()["resumo"]}
    assert r["Pendente"]["qtd"] == 27581
    assert r["Pendente"]["vinculadas"] == 2856
    assert r["Conciliado"]["qtd"] == 1604
    assert r["Outro"]["qtd"] == 68, "situacao 4 nao esta no filtro da tela nativa"


def test_uma_linha_do_feed_com_varios_vinculos_nao_e_contada_duas_vezes():
    """Um lançamento do banco pode ser casado com vários do razão. O SQL usa
    `SELECT DISTINCT idextratobancario` justamente por isso; sem ele o join
    multiplicaria a linha e todo count/sum sairia inflado."""
    assert "SELECT DISTINCT idextratobancario" in servico.CONCIL_RESUMO_SQL
    assert "SELECT DISTINCT idextratobancario" in servico.CONCIL_CONTA_SQL
    assert "SELECT DISTINCT idextratobancario" in servico.CONCIL_MENSAL_SQL


def test_feed_vazio_nao_estoura(monkeypatch):
    monkeypatch.setattr(servico.db, "query", lambda *a, **k: [])
    d = conciliacao_nativa()
    assert d["kpis"]["total"] == 0
    assert d["kpis"]["pct_pendente"] == 0.0
    assert d["kpis"]["contas_com_feed"] == 0
    assert d["kpis"]["ultima_marcacao"] is None
