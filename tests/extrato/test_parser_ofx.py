"""Parser OFX — cobre SGML (OFX 1.x, o dos bancos BR) e XML (2.x)."""
from __future__ import annotations

import pytest

from api.extrato.parser_ofx import parse_ofx

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


def test_parse_sgml_extrai_conta_lancamentos_e_saldo():
    d = parse_ofx(OFX_SGML.encode("cp1252"))
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
    d = parse_ofx(OFX_XML.encode("utf-8"))
    assert (d["banco"], d["agencia"], d["conta"]) == (237, "36455", "1239066")
    assert d["itens"][0]["valor"] == -99.90
    assert d["itens"][0]["tipo"] == "D"
    assert d["saldo"]["saldo"] == 500.00


def test_acentuacao_latin1_preservada():
    bruto = OFX_SGML.replace("TED RECEBIDA TUPY", "TRANSFERENCIA DEVOLUCAO JUROS")
    d = parse_ofx(bruto.encode("cp1252"))
    assert "DEVOLUCAO" in d["itens"][0]["historico"]


def test_conteudo_nao_ofx_levanta_valueerror():
    with pytest.raises(ValueError, match="OFX"):
        parse_ofx(b"data;valor;historico\n01/07/2026;10,00;TED\n")


def test_lancamento_sem_valor_e_ignorado_e_contado():
    ruim = OFX_SGML.replace("<TRNAMT>-2340.75", "<TRNAMT>")
    d = parse_ofx(ruim.encode("cp1252"))
    assert len(d["itens"]) == 1
    assert d["ignoradas"] == 1
