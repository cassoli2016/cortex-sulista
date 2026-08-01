"""Parser OFX — cobre SGML (OFX 1.x, o dos bancos BR) e XML (2.x)."""
from __future__ import annotations

import pytest

from api.extrato.parser_ofx import _valor, parse_ofx

OFX_SGML = """OFXHEADER:100
DATA:OFXSGML
CHARSET:1252

<OFX>
<BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>341
<BRANCHID>0098
<ACCTID>539349
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260701
<DTEND>20260731
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260702120000[-03:EBT]
<TRNAMT>15000.50
<FITID>202607020001
<CHECKNUM>998877
<MEMO>TED RECEBIDA TUPY
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260703
<TRNAMT>-2340.75
<FITID>202607030002
<MEMO>PAGAMENTO FORNECEDOR
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>123456.78
<DTASOF>20260731
</LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""

OFX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<BANKACCTFROM><BANKID>237</BANKID><BRANCHID>36455</BRANCHID>
<ACCTID>1239066</ACCTID></BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260710</DTPOSTED>
<TRNAMT>-99.90</TRNAMT><FITID>X1</FITID><MEMO>TARIFA</MEMO></STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>500.00</BALAMT><DTASOF>20260710</DTASOF></LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""

OFX_DUAS_CONTAS = """<OFX>
<BANKMSGSRSV1>
<STMTTRNRS><STMTRS>
<BANKACCTFROM><BANKID>341</BANKID><BRANCHID>0098</BRANCHID><ACCTID>111</ACCTID></BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20260701</DTPOSTED><TRNAMT>100.00</TRNAMT><FITID>A1</FITID><MEMO>CONTA UM</MEMO></STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>1000.00</BALAMT><DTASOF>20260701</DTASOF></LEDGERBAL>
</STMTRS></STMTTRNRS>
<STMTTRNRS><STMTRS>
<BANKACCTFROM><BANKID>237</BANKID><BRANCHID>5555</BRANCHID><ACCTID>222</ACCTID></BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260702</DTPOSTED><TRNAMT>-50.00</TRNAMT><FITID>B1</FITID><MEMO>CONTA DOIS</MEMO></STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>2000.00</BALAMT><DTASOF>20260702</DTASOF></LEDGERBAL>
</STMTRS></STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


def test_parse_sgml_extrai_conta_lancamentos_e_saldo():
    extratos = parse_ofx(OFX_SGML.encode("cp1252"))
    assert len(extratos) == 1
    d = extratos[0]
    assert (d["banco"], d["agencia"], d["conta"]) == (341, "0098", "539349")
    assert d["ident"] == "341/0098/539349"
    assert len(d["itens"]) == 2
    credito, debito = d["itens"]
    assert credito["dt"] == "2026-07-02"
    assert credito["valor"] == 15000.50
    assert credito["tipo"] == "C"
    assert credito["fitid"] == "202607020001"
    assert credito["numerodoc"] == "998877"
    assert credito["historico"] == "TED RECEBIDA TUPY"
    assert debito["valor"] == -2340.75
    assert debito["tipo"] == "D"
    assert d["saldo"] == {"dt": "2026-07-31", "saldo": 123456.78}


def test_parse_xml_ofx2():
    extratos = parse_ofx(OFX_XML.encode("utf-8"))
    d = extratos[0]
    assert (d["banco"], d["agencia"], d["conta"]) == (237, "36455", "1239066")
    assert d["itens"][0]["valor"] == -99.90
    assert d["itens"][0]["tipo"] == "D"
    assert d["saldo"]["saldo"] == 500.00


def test_acentuacao_latin1_preservada():
    bruto = OFX_SGML.replace("TED RECEBIDA TUPY", "TRANSFERENCIA DEVOLUCAO JUROS")
    d = parse_ofx(bruto.encode("cp1252"))[0]
    assert "DEVOLUCAO" in d["itens"][0]["historico"]


