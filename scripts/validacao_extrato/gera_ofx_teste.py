"""Gera um OFX de validação da tela de Extrato Bancário.

Usa a conta REAL do ERP (Itaú 341/0098/539349) e os valores REAIS de
contacorrente_saldo de jul/2026, para a comparação produzir resultado
verificável em vez de dado sintético que só bate consigo mesmo.

Desenho do cenário:
  01, 02 e 03/07 -> valores idênticos ao ERP  => devem sair OK
  06/07          -> débito 350.000,00 no lugar de 353.533,69 (erro proposital
                    de R$ 3.533,69) => deve sair DIVERGE, no débito e no saldo

A âncora (LEDGERBAL) é o saldo de 03/07 (R$ 429,36), o mesmo do ERP: derivando
para trás, os saldos de 02 e 01/07 reproduzem os do ERP ao centavo (verificado).
"""
from pathlib import Path

CONTA = ("341", "0098", "539349")
# (data, historico, valor com sinal)  -- credito +, debito -
LANC = [
    ("20260701", "TED RECEBIDA CLIENTES", 918000.00),
    ("20260701", "PAGAMENTOS FORNECEDORES", -935988.17),
    ("20260702", "TED RECEBIDA CLIENTES", 1753000.00),
    ("20260702", "PAGAMENTOS DIVERSOS", -801194.56),
    ("20260703", "PAGAMENTOS DIVERSOS", -628795.77),
    # divergencia proposital: o ERP tem 353.533,69 de debito neste dia
    ("20260706", "TED RECEBIDA CLIENTES", 357228.45),
    ("20260706", "PAGAMENTOS FORNECEDORES", -350000.00),
]
SALDO_FINAL = ("20260703", 429.36)


def stmttrn(i: int, dt: str, hist: str, valor: float) -> str:
    tipo = "CREDIT" if valor >= 0 else "DEBIT"
    return (f"<STMTTRN>\n<TRNTYPE>{tipo}\n<DTPOSTED>{dt}120000[-03:BRT]\n"
            f"<TRNAMT>{valor:.2f}\n<FITID>{dt}{i:04d}\n<MEMO>{hist}\n</STMTTRN>")


def main() -> None:
    banco, ag, cc = CONTA
    corpo = "\n".join(stmttrn(i, *l) for i, l in enumerate(LANC, 1))
    ofx = f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
CHARSET:1252

<OFX>
<BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>{banco}
<BRANCHID>{ag}
<ACCTID>{cc}
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260701
<DTEND>20260731
{corpo}
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>{SALDO_FINAL[1]:.2f}
<DTASOF>{SALDO_FINAL[0]}
</LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""
    destino = Path(__file__).with_name("itau_539349_jul2026.ofx")
    # banco brasileiro emite cp1252, nao utf-8 - o parser tem de lidar com isso
    destino.write_bytes(ofx.encode("cp1252"))
    print(f"gravado: {destino}  ({destino.stat().st_size} bytes)")
    print(f"lancamentos: {len(LANC)} | esperado: 01,02,03/07 OK e 06/07 DIVERGE")


if __name__ == "__main__":
    main()
