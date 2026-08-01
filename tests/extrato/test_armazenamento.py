"""Persistência local do extrato (SQLite) — sem AVA, sem rede."""
from __future__ import annotations

import pytest

from api.extrato import armazenamento as arm
from api.extrato import comparacao as cmp


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "extrato.db"
    arm.init_db(p)
    return p


def _item(dt="2026-07-01", valor=100.0, tipo="C", hist="TED RECEBIDA",
          doc="123", fitid="F1"):
    return {"dt": dt, "valor": valor, "tipo": tipo, "historico": hist,
            "numerodoc": doc, "fitid": fitid}


def test_conta_criada_uma_vez(db):
    a = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau 539349")
    b = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau 539349")
    assert a == b
    assert len(arm.listar_contas(db)) == 1


def test_grava_lancamentos_e_dedup_por_fitid(db):
    cid = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau")
    r1 = arm.gravar_lancamentos(db, cid, [_item(), _item(fitid="F2", valor=-50.0, tipo="D")],
                                "ext.ofx", "ofx")
    assert (r1["novas"], r1["duplicadas"]) == (2, 0)
    # re-upload do MESMO arquivo: nada entra de novo
    r2 = arm.gravar_lancamentos(db, cid, [_item(), _item(fitid="F2", valor=-50.0, tipo="D")],
                                "ext.ofx", "ofx")
    assert (r2["novas"], r2["duplicadas"]) == (0, 2)
    assert len(arm.lancamentos(db, cid, "2026-07-01", "2026-07-31")) == 2


def test_dedup_sem_fitid_usa_hash_e_preserva_repetidos_do_dia(db):
    cid = arm.obter_ou_criar_conta(db, "csv:itau", "Itau CSV")
    # dois lançamentos IDÊNTICOS no mesmo dia são legítimos (duas tarifas iguais)
    itens = [_item(fitid=None), _item(fitid=None)]
    r1 = arm.gravar_lancamentos(db, cid, itens, "ext.csv", "csv")
    assert (r1["novas"], r1["duplicadas"]) == (2, 0)
    r2 = arm.gravar_lancamentos(db, cid, itens, "ext.csv", "csv")
    assert (r2["novas"], r2["duplicadas"]) == (0, 2)


def test_apagar_importacao_remove_lancamentos(db):
    cid = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau")
    r = arm.gravar_lancamentos(db, cid, [_item()], "ext.ofx", "ofx")
    assert arm.apagar_importacao(db, r["importacao_id"]) == 1
    assert arm.lancamentos(db, cid, "2026-07-01", "2026-07-31") == []
    assert arm.listar_importacoes(db) == []


def test_mapeamento_erp_e_mapa_csv(db):
    cid = arm.obter_ou_criar_conta(db, "csv:itau", "Itau CSV")
    arm.mapear_conta(db, cid, 341, "0098", "539349", rotulo="Itau conta movimento")
    arm.salvar_mapa_csv(db, cid, {"dt": 0, "valor": 3, "historico": 1})
    c = arm.conta_por_ident(db, "csv:itau")
    assert (c["erp_banco"], c["erp_agencia"], c["erp_conta"]) == (341, "0098", "539349")
    assert c["rotulo"] == "Itau conta movimento"
    assert c["mapa_csv"] == {"dt": 0, "valor": 3, "historico": 1}


def test_saldo_extrato_upsert(db):
    cid = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau")
    arm.gravar_saldo_extrato(db, cid, "2026-07-31", 1000.0)
    arm.gravar_saldo_extrato(db, cid, "2026-07-31", 1200.0)   # reimport corrige
    assert arm.saldos_extrato(db, cid) == [{"dt": "2026-07-31", "saldo": 1200.0}]


# --- d1 (Critical na triagem): ext_saldo orfao corrompe saldos derivados ----

def test_apagar_importacao_remove_ancora_de_saldo_daquela_importacao(db):
    """A ancora de saldo gravada JUNTO com uma importacao tem que sumir quando
    a importacao e desfeita - sem isso ela fica orfa e, se for a mais recente,
    `saldo_derivado` (que usa `max(dt)` das ancoras) parte dela e corrompe
    TODOS os saldos derivados a partir dai."""
    cid = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau")
    r = arm.gravar_lancamentos(db, cid, [_item()], "ext.ofx", "ofx")
    arm.gravar_saldo_extrato(db, cid, "2026-07-01", 500.0, importacao_id=r["importacao_id"])
    assert arm.saldos_extrato(db, cid) == [{"dt": "2026-07-01", "saldo": 500.0}]

    arm.apagar_importacao(db, r["importacao_id"])
    assert arm.saldos_extrato(db, cid) == []


