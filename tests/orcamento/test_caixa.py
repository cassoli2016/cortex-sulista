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


def test_provisao_do_ano_le_sqlite_e_fallback(esquema_pg):
    from api.orcamento import armazenamento as arm
    arm.init_db(esquema_pg)
    vid = arm.criar_versao(esquema_pg, 2026, "teste", 0.0, "t")
    arm.gravar_baseline(esquema_pg, vid, [
        {"conta": "1|1", "mes": 8, "valor_baseline": 1000.0, "origem": "semestre", "meses_com_dado": 6},
        {"conta": "1|2", "mes": 8, "valor_baseline": -400.0, "origem": "semestre", "meses_com_dado": 6},
    ])
    r = provisao_do_ano(2026, None, None, hoje=date(2026, 7, 27), esquema=esquema_pg)
    assert r["dso"] == 49.0 and r["dso_fonte"] == "padrao"
    assert r["versao"]["id"] == vid
    assert all(m["mes"] >= 7 for m in r["meses"])                 # só meses >= corrente
    assert provisao_do_ano(2027, 49, 79, hoje=date(2026, 7, 27),
                           esquema=esquema_pg) is None     # sem versão do ano


def test_valor_efetivo_ajuste_manual(esquema_pg):
    """Teste extra: valor_efetivo (ajuste manual) é o que entra na provisão, não o baseline."""
    from api.orcamento import armazenamento as arm
    arm.init_db(esquema_pg)
    vid = arm.criar_versao(esquema_pg, 2026, "teste", 0.0, "t")
    # Gravar baseline com uma entrada em agosto
    arm.gravar_baseline(esquema_pg, vid, [
        {"conta": "1|1", "mes": 8, "valor_baseline": 1000.0, "origem": "semestre", "meses_com_dado": 6},
    ])
    # Ajustar para 1500.0 (valor_efetivo será 1500.0, não 1000.0)
    arm.ajustar(esquema_pg, vid, "1|1", 8, 1500.0, "teste")

    # Buscar provisão — deve usar valor_efetivo (1500.0)
    r = provisao_do_ano(2026, 49.0, 79.0, hoje=date(2026, 7, 27), esquema=esquema_pg)
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


def test_provisao_do_ano_dso_negativo_usa_padrao_e_marca_fonte(esquema_pg):
    """Mesma invalidação na camada de leitura: dso/dpo negativo vindo do
    chamador (ex.: kpis.dso_3m calculado sobre dado real ruim) não pode se
    disfarçar de 'medido'."""
    from api.orcamento import armazenamento as arm

    p = esquema_pg
    arm.init_db(p)
    vid = arm.criar_versao(p, 2026, "teste", 0.0, "t")
    arm.gravar_baseline(p, vid, [
        {"conta": "1|1", "mes": 3, "valor_baseline": 1000.0, "origem": "espelho", "meses_com_dado": 12},
    ])
    r = provisao_do_ano(2026, -40.0, 79.0, hoje=date(2026, 1, 1), esquema=p)
    assert r["dso"] == DSO_PADRAO
    assert r["dpo"] == 79.0
    assert r["dso_fonte"] == "padrao"


# ---------------------------------------------------------- M1: banco pré-migração


def test_provisao_do_ano_se_cura_em_schema_vazio(pg_disponivel):
    """M1 da revisão final, reescrito para o PostgreSQL: `provisao_do_ano` tem
    de chamar `arm.init_db` ANTES de ler a versão. Sem isso, um schema que
    ainda não tem as tabelas levanta erro engolido pelo `except Exception` de
    `get_overview` — que nem loga — e a série tracejada do Fluxo some para
    sempre, em silêncio.

    Antes o cenário era um `orcamento.db` sem a coluna `metodo`; agora é o
    caso equivalente e mais forte: schema sem tabela nenhuma.
    """
    import pytest

    from api import pglocal
    from api.orcamento import armazenamento as arm

    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    vazio = "teste_orc_schema_vazio"
    pglocal.criar_esquema(vazio)          # DE PROPÓSITO sem migrations
    try:
        r = provisao_do_ano(2026, None, None, hoje=date(2026, 7, 27), esquema=vazio)
        assert r is None, "schema sem versão nenhuma devolve None, não explode"

        # e depois do init_db a leitura normal volta a funcionar
        arm.init_db(vazio)
        vid = arm.criar_versao(vazio, 2026, "novo", 0.0, "teste")
        arm.gravar_baseline(vazio, vid, [
            {"conta": "1|100", "mes": 8, "valor_baseline": 1000.0,
             "origem": "espelho", "meses_com_dado": 12}])
        r = provisao_do_ano(2026, None, None, hoje=date(2026, 7, 27), esquema=vazio)
        assert r is not None
    finally:
        pglocal.apagar_esquema(vazio)


