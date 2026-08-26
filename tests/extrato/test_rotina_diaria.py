"""A rotina de subir o extrato do dia anterior, todo dia.

Três coisas que só o uso diário quebra, e que a importação de um arquivo
mensal inteiro nunca exercita:

  1. O mesmo lançamento chegando em vários envios (janela móvel, reenvio).
  2. O `LEDGERBAL` de um envio novo pisando numa âncora boa de um envio velho.
  3. O atraso medido em dias corridos punindo a segunda-feira e perdoando uma
     semana inteira.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from api.extrato import armazenamento as arm
from api.extrato.comparacao import atraso_uteis, farol
from api.extrato.servico import importar, posicao


def _ofx(trns: str, ledgerbal: str = "", banco: str = "341",
         conta: str = "0098539349") -> bytes:
    return f"""OFXHEADER:100
DATA:OFXSGML
CHARSET:1252

<OFX>
<BANKMSGSRSV1><STMTTRNRS><STMTRS>
<BANKACCTFROM>
<BANKID>{banco}
<ACCTID>{conta}
</BANKACCTFROM>
<BANKTRANLIST>
{trns}
</BANKTRANLIST>
{ledgerbal}
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
""".encode("cp1252")


def _trn(dt: str, valor: str, fitid: str, memo: str, tipo: str = "CREDIT") -> str:
    return (f"<STMTTRN>\n<TRNTYPE>{tipo}\n<DTPOSTED>{dt}000000[-3:GMT]\n"
            f"<TRNAMT>{valor}\n<FITID>{fitid}\n<CHECKNUM>0\n"
            f"<MEMO>{memo}\n</STMTTRN>")


def _ledger(valor: str, dt: str) -> str:
    return f"<LEDGERBAL>\n<BALAMT>{valor}\n<DTASOF>{dt}\n</LEDGERBAL>"


def _ymd(dias_atras: int) -> str:
    return (date.today() - timedelta(days=dias_atras)).strftime("%Y%m%d")


@pytest.fixture(autouse=True)
def _erp_mudo(monkeypatch):
    """Nenhum teste deste arquivo fala com o AVA.

    `posicao()` consulta o ERP, e o `try/except` dela engolia a falha de
    conexão — então a suíte PASSAVA, mas gastando o timeout do pool a cada
    chamada e deixando threads penduradas. Teste que depende de rede não é
    teste; o caso do ERP fora é exercitado de propósito, com exceção, em
    `test_posicao_nao_cai_com_o_erp_fora`.
    """
    from api.extrato import servico

    monkeypatch.setattr(servico.db, "query", lambda *a, **k: [])


# ----------------------------------------------- 1. envio incremental

def test_envio_diario_nao_duplica_nem_perde(tmp_path):
    """Três dias, um arquivo por dia — o resultado tem de ser o mesmo de um
    arquivo só com os três."""
    inc, tudo = tmp_path / "inc.db", tmp_path / "tudo.db"
    dias = [
        _trn("20260803", "1500.00", "F1", "TED TUPY"),
        _trn("20260804", "-230.75", "F2", "PAGTO FORNECEDOR", tipo="DEBIT"),
        _trn("20260805", "980.10", "F3", "PIX RECEBIDO"),
    ]
    for d in dias:
        importar(_ofx(d), "itau.ofx", path=inc)
    importar(_ofx("\n".join(dias)), "itau.ofx", path=tudo)

    def linhas(db):
        con = sqlite3.connect(db)
        r = sorted(con.execute("SELECT dt, round(valor,2), historico FROM ext_lancamento"))
        con.close()
        return r

    assert linhas(inc) == linhas(tudo)
    assert len(linhas(inc)) == 3


def test_janela_movel_reconhece_o_que_ja_entrou(tmp_path):
    """Vários bancos entregam os últimos N dias a cada download; a sobreposição
    não pode virar lançamento repetido."""
    db = tmp_path / "e.db"
    d1 = _trn("20260803", "1500.00", "F1", "TED TUPY")
    d2 = _trn("20260804", "-230.75", "F2", "PAGTO", tipo="DEBIT")
    d3 = _trn("20260805", "980.10", "F3", "PIX")
    importar(_ofx("\n".join([d1, d2])), "itau.ofx", path=db)
    r = importar(_ofx("\n".join([d2, d3])), "itau.ofx", path=db)
    assert r["novas"] == 1
    assert r["duplicadas"] == 1
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM ext_lancamento").fetchone()[0] == 3


def test_reenviar_o_mesmo_arquivo_nao_muda_nada(tmp_path):
    db = tmp_path / "e.db"
    bruto = _ofx(_trn("20260803", "1500.00", "F1", "TED TUPY"))
    importar(bruto, "itau.ofx", path=db)
    r = importar(bruto, "itau.ofx", path=db)
    assert (r["novas"], r["duplicadas"]) == (0, 1)


# ------------------------------------------ 2. precedência da âncora

def test_ledgerbal_novo_nao_pisa_na_linha_de_saldo_ja_gravada(tmp_path):
    """O defeito que só o envio diário provoca.

    Medido no Safra: o `LEDGERBAL` diz R$ 10.502,92 (posição consolidada, conta
    + aplicação) e a linha do MESMO dia diz R$ 657,38 (a conta corrente, que é
    o que o ERP guarda). O arquivo de amanhã repete aquele `LEDGERBAL` com a
    data de ontem — e reescrevia o número certo pelo errado.
    """
    db = tmp_path / "e.db"
    # dia 1: o arquivo traz a linha de saldo do dia 24
    importar(_ofx(_trn("20260824", "657.38", "S1", "SALDO TOTAL", tipo="BALANCE"),
                  banco="422", conta="00380012235"), "safra.ofx", path=db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT round(saldo,2) FROM ext_saldo WHERE dt='2026-08-24'"
                       ).fetchone()[0] == pytest.approx(657.38)
    con.close()

    # dia 2: arquivo novo, cujo LEDGERBAL ainda aponta para o dia 24
    importar(_ofx(_trn("20260825", "0.03", "S2", "RENDIMENTO CDB"),
                  ledgerbal=_ledger("10502.92", "20260824"),
                  banco="422", conta="00380012235"), "safra.ofx", path=db)
    con = sqlite3.connect(db)
    saldo, origem = con.execute(
        "SELECT round(saldo,2), origem FROM ext_saldo WHERE dt='2026-08-24'").fetchone()
    con.close()
    assert saldo == pytest.approx(657.38), "o LEDGERBAL sobrescreveu a linha de saldo"
    assert origem == "linha"


def test_linha_de_saldo_corrige_um_ledgerbal_ja_gravado(tmp_path):
    """O sentido inverso PRECISA sobrescrever: linha é dado melhor."""
    db = tmp_path / "e.db"
    importar(_ofx(_trn("20260824", "10.00", "A1", "TED"),
                  ledgerbal=_ledger("10502.92", "20260824"),
                  banco="422", conta="00380012235"), "safra.ofx", path=db)
    importar(_ofx(_trn("20260824", "657.38", "S1", "SALDO TOTAL", tipo="BALANCE"),
                  banco="422", conta="00380012235"), "safra.ofx", path=db)
    con = sqlite3.connect(db)
    saldo, origem = con.execute(
        "SELECT round(saldo,2), origem FROM ext_saldo WHERE dt='2026-08-24'").fetchone()
    con.close()
    assert saldo == pytest.approx(657.38)
    assert origem == "linha"


def test_ledgerbal_mais_novo_atualiza_outro_ledgerbal(tmp_path):
    """Origem igual: o envio mais recente manda (é como se corrige um número)."""
    db = tmp_path / "e.db"
    for v in ("100.00", "250.00"):
        importar(_ofx(_trn("20260824", "10.00", "A1", "TED"),
                      ledgerbal=_ledger(v, "20260824")), "itau.ofx", path=db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT round(saldo,2) FROM ext_saldo").fetchone()[0] == pytest.approx(250.0)
    con.close()


# ------------------------------------------------- 3. atraso em dias úteis

@pytest.mark.parametrize("ultimo,hoje,esperado", [
    ("2026-08-24", "2026-08-25", 0),    # segunda -> terça: em dia
    ("2026-08-21", "2026-08-24", 0),    # sexta -> segunda: o fim de semana não conta
    ("2026-08-21", "2026-08-25", 1),    # sexta -> terça: pulou a segunda
    ("2026-08-25", "2026-08-25", 0),    # mesmo dia
    ("2026-08-26", "2026-08-25", 0),    # extrato à frente de hoje: nunca negativo
    ("2026-07-20", "2026-08-01", 9),    # doze dias corridos, nove úteis
])
def test_atraso_conta_so_dia_util_pulado(ultimo, hoje, esperado):
    assert atraso_uteis(ultimo, hoje) == esperado


def _dia(dt, estado="OK"):
    return {"dt": dt, "estado": estado, "d_saldo": None,
            "d_credito": None, "d_debito": None}


def test_farol_perdoa_a_segunda_feira():
    """A régua antiga era de dias corridos: sexta para segunda são três dias, e
    toda segunda a conta parecia atrasada sem estar."""
    f = farol([_dia("2026-08-21")], "2026-08-21", "2026-08-24")
    assert f["estado"] == "ok"
    assert f["atraso_uteis"] == 0
    assert f["dias_sem_extrato"] == 3, "o corrido continua no payload, para o texto"


def test_farol_acende_bem_antes_dos_sete_dias():
    """Com a régua de sete dias corridos, três dias úteis pulados ficavam
    verdes — uma semana de silêncio numa rotina diária."""
    f = farol([_dia("2026-08-19")], "2026-08-19", "2026-08-25")
    assert f["atraso_uteis"] == 3
    assert f["estado"] == "desatualizado"
    assert f["dias_sem_extrato"] == 6, "seis corridos: a régua velha deixaria passar"


def test_farol_tolera_um_dia_util():
    f = farol([_dia("2026-08-21")], "2026-08-21", "2026-08-25")
    assert f["atraso_uteis"] == 1
    assert f["estado"] == "ok"


# ------------------------------------------------------------ posição

def test_posicao_soma_so_quem_tem_saldo_e_declara_quem_ficou_de_fora(tmp_path):
    """Conta sem âncora fica FORA do total e com o motivo — nunca com zero,
    que é um saldo e não uma ausência."""
    db = tmp_path / "e.db"
    importar(_ofx(_trn("20260824", "10.00", "A1", "TED"),
                  ledgerbal=_ledger("1500.00", "20260824")), "itau.ofx", path=db)
    # Bradesco: tem movimento, mas o LEDGERBAL vem com a data zerada
    importar(_ofx(_trn("20260824", "70.00", "B1", "TED"),
                  ledgerbal=_ledger("619059.53", "00000000"),
                  banco="237", conta="123906"), "bradesco.ofx", path=db)

    p = posicao(path=db)
    assert p["total"] == pytest.approx(1500.00)
    assert p["contas_no_total"] == 1
    assert p["contas_sem_saldo"] == 1
    sem = [x for x in p["linhas"] if x["saldo"] is None][0]
    assert "saldo" in (sem["sem_saldo_por"] or ""), "a conta sem saldo tem de dizer por quê"
    assert sem["ultimo_extrato"] == "2026-08-24", "o movimento dela entrou normalmente"


def test_posicao_avisa_quando_as_datas_sao_diferentes(tmp_path):
    """Somar posições de dias diferentes é o número certo — é o dinheiro que se
    sabe ter — mas não pode ser dito calado."""
    db = tmp_path / "e.db"
    importar(_ofx(_trn("20260824", "10.00", "A1", "TED"),
                  ledgerbal=_ledger("1500.00", "20260824")), "itau.ofx", path=db)
    importar(_ofx(_trn("20260820", "70.00", "B1", "TED"),
                  ledgerbal=_ledger("300.00", "20260820"),
                  banco="748", conta="7300000000075455"), "sicredi.ofx", path=db)
    p = posicao(path=db)
    assert p["total"] == pytest.approx(1800.00)
    assert p["datas_diferentes"] is True
    assert p["dt_mais_antiga"] == "2026-08-20"
    assert p["dt_mais_nova"] == "2026-08-24"


def test_posicao_nao_cai_com_o_erp_fora(tmp_path, monkeypatch):
    """A posição do extrato é local; com o AVA fora, mostrar o saldo do banco
    mesmo assim é melhor que esconder a tela."""
    from api.extrato import servico

    db = tmp_path / "e.db"
    importar(_ofx(_trn("20260824", "10.00", "A1", "TED"),
                  ledgerbal=_ledger("1500.00", "20260824")), "itau.ofx", path=db)

    def explode(*_a, **_k):
        raise RuntimeError("connection timeout expired")

    monkeypatch.setattr(servico.db, "query", explode)
    p = posicao(path=db)
    assert p["erp_disponivel"] is False
    assert p["total"] == pytest.approx(1500.00)
    assert all(x["erp_saldo"] is None for x in p["linhas"])


def test_posicao_marca_a_conta_atrasada(tmp_path):
    db = tmp_path / "e.db"
    importar(_ofx(_trn(_ymd(20), "10.00", "A1", "TED"),
                  ledgerbal=_ledger("1500.00", _ymd(20))), "itau.ofx", path=db)
    p = posicao(path=db)
    assert p["atrasadas"] == 1
    assert p["linhas"][0]["atraso_uteis"] >= 10
