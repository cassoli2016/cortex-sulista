import sqlite3
from datetime import date

from api.orcamento.caixa import DIAS_MES, DPO_PADRAO, DSO_PADRAO, provisao_caixa, provisao_do_ano


def test_split_fracionario_dso_49():
    """49d -> x=1,6097: 39,03% em M+1 e 60,97% em M+2 (recomputável à mão)."""
    r = provisao_caixa({8: 1000.0}, {}, dso=49.0, dpo=79.0)
    por_mes = {m["mes"]: m for m in r["meses"]}
    x = 49.0 / DIAS_MES
    f = x - int(x)
    assert abs(por_mes[9]["entradas"] - round(1000 * (1 - f), 2)) < 0.01
    assert abs(por_mes[10]["entradas"] - round(1000 * f, 2)) < 0.01
    assert por_mes[8]["entradas"] == 0.0


def test_dpo_79_cai_entre_m2_e_m3():
    r = provisao_caixa({}, {8: -1000.0}, dso=49.0, dpo=79.0)
    por_mes = {m["mes"]: m for m in r["meses"]}
    x = 79.0 / DIAS_MES
    f = x - int(x)
    assert abs(por_mes[10]["saidas"] - round(-1000 * (1 - f), 2)) < 0.01
    assert abs(por_mes[11]["saidas"] - round(-1000 * f, 2)) < 0.01


def test_transbordo_alem_de_dezembro():
    r = provisao_caixa({12: 1000.0}, {12: -500.0}, dso=49.0, dpo=79.0)
    assert all(m["entradas"] == 0.0 for m in r["meses"])          # tudo cai em jan+/fev+
    assert abs(r["transbordo"]["entradas"] - 1000.0) < 0.01
    assert abs(r["transbordo"]["saidas"] + 500.0) < 0.01


def test_dso_zero_paga_no_proprio_mes():
    r = provisao_caixa({5: 100.0}, {5: -40.0}, dso=0.0, dpo=0.0)
    m5 = next(m for m in r["meses"] if m["mes"] == 5)
    assert m5["entradas"] == 100.0 and m5["saidas"] == -40.0 and m5["geracao"] == 60.0


def test_provisao_do_ano_le_sqlite_e_fallback(tmp_path):
    from api.orcamento import armazenamento as arm
    arm.init_db(tmp_path / "o.db")
    vid = arm.criar_versao(tmp_path / "o.db", 2026, "teste", 0.0, "t")
    arm.gravar_baseline(tmp_path / "o.db", vid, [
        {"conta": "1|1", "mes": 8, "valor_baseline": 1000.0, "origem": "semestre", "meses_com_dado": 6},
        {"conta": "1|2", "mes": 8, "valor_baseline": -400.0, "origem": "semestre", "meses_com_dado": 6},
    ])
    r = provisao_do_ano(2026, None, None, hoje=date(2026, 7, 27), db_path=tmp_path / "o.db")
    assert r["dso"] == 49.0 and r["dso_fonte"] == "padrao"
    assert r["versao"]["id"] == vid
    assert all(m["mes"] >= 7 for m in r["meses"])                 # só meses >= corrente
    assert provisao_do_ano(2027, 49, 79, hoje=date(2026, 7, 27),
                           db_path=tmp_path / "o.db") is None     # sem versão do ano


def test_valor_efetivo_ajuste_manual(tmp_path):
    """Teste extra: valor_efetivo (ajuste manual) é o que entra na provisão, não o baseline."""
    from api.orcamento import armazenamento as arm
    arm.init_db(tmp_path / "o.db")
    vid = arm.criar_versao(tmp_path / "o.db", 2026, "teste", 0.0, "t")
    # Gravar baseline com uma entrada em agosto
    arm.gravar_baseline(tmp_path / "o.db", vid, [
        {"conta": "1|1", "mes": 8, "valor_baseline": 1000.0, "origem": "semestre", "meses_com_dado": 6},
    ])
    # Ajustar para 1500.0 (valor_efetivo será 1500.0, não 1000.0)
    arm.ajustar(tmp_path / "o.db", vid, "1|1", 8, 1500.0, "teste")

    # Buscar provisão — deve usar valor_efetivo (1500.0)
    r = provisao_do_ano(2026, 49.0, 79.0, hoje=date(2026, 7, 27), db_path=tmp_path / "o.db")
    # A entrada de 1500.0 em agosto deve se deslocar para setembro/outubro com DSO=49
    por_mes = {m["mes"]: m for m in r["meses"]}
    x = 49.0 / DIAS_MES
    f = x - int(x)
    assert abs(por_mes[9]["entradas"] - round(1500 * (1 - f), 2)) < 0.01
    assert abs(por_mes[10]["entradas"] - round(1500 * f, 2)) < 0.01


