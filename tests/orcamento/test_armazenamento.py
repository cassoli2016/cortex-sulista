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


# ------------------------------------------- aprovar / reabrir / arquivar

def _versao(db):
    vid = arm.criar_versao(db, 2027, "v1", 0.0, "cristian")
    arm.gravar_baseline(db, vid, _linhas())
    return vid


def test_aprovar_grava_status_quem_e_quando(db):
    import datetime as dt

    vid = _versao(db)
    agora = dt.datetime(2026, 7, 27, 14, 30)
    arm.aprovar(db, vid, "ana", agora=agora)
    v = arm.listar_versoes(db, 2027)[0]
    assert v["status"] == "aprovado"
    assert v["aprovado_por"] == "ana"
    assert v["aprovado_em"] == "2026-07-27 14:30"


def test_reabrir_volta_a_rascunho_e_limpa_aprovacao(db):
    vid = _versao(db)
    arm.aprovar(db, vid, "ana")
    arm.reabrir(db, vid)
    v = arm.listar_versoes(db, 2027)[0]
    assert v["status"] == "rascunho"
    assert v["aprovado_em"] is None
    assert v["aprovado_por"] is None


def test_reaprovar_versao_ja_aprovada_regrava_quem_e_quando(db):
    import datetime as dt

    vid = _versao(db)
    arm.aprovar(db, vid, "ana", agora=dt.datetime(2026, 7, 20, 10, 0))
    arm.aprovar(db, vid, "cristian", agora=dt.datetime(2026, 7, 27, 9, 0))
    v = arm.listar_versoes(db, 2027)[0]
    assert v["status"] == "aprovado"
    assert v["aprovado_por"] == "cristian"
    assert v["aprovado_em"] == "2026-07-27 09:00"


def test_aprovar_versao_arquivada_da_value_error(db):
    vid = _versao(db)
    novo_id = arm.arquivar_copia(db, vid, "v1 (histórico)")
    with pytest.raises(ValueError):
        arm.aprovar(db, novo_id, "ana")


def test_reabrir_versao_arquivada_da_value_error(db):
    vid = _versao(db)
    novo_id = arm.arquivar_copia(db, vid, "v1 (histórico)")
    with pytest.raises(ValueError):
        arm.reabrir(db, novo_id)


def test_aprovar_versao_inexistente_da_key_error(db):
    with pytest.raises(KeyError):
        arm.aprovar(db, 999, "ana")


def test_reabrir_versao_inexistente_da_key_error(db):
    with pytest.raises(KeyError):
        arm.reabrir(db, 999)


def test_arquivar_copia_versao_inexistente_da_key_error(db):
    with pytest.raises(KeyError):
        arm.arquivar_copia(db, 999, "cópia")


def test_ajustar_em_versao_aprovada_e_imutavel(db):
    vid = _versao(db)
    arm.aprovar(db, vid, "ana")
    with pytest.raises(ValueError, match="imutável"):
        arm.ajustar(db, vid, "1|100", 3, 7777.0, "cristian")


def test_ajustar_apos_reabrir_volta_a_funcionar(db):
    vid = _versao(db)
    arm.aprovar(db, vid, "ana")
    arm.reabrir(db, vid)
    arm.ajustar(db, vid, "1|100", 3, 7777.0, "cristian")
    m3 = next(l for l in arm.ler_linhas(db, vid) if l["mes"] == 3)
    assert m3["valor_ajustado"] == 7777.0


def test_arquivar_copia_cria_versao_nova_arquivada_com_mesmo_metodo_e_base(db):
    vid = arm.criar_versao(db, 2027, "v1", -0.05, "cristian",
                            meses_base=["2026-01", "2026-02"], metodo="semestre")
    arm.gravar_baseline(db, vid, _linhas())

    novo_id = arm.arquivar_copia(db, vid, "v1 (histórico)")

    assert novo_id != vid
    nova = next(v for v in arm.listar_versoes(db, 2027) if v["id"] == novo_id)
    assert nova["status"] == "arquivada"
    assert nova["rotulo"] == "v1 (histórico)"
    assert nova["metodo"] == "semestre"
    assert nova["meses_base"] == '["2026-01", "2026-02"]'
    assert nova["fator_tendencia"] == -0.05
    assert nova["criado_por"] == "cristian"

    original = next(v for v in arm.listar_versoes(db, 2027) if v["id"] == vid)
    assert original["status"] == "rascunho"    # original intocada


def test_arquivar_copia_preserva_baseline_e_ajuste_de_todas_as_linhas(db):
    vid = _versao(db)
    arm.ajustar(db, vid, "1|100", 3, 7777.0, "cristian")

    novo_id = arm.arquivar_copia(db, vid, "v1 (histórico)")

    originais = {l["mes"]: l for l in arm.ler_linhas(db, vid)}
    copiadas = {l["mes"]: l for l in arm.ler_linhas(db, novo_id)}
    assert len(copiadas) == len(originais) == 12
    for mes, linha in copiadas.items():
        antiga = originais[mes]
        assert linha["valor_baseline"] == antiga["valor_baseline"]
        assert linha["valor_ajustado"] == antiga["valor_ajustado"]
        assert linha["origem"] == antiga["origem"]
        assert linha["meses_com_dado"] == antiga["meses_com_dado"]
        assert linha["ajustado_em"] == antiga["ajustado_em"]
        assert linha["ajustado_por"] == antiga["ajustado_por"]
    assert copiadas[3]["valor_ajustado"] == 7777.0   # o ajuste específico, conferido


def test_migracao_adiciona_colunas_aprovado_a_banco_velho(tmp_path):
    """Mesma mecânica do teste de migração de `metodo`: banco criado sem as
    colunas de aprovação, `init_db` acrescenta ambas."""
    import sqlite3

    p = tmp_path / "velho_aprovado.db"
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
        assert "aprovado_em" in cols
        assert "aprovado_por" in cols
        row = c2.execute(
            "SELECT aprovado_em, aprovado_por FROM orc_versao WHERE ano=2025").fetchone()
        assert row == (None, None)
