"""Defeitos que só apareceram quando sete extratos REAIS passaram pelo parser.

Bradesco, Caixa, Itaú, Safra, Santander e Sicredi, agosto/2026 — 756 lançamentos.
Nenhum arquivo real entra no repositório (a pasta `extratos/` é ignorada e o
conteúdo é dado bancário da empresa); cada fixture aqui REPRODUZ a estrutura
exata do defeito medido, com valores inventados.

O que os sete arquivos derrubaram, e cada um tem teste abaixo:

  1. FITID não é único em banco brasileiro. Confiando nele como chave inteira,
     50 dos 65 lançamentos da Caixa eram descartados como "duplicada".
  2. Linha de saldo diário vem como `<STMTTRN>` e era somada como movimento —
     no Itaú, R$ 157.152,97 de movimento aparente contra R$ 4.028,73 reais.
  3. `TRNTYPE=BALANCE` não prova nada: o Safra marca assim TAMBÉM o movimento.
  4. Data zerada (`DTASOF 00000000`, Bradesco) virava o dia "0000-00-00".
  5. O arquivo de compromissos do Bradesco é idêntico ao de extrato e traz
     lançamentos futuros.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api.extrato import armazenamento as arm
from api.extrato.parser_ofx import parse_ofx
from api.extrato.servico import importar


def _ofx(transacoes: str, ledgerbal: str = "", banco: str = "104",
         conta: str = "0005772214779") -> bytes:
    return f"""OFXHEADER:100
DATA:OFXSGML
CHARSET:1252