def test_conservacao_massa_dso_49_mes_11():
    """Conservação: competência nov (11) com DSO=49 desembarca em dez/jan+.

    DSO=49 → 1.609 meses → 1ª parcela em dez (39.03%), 2ª em jan+ (60.97%).
    Problema original: 1ª parcela entrava em dez, mas 2ª somava o VALOR INTEIRO ao transbordo
    (duplicação: 390 + 1000 = 1390).
    Correção: 2ª parcela (60.97%) vai ao transbordo, não o valor inteiro.
    Total série + transbordo = 1000 (conservado).
    """
    r = provisao_caixa({11: 1000.0}, {}, dso=49.0, dpo=79.0)
    por_mes = {m["mes"]: m for m in r["meses"]}
    x = 49.0 / DIAS_MES
    f = x - int(x)
    parcela1_esperada = 1000 * (1 - f)  # ~390.28
    parcela2_esperada = 1000 * f        # ~609.72

    # Verificar série
    assert abs(por_mes[12]["entradas"] - round(parcela1_esperada, 2)) < 0.01
    # Verificar transbordo
    assert abs(r["transbordo"]["entradas"] - round(parcela2_esperada, 2)) < 0.01
    # Verificar conservação total
    total_serie = sum(m["entradas"] for m in r["meses"])
    total = total_serie + r["transbordo"]["entradas"]
    assert abs(total - 1000.0) < 0.02


def test_conservacao_massa_dso_60_88_mes_11():
    """Conservação: competência nov (11) com DSO=60.88 (2 meses exatos).

    DSO=60.88 → 2.0 meses → desembarca em jan+ (13º mês), sem fração.
    Problema original: mes_caixa=13 (>12) e f=0 → nem série nem transbordo → SÓ SOME.
    Correção: 1ª parcela (100%) vai ao transbordo porque mes_caixa > 12.
    Total série + transbordo = 1000 (conservado).
    """
    r = provisao_caixa({11: 1000.0}, {}, dso=60.88, dpo=79.0)
    por_mes = {m["mes"]: m for m in r["meses"]}

    # Nada deve entrar na série (todo valor vai para jan+)
    assert all(m["entradas"] == 0.0 for m in r["meses"])
    # Transbordo deve ter o valor inteiro
    assert abs(r["transbordo"]["entradas"] - 1000.0) < 0.01


def test_conservacao_massa_dso_49_todas_competencias():
    """Conservação para competências 9..12 com DSO=49.

    Verifica que soma(série) + transbordo = valor original para cada competência.
    Garante que nenhum valor duplica nem some em nenhum recorte do ano.
    """
    for mes_comp in [9, 10, 11, 12]:
        r = provisao_caixa({mes_comp: 1000.0}, {}, dso=49.0, dpo=79.0)
        total_serie = sum(m["entradas"] for m in r["meses"])
        total = total_serie + r["transbordo"]["entradas"]
        assert abs(total - 1000.0) < 0.02, f"Falha em mes_comp={mes_comp}: total={total}"


def test_conservacao_massa_dso_60_88_todas_competencias():
    """Conservação para competências 9..12 com DSO=60.88 (2 meses exatos).

    Verifica que soma(série) + transbordo = valor original para cada competência.
    """
    for mes_comp in [9, 10, 11, 12]:
        r = provisao_caixa({mes_comp: 1000.0}, {}, dso=60.88, dpo=79.0)
        total_serie = sum(m["entradas"] for m in r["meses"])
        total = total_serie + r["transbordo"]["entradas"]
        assert abs(total - 1000.0) < 0.02, f"Falha em mes_comp={mes_comp}: total={total}"


# ---------------------------------------------------------- I1: prazo negativo


def test_dso_negativo_cai_no_padrao_e_conserva_massa():
    """dso=-40 é inválido (não existe venda recebida antes de ser emitida): cai
    no fallback DSO_PADRAO (49) em vez de truncar em direção a zero.

    Antes da correção, int(-40/30.44) = int(-1.31) = -1 (trunca para ZERO, não
    para -2 como floor faria) e o mês de caixa saía adiantado, criando massa
    do nada; e uma competência baixa o suficiente batia em mes_caixa<=0 e
    lançava KeyError na tabela de meses (1..12).
    """
    r_neg = provisao_caixa({3: 1000.0}, {}, dso=-40.0, dpo=79.0)
    r_padrao = provisao_caixa({3: 1000.0}, {}, dso=DSO_PADRAO, dpo=79.0)
    assert r_neg["meses"] == r_padrao["meses"]
    assert r_neg["transbordo"] == r_padrao["transbordo"]
    total_serie = sum(m["entradas"] for m in r_neg["meses"])
    total = total_serie + r_neg["transbordo"]["entradas"]
    assert abs(total - 1000.0) < 0.02


