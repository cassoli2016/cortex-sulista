"""driversOverview -> motoristas com km e nota. Sem CPF, sem Reward."""
from __future__ import annotations

from api.gobrax import overview

RESPOSTA = {"success": True, "data": [
    {"ID": 13, "Name": "3190 - JEAN LAURO", "DocumentNumber": "12345678901",
     "Err": "", "Overview": [
         {"Date": "03-2026", "Reward": 0, "TotalKM": 2922, "Score": 93, "Err": ""},
         {"Date": "04-2026", "Reward": 0, "TotalKM": 5200, "Score": 99, "Err": ""}]},
    {"ID": 14, "Name": "3773 - AGNALDO", "DocumentNumber": "98765432100",
     "Err": "", "Overview": [
         {"Date": "03-2026", "Reward": 0, "TotalKM": 3094, "Score": 85, "Err": ""}]},
    {"ID": 15, "Name": "SEM ATIVIDADE", "DocumentNumber": "11111111111",
     "Err": "", "Overview": [
         {"Date": "03-2026", "Reward": 0, "TotalKM": 0, "Score": 0,
          "Err": "performance data not found"}]},
]}


class ClienteFalso:
    def __init__(self, resposta=None):
        self.resposta = resposta if resposta is not None else RESPOSTA
        self.chamadas = []

    def get(self, caminho, params=None, timeout=120):
        self.chamadas.append((caminho, params))
        return self.resposta


def test_traz_so_o_mes_pedido():
    """A API devolve o mês pedido E o seguinte, porque endDate tem de ser
    diferente. Só o mês pedido interessa."""
    c = ClienteFalso()
    linhas = overview.coletar("2026-03", cliente=c)
    assert {l["driverName"] for l in linhas} == {"3190 - JEAN LAURO", "3773 - AGNALDO"}
    assert [l["km"] for l in linhas if l["driverId"] == 13] == [2922]


def test_pede_o_periodo_no_formato_da_api():
    c = ClienteFalso()
    overview.coletar("2026-03", cliente=c)
    _caminho, params = c.chamadas[0]
    assert params["startDate"] == "03-2026"
    assert params["endDate"] == "04-2026"


def test_motorista_sem_atividade_fica_de_fora():
    linhas = overview.coletar("2026-03", cliente=ClienteFalso())
    assert all(l["driverName"] != "SEM ATIVIDADE" for l in linhas)


def test_nunca_devolve_documento_nem_reward():
    """CPF é PII e não tem uso aqui; Reward vem zerado da API e o cálculo é
    nosso — carregar os dois só cria chance de erro."""
    linhas = overview.coletar("2026-03", cliente=ClienteFalso())
    for l in linhas:
        assert "documento" not in l and "DocumentNumber" not in l
        assert "reward" not in l and "Reward" not in l
    assert "12345678901" not in repr(linhas)


def test_campos_do_retorno():
    l = overview.coletar("2026-03", cliente=ClienteFalso())[0]
    assert sorted(l.keys()) == ["driverId", "driverName", "km", "nota"]


def test_resposta_sem_data_devolve_lista_vazia():
    assert overview.coletar("2026-03", cliente=ClienteFalso({"success": True})) == []


def test_resposta_de_insucesso_devolve_lista_vazia():
    """Lista vazia sobe para quem chama decidir — e a regra da casa é que
    coleta vazia não sobrescreve snapshot bom."""
    c = ClienteFalso({"success": False, "data": None})
    assert overview.coletar("2026-03", cliente=c) == []