def test_provisao_do_ano_prefere_aprovada_sobre_rascunho_mais_novo(esquema_pg):
    """Uma versão aprovada (número travado) tem prioridade mesmo quando existe
    uma rascunho com id maior — regerar não pode fazer a provisão de caixa
    saltar silenciosamente para um número ainda em edição."""
    from api.orcamento import armazenamento as arm

    p = esquema_pg
    arm.init_db(p)
    aprovada_id = arm.criar_versao(p, 2026, "aprovada", 0.0, "t")
    arm.gravar_baseline(p, aprovada_id, [
        {"conta": "1|1", "mes": 8, "valor_baseline": 1000.0, "origem": "espelho", "meses_com_dado": 12}])
    arm.aprovar(p, aprovada_id, "ana")

    rascunho_id = arm.criar_versao(p, 2026, "rascunho mais novo", 0.0, "t")
    arm.gravar_baseline(p, rascunho_id, [
        {"conta": "1|1", "mes": 8, "valor_baseline": 9999.0, "origem": "espelho", "meses_com_dado": 12}])
    assert rascunho_id > aprovada_id   # id maior = mais recente

    r = provisao_do_ano(2026, 49.0, 79.0, hoje=date(2026, 7, 27), esquema=p)
    assert r["versao"]["id"] == aprovada_id
    assert r["versao"]["status"] == "aprovado"


def test_provisao_do_ano_ignora_arquivada(esquema_pg):
    """Arquivada é registro histórico — nunca entra na provisão de caixa,
    mesmo sendo a versão de id mais alto do ano."""
    from api.orcamento import armazenamento as arm

    p = esquema_pg
    arm.init_db(p)
    rascunho_id = arm.criar_versao(p, 2026, "rascunho", 0.0, "t")
    arm.gravar_baseline(p, rascunho_id, [
        {"conta": "1|1", "mes": 8, "valor_baseline": 500.0, "origem": "espelho", "meses_com_dado": 12}])
    arquivada_id = arm.arquivar_copia(p, rascunho_id, "rascunho (antes de regerar)")
    assert arquivada_id > rascunho_id

    r = provisao_do_ano(2026, 49.0, 79.0, hoje=date(2026, 7, 27), esquema=p)
    assert r["versao"]["id"] == rascunho_id
    assert r["versao"]["status"] == "rascunho"


def test_provisao_do_ano_com_status_vazio_trata_como_rascunho(esquema_pg):
    """Compat com versão gravada antes da coluna `status`: `.get("status")`
    caía em None e a versão tinha de entrar no grupo tratado como rascunho, e
    não ser descartada. No Postgres a coluna é NOT NULL, então o caso que ainda
    chega é a string vazia — a regra é a mesma e é ela que se protege aqui."""
    from api import pglocal
    from api.orcamento import armazenamento as arm

    p = esquema_pg
    arm.init_db(p)
    vid = arm.criar_versao(p, 2026, "sem status", 0.0, "teste")
    arm.gravar_baseline(p, vid, [
        {"conta": "1|100", "mes": 8, "valor_baseline": 1000.0,
         "origem": "espelho", "meses_com_dado": 12}])
    pglocal.executar("UPDATE orc_versao SET status='' WHERE id=%s", (vid,),
                     esquema=p)

    r = provisao_do_ano(2026, None, None, hoje=date(2026, 7, 27), esquema=p)
    assert r is not None