def test_dpo_negativo_cai_no_padrao():
    r_neg = provisao_caixa({}, {6: -1000.0}, dso=49.0, dpo=-79.0)
    r_padrao = provisao_caixa({}, {6: -1000.0}, dso=49.0, dpo=DPO_PADRAO)
    assert r_neg["meses"] == r_padrao["meses"]
    assert r_neg["transbordo"] == r_padrao["transbordo"]


def test_provisao_do_ano_dso_negativo_usa_padrao_e_marca_fonte(tmp_path):
    """Mesma invalidação na camada de leitura: dso/dpo negativo vindo do
    chamador (ex.: kpis.dso_3m calculado sobre dado real ruim) não pode se
    disfarçar de 'medido'."""
    from api.orcamento import armazenamento as arm

    p = tmp_path / "o.db"
    arm.init_db(p)
    vid = arm.criar_versao(p, 2026, "teste", 0.0, "t")
    arm.gravar_baseline(p, vid, [
        {"conta": "1|1", "mes": 3, "valor_baseline": 1000.0, "origem": "espelho", "meses_com_dado": 12},
    ])
    r = provisao_do_ano(2026, -40.0, 79.0, hoje=date(2026, 1, 1), db_path=p)
    assert r["dso"] == DSO_PADRAO
    assert r["dpo"] == 79.0
    assert r["dso_fonte"] == "padrao"


# ---------------------------------------------------------- M1: banco pré-migração


def test_provisao_do_ano_migra_banco_pre_metodo(tmp_path):
    """M1 da revisão final: um orcamento.db criado ANTES desta branch não tem
    a coluna `metodo` em orc_versao. Sem `init_db` no início de
    `provisao_do_ano`, `versao["metodo"]` levanta KeyError — engolido pelo
    `except Exception` de `get_overview`, que nem loga — e a série tracejada
    do Fluxo some para sempre em silêncio. `provisao_do_ano` tem que se
    auto-curar chamando `arm.init_db` antes de ler a versão.
    """
    p = tmp_path / "velho.db"
    c = sqlite3.connect(p)
    c.executescript("""
        CREATE TABLE orc_versao(
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ano             INTEGER NOT NULL,
            rotulo          TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'rascunho',
            fator_tendencia REAL    NOT NULL DEFAULT 0,
            criado_em       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            criado_por      TEXT
        );
        CREATE TABLE orc_linha(
            versao_id      INTEGER NOT NULL,
            conta          TEXT    NOT NULL,
            mes            INTEGER NOT NULL,
            valor_baseline REAL    NOT NULL DEFAULT 0,
            valor_ajustado REAL,
            origem         TEXT    NOT NULL DEFAULT 'sem_base',
            meses_com_dado INTEGER NOT NULL DEFAULT 0,
            ajustado_em    TEXT,
            ajustado_por   TEXT,
            PRIMARY KEY (versao_id, conta, mes)
        );
    """)
    c.execute("INSERT INTO orc_versao(id, ano, rotulo) VALUES (1, 2026, 'Orçamento 2026 antigo')")
    c.execute("""INSERT INTO orc_linha(versao_id, conta, mes, valor_baseline, origem, meses_com_dado)
                 VALUES (1, '1|100', 8, 1000.0, 'espelho', 12)""")
    c.commit()
    c.close()

    cols_antes = {r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(orc_versao)")}
    assert "metodo" not in cols_antes   # confirma que o cenário reproduz o schema velho

    r = provisao_do_ano(2026, None, None, hoje=date(2026, 7, 27), db_path=p)

    assert r is not None
    assert r["versao"]["id"] == 1
    assert r["versao"]["metodo"] == "espelho"   # default do ALTER TABLE
    assert any(m["mes"] == 9 for m in r["meses"])   # entrada de ago (8) deslocada por DSO

    cols_depois = {r2[1] for r2 in sqlite3.connect(p).execute("PRAGMA table_info(orc_versao)")}
    assert "metodo" in cols_depois
