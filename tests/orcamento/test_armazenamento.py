"""Testes do armazenamento local do orçamento (SQLite)."""
from __future__ import annotations

import pytest

from api.orcamento import armazenamento as arm


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "orcamento.db"
    arm.init_db(p)
    return p


def _linhas(conta="1|100", valor=1000.0, origem="espelho"):
    return [{"conta": conta, "mes": m, "valor_baseline": valor,
             "origem": origem, "meses_com_dado": 12} for m in range(1, 13)]


def test_cria_versao_e_le_de_volta(db):
    vid = arm.criar_versao(db, 2027, "Orçamento 2027", -0.05, "cristian")
    vs = arm.listar_versoes(db, 2027)
    assert len(vs) == 1
    assert vs[0]["id"] == vid
    assert vs[0]["ano"] == 2027
    assert vs[0]["fator_tendencia"] == -0.05
    assert vs[0]["status"] == "rascunho"


def test_grava_baseline_e_valor_efetivo_cai_no_baseline(db):
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian")
    n = arm.gravar_baseline(db, vid, _linhas())
    assert n == 12
    linhas = arm.ler_linhas(db, vid)
    assert len(linhas) == 12
    assert all(l["valor_efetivo"] == 1000.0 for l in linhas)
    assert all(l["valor_ajustado"] is None for l in linhas)


def test_ajuste_sobrepoe_o_baseline(db):
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian")
    arm.gravar_baseline(db, vid, _linhas())
    arm.ajustar(db, vid, "1|100", 3, 7777.0, "cristian")
    m3 = next(l for l in arm.ler_linhas(db, vid) if l["mes"] == 3)
    assert m3["valor_ajustado"] == 7777.0
    assert m3["valor_baseline"] == 1000.0
    assert m3["valor_efetivo"] == 7777.0


def test_regerar_baseline_preserva_o_ajuste_manual(db):
    """O requisito central: recalcular não pode jogar fora o trabalho da controladoria."""
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian")
    arm.gravar_baseline(db, vid, _linhas(valor=1000.0))
    arm.ajustar(db, vid, "1|100", 3, 7777.0, "cristian")

    arm.gravar_baseline(db, vid, _linhas(valor=2000.0))   # regera com outro fator

    m3 = next(l for l in arm.ler_linhas(db, vid) if l["mes"] == 3)
    assert m3["valor_baseline"] == 2000.0    # baseline atualizou
    assert m3["valor_ajustado"] == 7777.0    # ajuste sobreviveu
    assert m3["valor_efetivo"] == 7777.0
    m4 = next(l for l in arm.ler_linhas(db, vid) if l["mes"] == 4)
    assert m4["valor_efetivo"] == 2000.0     # sem ajuste, segue o baseline novo


def test_limpar_ajuste_volta_para_o_baseline(db):
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian")
    arm.gravar_baseline(db, vid, _linhas())
    arm.ajustar(db, vid, "1|100", 3, 7777.0, "cristian")
    arm.ajustar(db, vid, "1|100", 3, None, "cristian")
    m3 = next(l for l in arm.ler_linhas(db, vid) if l["mes"] == 3)
    assert m3["valor_ajustado"] is None
    assert m3["valor_efetivo"] == 1000.0


def test_cada_ajuste_vira_linha_de_auditoria(db):
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian")
    arm.gravar_baseline(db, vid, _linhas())
    arm.ajustar(db, vid, "1|100", 3, 7777.0, "cristian")
    arm.ajustar(db, vid, "1|100", 3, 8888.0, "ana")
    log = arm.ler_log(db, vid)
    assert len(log) == 2
    assert log[0]["quem"] == "ana"            # mais recente primeiro
    assert log[0]["valor_de"] == 7777.0
    assert log[0]["valor_para"] == 8888.0
    assert log[1]["valor_de"] == 1000.0       # primeiro ajuste partiu do baseline


# ---------------------------------------------------------- coluna `metodo`

def test_migracao_adiciona_coluna_metodo_a_banco_velho(tmp_path):
    """Banco criado antes da coluna existir (mesmo padrão de `meses_base`):
    PRAGMA confirma que o `init_db` acrescenta `metodo` com o padrão 'espelho',
    inclusive retroativo nas linhas já existentes."""
    import sqlite3

    p = tmp_path / "velho.db"
    c = sqlite3.connect(p)
    c.execute("""
        CREATE TABLE orc_versao(
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ano             INTEGER NOT NULL,
            rotulo          TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'rascunho',
            fator_tendencia REAL    NOT NULL DEFAULT 0,
            criado_em       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            criado_por      TEXT
        )
    """)
    c.execute("INSERT INTO orc_versao(ano, rotulo) VALUES (2025, 'antigo')")
    c.commit()
    c.close()

    arm.init_db(p)

    with sqlite3.connect(p) as c2:
        cols = {r[1] for r in c2.execute("PRAGMA table_info(orc_versao)")}
        assert "metodo" in cols
        row = c2.execute("SELECT metodo FROM orc_versao WHERE ano=2025").fetchone()
        assert row[0] == "espelho"


def test_criar_versao_grava_metodo_e_listar_versoes_devolve(db):
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian", metodo="semestre")
    vs = arm.listar_versoes(db, 2027)
    assert vs[0]["id"] == vid
    assert vs[0]["metodo"] == "semestre"


def test_criar_versao_sem_metodo_usa_espelho_por_padrao(db):
    vid = arm.criar_versao(db, 2027, "v2", 0.0, "cristian")
    v = next(v for v in arm.listar_versoes(db, 2027) if v["id"] == vid)
    assert v["metodo"] == "espelho"


def test_atualizar_versao_sem_metodo_nao_altera_o_gravado(db):
    vid = arm.criar_versao(db, 2027, "v3", 0.0, "cristian", metodo="semestre")
    arm.atualizar_versao(db, vid, -0.05, meses_base=["2026-01"])
    v = arm.listar_versoes(db, 2027)[0]
    assert v["metodo"] == "semestre"
    assert v["fator_tendencia"] == -0.05


def test_atualizar_versao_com_metodo_regrava(db):
    vid = arm.criar_versao(db, 2027, "v4", 0.0, "cristian", metodo="espelho")
    arm.atualizar_versao(db, vid, 0.0, metodo="semestre")
    v = arm.listar_versoes(db, 2027)[0]
    assert v["metodo"] == "semestre"