def test_desfazer_import_errado_nao_deixa_ancora_orfa_nem_dia_fantasma(db):
    """Cenario provado pela revisao: sobe o arquivo ERRADO (grava lancamento e
    uma ancora de saldo num dia sem lancamento nenhum) -> desfaz -> sobe o
    CERTO. A ancora errada NAO pode sobreviver (nem como "dia fantasma"
    isolado com qtd:0 em `comparar`), e o saldo derivado tem que refletir so
    a importacao boa - nunca ficar refem de qual ancora e "mais recente" entre
    uma valida e uma que devia ter sido apagada."""
    cid = arm.obter_ou_criar_conta(db, "1/2/3", "conta")

    errado = arm.gravar_lancamentos(
        db, cid, [_item(dt="2026-07-01", valor=999.0, fitid="ERR1")], "errado.ofx", "ofx")
    # ancora do arquivo errado cai num dia MAIS recente e SEM lancamento -
    # exatamente o caso que faria saldo_derivado usar a ancora errada como
    # ponto de partida (max(dt) das ancoras) se ela sobrevivesse ao desfazer
    arm.gravar_saldo_extrato(db, cid, "2026-07-05", 99999.0,
                             importacao_id=errado["importacao_id"])
    arm.apagar_importacao(db, errado["importacao_id"])

    certo = arm.gravar_lancamentos(
        db, cid, [_item(dt="2026-07-01", valor=100.0, fitid="OK1")], "certo.ofx", "ofx")
    arm.gravar_saldo_extrato(db, cid, "2026-07-03", 429.36,
                             importacao_id=certo["importacao_id"])

    assert arm.saldos_extrato(db, cid) == [{"dt": "2026-07-03", "saldo": 429.36}]
    dias = cmp.comparar(arm.lancamentos(db, cid, "2026-07-01", "2026-07-31"),
                        arm.saldos_extrato(db, cid), [])
    datas = {d["dt"] for d in dias}
    # so os dias reais aparecem - "2026-07-05" (ancora do arquivo errado, ja
    # apagada) nao pode sobreviver como dia fantasma isolado
    assert datas == {"2026-07-01", "2026-07-03"}
    por_dt = {d["dt"]: d for d in dias}
    # nenhum lancamento entre 01/07 e 03/07 - o saldo deriva constante a
    # partir da unica ancora que sobrou (a boa, 429.36), nunca da errada
    # (99999.0) que foi desfeita
    assert round(por_dt["2026-07-03"]["ext_saldo"], 2) == 429.36
    assert round(por_dt["2026-07-01"]["ext_saldo"], 2) == 429.36


def test_gravar_saldo_extrato_sem_importacao_id_fica_sem_vinculo(db):
    """Ancoras pre-migracao (ou de reimport 100% duplicado, sem importacao
    nova a que amarrar) ficam com `importacao_id` None - `apagar_importacao`
    de QUALQUER importacao nao pode removê-las."""
    cid = arm.obter_ou_criar_conta(db, "1/2/3", "conta")
    r = arm.gravar_lancamentos(db, cid, [_item()], "ext.ofx", "ofx")
    arm.gravar_saldo_extrato(db, cid, "2026-07-15", 777.0)   # sem importacao_id
    arm.apagar_importacao(db, r["importacao_id"])
    assert arm.saldos_extrato(db, cid) == [{"dt": "2026-07-15", "saldo": 777.0}]


def test_dedup_hash_independe_da_ordem_com_numerodoc_diferente(db):
    """Fix round 1 — FINDING 1: dois boletos de mesmo dia/valor/histórico mas
    numerodoc diferente não podem duplicar quando o re-upload chega em ordem
    trocada (o contador de ocorrência tem de usar a MESMA identidade do hash)."""
    cid = arm.obter_ou_criar_conta(db, "csv:itau", "Itau CSV")
    boleto_1001 = _item(fitid=None, doc="1001")
    boleto_2002 = _item(fitid=None, doc="2002")
    r1 = arm.gravar_lancamentos(db, cid, [boleto_1001, boleto_2002], "ext.csv", "csv")
    assert (r1["novas"], r1["duplicadas"]) == (2, 0)
    # re-upload do MESMO arquivo com a ORDEM das linhas trocada
    r2 = arm.gravar_lancamentos(db, cid, [boleto_2002, boleto_1001], "ext.csv", "csv")
    assert (r2["novas"], r2["duplicadas"]) == (0, 2)
    assert len(arm.lancamentos(db, cid, "2026-07-01", "2026-07-31")) == 2


def test_dedup_normaliza_espaco_duplo_no_historico(db):
    """Fix round 1 — FINDING 2: "TARIFA  PACOTE" (espaço duplo) e "TARIFA PACOTE"
    são o MESMO lançamento para efeito de dedup; export de banco costuma variar
    isso entre uploads do mesmo arquivo."""
    cid = arm.obter_ou_criar_conta(db, "csv:itau", "Itau CSV")
    r1 = arm.gravar_lancamentos(
        db, cid, [_item(fitid=None, hist="TARIFA PACOTE")], "ext.csv", "csv")
    assert (r1["novas"], r1["duplicadas"]) == (1, 0)
    r2 = arm.gravar_lancamentos(
        db, cid, [_item(fitid=None, hist="TARIFA  PACOTE")], "ext.csv", "csv")
    assert (r2["novas"], r2["duplicadas"]) == (0, 1)


def test_tipo_deriva_do_sinal_do_valor(db):
    """Fix round 1 — FINDING 3: tipo=C/D é sempre derivado do sinal de valor,
    nunca confiado ao item de entrada — crédito >= 0, débito < 0."""
    cid = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau")
    arm.gravar_lancamentos(db, cid, [_item(valor=-30.0, tipo="C", fitid="F9")],
                           "ext.ofx", "ofx")
    lanc = arm.lancamentos(db, cid, "2026-07-01", "2026-07-31")
    assert len(lanc) == 1
    assert lanc[0]["tipo"] == "D"