<OFX>
<BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>{banco}
<ACCTID>{conta}
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
{transacoes}
</BANKTRANLIST>
{ledgerbal}
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
""".encode("cp1252")


def _trn(dt: str, valor: str, fitid: str, memo: str,
         tipo: str = "CREDIT", doc: str = "0") -> str:
    return (f"<STMTTRN>\n<TRNTYPE>{tipo}\n<DTPOSTED>{dt}000000[-3:GMT]\n"
            f"<TRNAMT>{valor}\n<FITID>{fitid}\n<CHECKNUM>{doc}\n"
            f"<MEMO>{memo}\n</STMTTRN>")


# ---------------------------------------------------------------- 1. FITID

# O padrão exato da Caixa: o FITID repetido é "341" — o código do banco de
# ORIGEM da TED (Itaú), não um identificador de transação. Vinte e seis
# créditos de valores completamente diferentes carregavam o mesmo "341".
CAIXA_FITID_REPETIDO = _ofx(
    "\n".join([
        _trn("20260803", "3589.77", "341", "CRED TED", doc="341"),
        _trn("20260803", "287641.95", "341", "CRED TED", doc="341"),
        _trn("20260805", "337736.02", "341", "CRED TED", doc="341"),
        _trn("20260819", "376977.74", "341", "CRED TED", doc="341"),
    ]))


def _sql(esquema, sql, params=None):
    """Lê o banco CRU: a asserção é sobre o que FOI GRAVADO. Era sqlite3,
    agora é o schema do teste no PostgreSQL."""
    from api import pglocal
    return pglocal.query(sql, params, esquema=esquema)


def test_fitid_repetido_nao_descarta_lancamento(esquema_pg):
    """Quatro créditos distintos com o mesmo FITID entram como quatro."""
    db = esquema_pg
    r = importar(CAIXA_FITID_REPETIDO, "caixa.ofx", esquema=db)
    assert r["novas"] == 4, "FITID repetido não pode colapsar lançamentos"
    assert r["duplicadas"] == 0
    total = _sql(db, "SELECT sum(valor) AS t FROM ext_lancamento")[0]["t"]
    assert total == pytest.approx(1005945.48)


def test_reimport_do_mesmo_arquivo_continua_deduplicando(esquema_pg):
    """A troca de chave não pode custar a deduplicação — que é o motivo de ela existir."""
    db = esquema_pg
    importar(CAIXA_FITID_REPETIDO, "caixa.ofx", esquema=db)
    r = importar(CAIXA_FITID_REPETIDO, "caixa.ofx", esquema=db)
    assert r["novas"] == 0
    assert r["duplicadas"] == 4


def test_lancamentos_gemeos_no_mesmo_arquivo_entram_os_dois(esquema_pg):
    """Mesma data, mesmo valor, mesmo histórico e mesmo doc: são três de verdade
    (três tarifas PIX de R$ 8,50 no mesmo dia, caso real da Caixa)."""
    db = esquema_pg
    bruto = _ofx("\n".join([
        _trn("20260804", "-8.50", "41527", "TAR PIX", tipo="DEBIT", doc="41527"),
        _trn("20260804", "-8.50", "41527", "TAR PIX", tipo="DEBIT", doc="41527"),
        _trn("20260804", "-8.50", "41527", "TAR PIX", tipo="DEBIT", doc="41527"),
    ]))
    assert importar(bruto, "caixa.ofx", esquema=db)["novas"] == 3


# ------------------------------------------------------- 2 e 3. linha de saldo

# Itaú: o saldo do dia vem como transação CREDIT/DEBIT comum — o TRNTYPE não
# denuncia. Os números abaixo são os reais, e servem à conferência aritmética.
ITAU_SALDO_COMO_MOVIMENTO = _ofx(
    "\n".join([
        _trn("20260731", "-2703.15", "20260731001", "SALDO ANTERIOR", tipo="DEBIT"),
        _trn("20260803", "-28452.39", "20260803001", "SISPAG FORNECEDORES", tipo="DEBIT"),
        _trn("20260803", "-31155.54", "20260803009", "SALDO TOTAL DISPONIVEL DIA", tipo="DEBIT"),
        _trn("20260804", "32554.64", "20260804001", "TED RECEBIDA LEAR"),
        _trn("20260804", "1399.10", "20260804009", "SALDO TOTAL DISPONIVEL DIA"),
    ]),
    ledgerbal="<LEDGERBAL>\n<BALAMT>1399.10\n<DTASOF>20260804\n</LEDGERBAL>",
    banco="341", conta="0098539349")


def test_linha_de_saldo_nao_e_movimento():
    d = parse_ofx(ITAU_SALDO_COMO_MOVIMENTO)[0]
    assert len(d["itens"]) == 2, "só SISPAG e TED são movimento"
    assert {i["historico"] for i in d["itens"]} == {
        "SISPAG FORNECEDORES", "TED RECEBIDA LEAR"}
    assert d["linhas_saldo"] == 3


def test_linha_de_saldo_vira_ancora_por_dia():
    d = parse_ofx(ITAU_SALDO_COMO_MOVIMENTO)[0]
    ancoras = {s["dt"]: s["saldo"] for s in d["saldos"]}
    assert ancoras == {"2026-07-31": -2703.15, "2026-08-03": -31155.54,
                       "2026-08-04": 1399.10}


def test_cadeia_de_saldo_fecha_com_o_movimento():
    """A conferência que vale para QUALQUER banco novo, e que foi quem pegou o
    erro do `TRNTYPE=BALANCE`: âncora do dia == âncora anterior + movimento."""
    d = parse_ofx(ITAU_SALDO_COMO_MOVIMENTO)[0]
    mov: dict[str, float] = {}
    for i in d["itens"]:
        mov[i["dt"]] = mov.get(i["dt"], 0.0) + i["valor"]
    linhas = [s for s in d["saldos"] if s["origem"] == "linha"]
    for ant, atual in zip(linhas, linhas[1:]):
        esperado = ant["saldo"] + mov.get(atual["dt"], 0.0)
        assert atual["saldo"] == pytest.approx(esperado, abs=0.01), atual["dt"]


# Safra: marca com BALANCE a abertura, o MOVIMENTO e o fechamento do dia.
SAFRA_BALANCE_EM_TUDO = _ofx(
    "\n".join([
        _trn("20260826", "657.41", "08261", "SALDO INICIAL", tipo="BALANCE"),
        _trn("20260826", "-656.45", "08262", " BLOQUEIO JUDICIAL", tipo="BALANCE"),
        _trn("20260826", "0.96", "08263", "SALDO TOTAL", tipo="BALANCE"),
    ]), banco="422", conta="00380012235")


def test_trntype_balance_nao_basta_para_descartar():
    """O bloqueio judicial está marcado como BALANCE e é movimento de verdade."""
    d = parse_ofx(SAFRA_BALANCE_EM_TUDO)[0]
    assert [i["historico"] for i in d["itens"]] == ["BLOQUEIO JUDICIAL"]
    assert d["itens"][0]["valor"] == pytest.approx(-656.45)


def test_ultima_linha_de_saldo_do_dia_vence():
    """Abertura (657,41) e fechamento (0,96) no mesmo dia: fica o fechamento."""
    d = parse_ofx(SAFRA_BALANCE_EM_TUDO)[0]
    assert d["saldos"] == [{"dt": "2026-08-26", "saldo": 0.96, "origem": "linha"}]


def test_historico_que_contem_saldo_no_meio_continua_movimento():
    """Tarifa real do Santander — casar a palavra solta descartaria cobrança."""
    bruto = _ofx(_trn("20260825", "-1204.55",
                      "S1", "JUROS SALDO UTILIZ ATE LIMITE PERIODO: 25/07 A 24/08/26",
                      tipo="DEBIT"), banco="033", conta="4849130000265")
    d = parse_ofx(bruto)[0]
    assert len(d["itens"]) == 1
    assert d["linhas_saldo"] == 0


def test_linha_de_saldo_vence_o_ledgerbal_do_mesmo_dia():
    """No Safra o LEDGERBAL é a posição consolidada (conta + aplicação) e a
    linha é a conta corrente — que é o que o `contacorrente_saldo` do ERP tem."""
    bruto = _ofx(_trn("20260824", "657.38", "08242", "SALDO TOTAL", tipo="BALANCE"),
                 ledgerbal="<LEDGERBAL>\n<BALAMT>10502.92\n<DTASOF>20260824\n</LEDGERBAL>",
                 banco="422", conta="00380012235")
    d = parse_ofx(bruto)[0]
    assert d["saldos"] == [{"dt": "2026-08-24", "saldo": 657.38, "origem": "linha"}]
    assert d["saldo"] == {"dt": "2026-08-24", "saldo": 10502.92}, "LEDGERBAL segue exposto"


# ------------------------------------------------------------------ 4. data

def test_dtasof_zerado_nao_vira_ancora():
    """Bradesco grava `00000000`; "0000-00-00" nunca casaria com dia do ERP."""
    bruto = _ofx(_trn("20260803", "100.00", "F1", "TED"),
                 ledgerbal="<LEDGERBAL>\n<BALAMT>619059.53\n<DTASOF>00000000000000\n</LEDGERBAL>",
                 banco="237", conta="123906")
    d = parse_ofx(bruto)[0]
    assert d["saldo"] is None
    assert d["saldos"] == []
    assert len(d["itens"]) == 1, "o lançamento bom continua entrando"


def test_data_de_lancamento_impossivel_conta_como_ignorada():
    bruto = _ofx("\n".join([
        _trn("20260230", "10.00", "F1", "DIA 30 DE FEVEREIRO"),
        _trn("20260803", "20.00", "F2", "TED BOA"),
    ]))
    d = parse_ofx(bruto)[0]
    assert d["ignoradas"] == 1
    assert len(d["itens"]) == 1


# -------------------------------------------------------------- 5. futuros

def test_lancamento_futuro_nao_entra_e_e_contado(esquema_pg):
    """O arquivo de compromissos do Bradesco é OFX idêntico ao do extrato."""
    db = esquema_pg
    futuro = (date.today() + timedelta(days=15)).strftime("%Y%m%d")
    ontem = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    bruto = _ofx("\n".join([
        _trn(ontem, "-3.00", "B1", "TARIFA", tipo="DEBIT"),
        _trn(futuro, "-85433.92", "B2", "PARCELAMENTO DE DARF", tipo="DEBIT"),
    ]), banco="237", conta="123906")
    r = importar(bruto, "bradesco_comp.ofx", esquema=db)
    assert r["novas"] == 1
    assert r["futuras"] == 1
    maior = _sql(db, "SELECT max(dt) AS m FROM ext_lancamento")[0]["m"]
    assert maior <= date.today().isoformat()


def test_futuro_nao_desliga_o_alerta_de_extrato_velho(esquema_pg):
    """Era o efeito prático: `dias_sem_extrato` saía -20 e a conta ficava
    permanentemente "em dia", porque o farol só acusa atraso acima de 7 dias."""
    db = esquema_pg
    velho = (date.today() - timedelta(days=40)).strftime("%Y%m%d")
    futuro = (date.today() + timedelta(days=20)).strftime("%Y%m%d")
    bruto = _ofx("\n".join([
        _trn(velho, "-3.00", "B1", "TARIFA", tipo="DEBIT"),
        _trn(futuro, "-100.00", "B2", "CONTA DE LUZ", tipo="DEBIT"),
    ]), banco="237", conta="123906")
    importar(bruto, "bradesco_comp.ofx", esquema=db)
    ultimos = arm.ultimo_dt_por_conta(db)
    assert ultimos, "a conta tem de existir"
    assert all(dt <= date.today().isoformat() for dt in ultimos.values())


# ------------------------------------------------------------- 6. migração

# `test_migracao_reescreve_chaves_no_formato_antigo` FOI REMOVIDO na migração
# para o PostgreSQL (27/08/2026), junto com `_remigra_chaves`, a função que ele
# protegia. Ela recalculava chaves no formato antigo `fitid:<id>`, e a base foi
# conferida com ZERO linhas nesse formato antes de migrar; a partir daqui só
# existe o formato novo. `scripts/migrar_extrato.py` se recusa a rodar se
# encontrar uma chave antiga — é onde a guarda passou a morar.
#
# O que aquele teste também cobria — reimport do mesmo arquivo não duplicar —
# segue coberto por `test_reimport_do_mesmo_arquivo_continua_deduplicando`.
