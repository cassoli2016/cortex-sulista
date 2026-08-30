"""Os 14 indicadores de condução, e a varredura da frota.

O QUE MUDOU E POR QUE ESTES TESTES EXISTEM
==========================================
`vehicle-performance` sempre devolveu 14 indicadores e o módulo lia 3 — os
outros 11 iam para o lixo em silêncio, inclusive `idle` (motor ligado parado) e
`greenRange` (faixa verde), que são o que a premiação pediu. Não há chamada
nova: é o mesmo GET, lendo o corpo inteiro.

A varredura da frota só passou a ser possível porque a premissa de custo estava
errada: o módulo dizia "~17 s por chamada, mais de 20 minutos a frota". Medido
em 30/08/2026 sobre 108 placas: **0,79 s por placa, 86 s a frota**.
"""
from __future__ import annotations

import pytest

from api.gobrax import armazenamento, performance


def _ind(pct, nota=0, dur=None):
    return {"duration": dur if dur is not None else pct * 2,
            "percentage": pct, "score": nota}


def _resp(placa, **pcts):
    return {"records": [{
        "vehicleIdentification": placa,
        "drivers": [{"driverName": "MARCOS SANTOS", "cpf": "11122233344",
                     "startDate": "2026-08-01T00:00:00+0000",
                     "endDate": "2026-08-31T23:59:59+0000"}],
        "indicators": {k: _ind(v) for k, v in pcts.items()}}]}


class ClienteFalso:
    """Devolve resposta por placa. Copiar o corpo REAL do fornecedor, campos
    'inúteis' inclusive, é a lição da Z-API: o dublê otimista testa um
    fornecedor que não existe."""

    def __init__(self, por_placa, falham=()):
        self.por_placa = por_placa
        self.falham = set(falham)
        self.chamadas = []

    def get(self, caminho, params=None, timeout=120):
        placa = (params or {}).get("vehicleIdentification", "")
        self.chamadas.append(placa)
        if placa in self.falham:
            raise RuntimeError("instabilidade do fornecedor")
        return self.por_placa.get(placa, {"records": []})


# ── o catálogo ──────────────────────────────────────────────────────────────


def test_o_catalogo_tem_os_14_e_as_familias_batem():
    assert len(performance.INDICADORES) == 14
    assert set(performance.ORDEM) == set(performance.INDICADORES)


def test_os_dois_indicadores_pedidos_estao_no_catalogo():
    """`idle` e `greenRange` foram o pedido explícito; eram descartados."""
    assert performance.INDICADORES["idle"] == "Motor ligado parado"
    assert performance.INDICADORES["greenRange"] == "Faixa verde"


def test_onde_MENOS_e_melhor_esta_declarado():
    """Sem isto a tela pintaria "motor ligado parado 60%" de verde por ser um
    número alto — o oposto da leitura."""
    assert "idle" in performance.MENOR_MELHOR
    assert "speeding" in performance.MENOR_MELHOR
    assert "greenRange" not in performance.MENOR_MELHOR


def test_le_os_indicadores_que_antes_eram_descartados():
    c = ClienteFalso({"AAA1A11": _resp("AAA1A11", idle=26.8, greenRange=92.7,
                                       speeding=3.1)})
    d = performance.coletar("AAA1A11", "2026-08", cliente=c)
    por = {i["chave"]: i for i in d["indicadores"]}
    assert por["idle"]["percentual"] == 26.8
    assert por["greenRange"]["percentual"] == 92.7
    assert por["idle"]["menor_melhor"] is True


def test_a_nota_do_fornecedor_vem_junto_mas_com_nome_proprio():
    """`nota_fornecedor` e não `nota`: a régua que paga é a da casa, e o nome
    do campo tem de impedir que alguém use uma pela outra sem perceber.
    Medido: 6 dos 14 indicadores vieram com nota 0 em 108 de 108 veículos."""
    c = ClienteFalso({"A": _resp("A", idle=10.0)})
    i = performance.coletar("A", "2026-08", cliente=c)["indicadores"][0]
    assert "nota_fornecedor" in i and "nota" not in i