def test_conteudo_nao_ofx_levanta_valueerror():
    with pytest.raises(ValueError, match="OFX"):
        parse_ofx(b"data;valor;historico\n01/07/2026;10,00;TED\n")


def test_lancamento_sem_valor_e_ignorado_e_contado():
    ruim = OFX_SGML.replace("<TRNAMT>-2340.75", "<TRNAMT>")
    d = parse_ofx(ruim.encode("cp1252"))[0]
    assert len(d["itens"]) == 1
    assert d["ignoradas"] == 1


# --- FINDING 1: separador decimal é o ÚLTIMO que aparece na string --------

@pytest.mark.parametrize("cru, esperado", [
    ("1234.56", 1234.56),
    ("-1234.56", -1234.56),
    ("1.234,56", 1234.56),
    ("1234,56", 1234.56),
    ("+1234.56", 1234.56),
    ("1,234.56", 1234.56),
    ("10,000.00", 10000.00),
    ("", None),
    ("abc", None),
])
def test_valor_formatos_numericos(cru, esperado):
    assert _valor(cru) == esperado


def test_valor_ponto_unico_e_ponto_decimal_nao_milhar():
    # spec OFX: TRNAMT é sempre ponto-decimal, mesmo com 3 dígitos depois
    assert _valor("1.234") == 1.234


# --- FINDING 2: múltiplas contas (múltiplos <STMTRS>) não se misturam -----

def test_parse_multiplas_contas_stmtrs_separados():
    extratos = parse_ofx(OFX_DUAS_CONTAS.encode("utf-8"))
    assert len(extratos) == 2
    c1, c2 = extratos
    assert (c1["banco"], c1["agencia"], c1["conta"]) == (341, "0098", "111")
    assert len(c1["itens"]) == 1
    assert c1["itens"][0]["historico"] == "CONTA UM"
    assert c1["saldo"] == {"dt": "2026-07-01", "saldo": 1000.00}
    assert (c2["banco"], c2["agencia"], c2["conta"]) == (237, "5555", "222")
    assert len(c2["itens"]) == 1
    assert c2["itens"][0]["historico"] == "CONTA DOIS"
    assert c2["saldo"] == {"dt": "2026-07-02", "saldo": 2000.00}


def test_ledgerbal_sem_dtasof_saldo_none():
    bruto = OFX_SGML.replace("<DTASOF>20260731\n", "")
    d = parse_ofx(bruto.encode("cp1252"))[0]
    assert d["saldo"] is None


def test_stmttrn_sem_dtposted_e_ignorado():
    bruto = OFX_SGML.replace("<DTPOSTED>20260703\n", "")
    d = parse_ofx(bruto.encode("cp1252"))[0]
    assert len(d["itens"]) == 1
    assert d["ignoradas"] == 1


def test_historico_usa_name_quando_sem_memo():
    bruto = OFX_XML.replace("<MEMO>TARIFA</MEMO>", "<NAME>LOJA XYZ</NAME>")
    d = parse_ofx(bruto.encode("utf-8"))[0]
    assert d["itens"][0]["historico"] == "LOJA XYZ"


def test_fitid_ausente_retorna_none():
    bruto = OFX_XML.replace("<FITID>X1</FITID>", "")
    d = parse_ofx(bruto.encode("utf-8"))[0]
    assert d["itens"][0]["fitid"] is None


def test_ofx_sem_itens_nem_saldo_levanta_valueerror():
    bruto = "<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
    with pytest.raises(ValueError, match="OFX"):
        parse_ofx(bruto.encode("utf-8"))


# --- FINDING 3: entidades HTML no histórico --------------------------------

def test_historico_decodifica_entidades_html():
    bruto = OFX_XML.replace("<MEMO>TARIFA</MEMO>", "<MEMO>J&amp;J LTDA</MEMO>")
    d = parse_ofx(bruto.encode("utf-8"))[0]
    assert d["itens"][0]["historico"] == "J&J LTDA"
