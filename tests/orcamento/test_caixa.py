from datetime import date

from api.orcamento.caixa import DIAS_MES, provisao_caixa, provisao_do_ano


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