# ── a varredura ─────────────────────────────────────────────────────────────


def test_o_universo_da_varredura_sai_do_cache_de_estatisticas(tmp_path):
    """E não de uma chamada nova: assim a varredura não inventa um universo
    próprio que discordaria do resto da telemetria."""
    p = tmp_path / "t.db"
    armazenamento.init_db(p)
    armazenamento.gravar("estatisticas", "2026-08",
                         [{"placa": "AAA1A11", "km": 100.0},
                          {"placa": "BBB2B22", "km": 50.0},
                          {"placa": "SEMKM99", "km": None}], p)
    assert performance.placas_da_competencia("2026-08", p) == ["AAA1A11", "BBB2B22"]


def test_uma_placa_que_FALHA_nao_derruba_a_varredura(tmp_path):
    """São 108 chamadas: uma instabilidade no meio não pode custar as outras
    107. A que falhou fica de fora e a próxima execução tenta de novo."""
    c = ClienteFalso({"A1": _resp("A1", idle=10.0), "A3": _resp("A3", idle=20.0)},
                     falham={"A2"})
    linhas = performance.coletar_frota("2026-08", cliente=c, placas=["A1", "A2", "A3"])
    assert [l["placa"] for l in linhas] == ["A1", "A3"]
    assert c.chamadas == ["A1", "A2", "A3"], "tentou as três"


def test_placa_sem_indicador_nao_entra(tmp_path):
    """Veículo sem medida no mês não é veículo com medida zero."""
    c = ClienteFalso({"A1": _resp("A1", idle=10.0), "A2": {"records": []}})
    linhas = performance.coletar_frota("2026-08", cliente=c, placas=["A1", "A2"])
    assert [l["placa"] for l in linhas] == ["A1"]


# ── o resumo, que dá referência ao número individual ────────────────────────


def _povoar(p, dados, comp="2026-08"):
    armazenamento.init_db(p)
    linhas = [{"placa": pl, "motoristas": [],
               **{k: {"pct": v, "h": v * 2, "nota": nota}
                  for k, (v, nota) in ind.items()}}
              for pl, ind in dados.items()]
    armazenamento.gravar(performance.COLECAO, comp, linhas, p)


def test_o_resumo_da_a_distribuicao_da_frota(tmp_path):
    """Um número sozinho não decide nada: "motor ligado parado 18%" é muito?
    Só a mediana da frota responde."""
    p = tmp_path / "t.db"
    _povoar(p, {f"P{i}": {"idle": (float(i), 0)} for i in range(1, 11)})
    r = performance.resumo_frota("2026-08", p)
    idle = [i for i in r["indicadores"] if i["chave"] == "idle"][0]
    assert r["veiculos"] == 10
    assert idle["min"] == 1.0 and idle["max"] == 10.0
    assert idle["mediana"] == 6.0


def test_o_resumo_ACUSA_indicador_com_nota_zerada_na_frota_toda(tmp_path):
    """Sem esse aviso, a nota do fornecedor zerada em todos passaria como
    desempenho ruim generalizado. Medido: acontece em 6 dos 14 indicadores."""
    p = tmp_path / "t.db"
    _povoar(p, {"P1": {"greenRange": (95.0, 0), "idle": (10.0, 7)},
                "P2": {"greenRange": (97.0, 0), "idle": (12.0, 3)}})
    r = performance.resumo_frota("2026-08", p)
    por = {i["chave"]: i for i in r["indicadores"]}
    assert por["greenRange"]["nota_zerada"] is True
    assert por["idle"]["nota_zerada"] is False


def test_o_resumo_ignora_indicador_sem_medida(tmp_path):
    p = tmp_path / "t.db"
    _povoar(p, {"P1": {"idle": (10.0, 0)}})
    r = performance.resumo_frota("2026-08", p)
    assert {i["chave"] for i in r["indicadores"]} == {"idle"}
