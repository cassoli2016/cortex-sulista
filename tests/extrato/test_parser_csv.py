"""Parser CSV genérico com mapa de colunas por conta."""
from __future__ import annotations

import pytest

from api.extrato.parser_csv import parse_csv, preview_csv, valor_br

CSV_VALOR_UNICO = (
    "Data;Historico;Documento;Valor\n"
    "01/07/2026;TED RECEBIDA TUPY;998877;15.000,50\n"
    "03/07/2026;PAGAMENTO FORNECEDOR;;-2.340,75\n"
    "SALDO FINAL;;;123.456,78\n"
)

CSV_CRED_DEB = (
    "Data;Historico;Credito;Debito\n"
    "10/07/2026;DEPOSITO;1.200,00;\n"
    "11/07/2026;TARIFA;;99,90\n"
)


def test_valor_br_formatos():
    assert valor_br("15.000,50") == 15000.50
    assert valor_br("-2.340,75") == -2340.75
    assert valor_br("1.234") == 1234.00      # ponto em grupo de 3 = milhar
    assert valor_br("99,90") == 99.90
    assert valor_br("1234.56") == 1234.56    # ponto decimal (export en-US)
    assert valor_br("R$ 1.000,00") == 1000.00
    assert valor_br("") is None
    assert valor_br("abc") is None
    assert valor_br("1.2.3.4") is None       # não é milhar nem decimal válido


def test_preview_detecta_delimitador_e_amostra():
    p = preview_csv(CSV_VALOR_UNICO.encode("utf-8"))
    assert p["delim"] == ";"
    assert p["amostra"][0] == ["Data", "Historico", "Documento", "Valor"]
    assert len(p["amostra"]) == 4


def test_parse_coluna_valor_unica():
    d = parse_csv(CSV_VALOR_UNICO.encode("utf-8"),
                  {"dt": 0, "historico": 1, "numerodoc": 2, "valor": 3})
    assert len(d["itens"]) == 2
    assert d["itens"][0] == {"dt": "2026-07-01", "valor": 15000.50, "tipo": "C",
                             "historico": "TED RECEBIDA TUPY", "numerodoc": "998877",
                             "fitid": None}
    assert d["itens"][1]["valor"] == -2340.75
    assert d["itens"][1]["tipo"] == "D"
    assert d["ignoradas"] == 1          # a linha "SALDO FINAL" não tem data


def test_parse_colunas_credito_debito_separadas():
    # débito vem positivo na coluna e tem de sair NEGATIVO no lançamento
    d = parse_csv(CSV_CRED_DEB.encode("utf-8"),
                  {"dt": 0, "historico": 1, "credito": 2, "debito": 3, "cabecalho": 1})
    assert [i["tipo"] for i in d["itens"]] == ["C", "D"]
    assert d["itens"][0]["valor"] == 1200.00
    assert d["itens"][1]["valor"] == -99.90


def test_mapa_incompleto_levanta_valueerror():
    with pytest.raises(ValueError, match="coluna"):
        parse_csv(CSV_VALOR_UNICO.encode("utf-8"), {"historico": 1})


def test_encoding_latin1():
    bruto = "Data;Historico;Valor\n01/07/2026;TARIFA MANUTENCAO;-10,00\n".encode("latin-1")
    d = parse_csv(bruto, {"dt": 0, "historico": 1, "valor": 2})
    assert d["itens"][0]["historico"] == "TARIFA MANUTENCAO"
