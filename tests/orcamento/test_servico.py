"""Testes da agregação orçado x realizado por linha da DRE."""
from __future__ import annotations

from datetime import date

from api.orcamento import armazenamento as arm
from api.orcamento import servico as svc
from api.orcamento import sql as sql_mod
from api.orcamento.servico import montar_comparativo

MAPA = {"1|100": "CUSTO VARIAVEL", "1|101": "CUSTO VARIAVEL",
        "1|103": "RECEITA BRUTA", "9|999": None}


def _orc(conta, mes, valor):
    return {"conta": conta, "mes": mes, "valor_efetivo": valor,
            "valor_baseline": valor, "valor_ajustado": None,
            "origem": "espelho", "meses_com_dado": 12}


def test_soma_orcado_e_realizado_por_linha_ate_o_mes():
    linhas_orc = [_orc("1|100", m, -1000.0) for m in range(1, 13)]
    linhas_orc += [_orc("1|103", m, 5000.0) for m in range(1, 13)]
    realizado = {("1|100", 1): -900.0, ("1|100", 2): -1200.0,
                 ("1|103", 1): 4000.0, ("1|103", 2): 4000.0}
    r = montar_comparativo(linhas_orc, realizado, MAPA, ate_mes=2)
    por_linha = {l["linha"]: l for l in r["linhas"]}
    assert por_linha["CUSTO VARIAVEL"]["orcado"] == -2000.0
    assert por_linha["CUSTO VARIAVEL"]["realizado"] == -2100.0
    assert por_linha["RECEITA BRUTA"]["orcado"] == 10000.0
    assert por_linha["RECEITA BRUTA"]["realizado"] == 8000.0


def test_desvio_de_custo_acima_do_orcado_e_desfavoravel():
    """Custo realizado maior que o orçado estoura: favoravel=False."""
    linhas_orc = [_orc("1|100", 1, -1000.0)]
    r = montar_comparativo(linhas_orc, {("1|100", 1): -1300.0}, MAPA, ate_mes=1)
    cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert cv["desvio"] == -300.0
    assert cv["favoravel"] is False


def test_custo_abaixo_do_orcado_e_favoravel():
    linhas_orc = [_orc("1|100", 1, -1000.0)]
    r = montar_comparativo(linhas_orc, {("1|100", 1): -700.0}, MAPA, ate_mes=1)
    cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert cv["desvio"] == 300.0
    assert cv["favoravel"] is True


def test_receita_abaixo_do_orcado_e_desfavoravel():
    linhas_orc = [_orc("1|103", 1, 5000.0)]
    r = montar_comparativo(linhas_orc, {("1|103", 1): 4000.0}, MAPA, ate_mes=1)
    rb = next(l for l in r["linhas"] if l["linha"] == "RECEITA BRUTA")
    assert rb["desvio"] == -1000.0
    assert rb["favoravel"] is False


def test_conta_sem_linha_nao_entra_no_total_e_e_reportada():
    linhas_orc = [_orc("1|100", 1, -1000.0), _orc("9|999", 1, -500.0)]
    r = montar_comparativo(linhas_orc, {}, MAPA, ate_mes=1)
    total_cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert total_cv["orcado"] == -1000.0
    assert [x["conta"] for x in r["sem_linha"]] == ["9|999"]


def test_meses_depois_do_corte_ficam_fora_do_acumulado():
    linhas_orc = [_orc("1|100", m, -1000.0) for m in range(1, 13)]
    r = montar_comparativo(linhas_orc, {}, MAPA, ate_mes=3)
    cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert cv["orcado"] == -3000.0


def test_meses_faltando_na_base_sao_reportados():
    """Derivar espelho sobre base furada viraria zero com cara de orçamento."""
    from api.orcamento.servico import meses_faltando

    meses = ["2025-08", "2025-09", "2025-10"]
    hist = {"1|100": {"2025-08": 1.0}, "2|200": {"2025-09": 2.0}}
    assert meses_faltando(hist, meses) == ["2025-10"]


def test_base_completa_nao_reporta_falta():
    from api.orcamento.servico import meses_faltando

    meses = ["2025-08", "2025-09"]
    hist = {"1|100": {"2025-08": 1.0}, "2|200": {"2025-09": 2.0}}
    assert meses_faltando(hist, meses) == []


def test_grade_traz_as_12_celulas_mesmo_com_ano_nao_iniciado():
    """Sem isso a aba Montagem viria vazia num orçamento do ano que vem."""
    linhas_orc = [_orc("1|100", m, -1000.0) for m in range(1, 13)]
    r = montar_comparativo(linhas_orc, {}, MAPA, ate_mes=0)
    assert r["contas"] == []            # nada acumulado ainda
    g = next(x for x in r["grade"] if x["conta"] == "1|100")
    assert len(g["valores"]) == 12
    assert g["valores"][12] == -1000.0
    assert g["linha"] == "CUSTO VARIAVEL"


def test_serie_mensal_marca_o_mes_sem_realizado():
    """Mês sem realizado não pode virar barra zerada no gráfico."""
    linhas_orc = [_orc("1|100", m, -1000.0) for m in range(1, 13)]
    r = montar_comparativo(linhas_orc, {("1|100", 1): -900.0}, MAPA, ate_mes=1)
    serie = {s["mes"]: s for s in r["mensal"]}
    assert serie[1]["realizado"] == -900.0
    assert serie[1]["fechado"] is True
    assert serie[5]["realizado"] is None
    assert serie[5]["fechado"] is False


def test_gerar_e_comparativo_respeitam_db_path_trocado_em_runtime(tmp_path, monkeypatch):
    """Achado 3 da revisão: `path=arm.DB_PATH` como default resolve em tempo de
    IMPORT (uma vez só, quando o módulo carrega). Se `gerar`/`comparativo` forem
    chamados sem `path=` depois de um `monkeypatch.setattr(arm, "DB_PATH", ...)`
    (como este teste faz), eles têm que gravar/ler no destino trocado — não no
    valor congelado na assinatura da função. Isolado do Postgres real: stub em
    `db.query` e em `ler_ajustes` cobre o histórico e o agrupador."""
    destino = tmp_path / "orcamento.db"
    monkeypatch.setattr(arm, "DB_PATH", destino)
    monkeypatch.setattr(svc, "ler_ajustes", lambda: {})

    hoje = date(2026, 7, 1)
    meses_base = sql_mod.meses_fechados(hoje, 12)

    def fake_query(sql, params=None):
        if sql == sql_mod.HIST_CONTA_SQL:
            return [{"conta": "1|100", "mes": m, "valor": -100.0} for m in meses_base]
        if sql == sql_mod.AGRUP_CONTA_SQL:
            return [{"conta": "1|100", "agrupador": "CV - COMBUSTIVEL"}]
        return []

    monkeypatch.setattr(svc.db, "query", fake_query)

    # gerar() sem path=: tem que gravar em `destino`, não no DB_PATH original.
    r = svc.gerar(2026, "teste path default", 0.0, "teste", hoje=hoje)
    assert destino.exists()
    assert r["contas_sem_linha"] == []
    assert arm.listar_versoes(destino)[0]["id"] == r["versao_id"]

    # comparativo() sem path=: tem que ler de `destino` também.
    out = svc.comparativo(r["versao_id"], ate_mes=0)
    assert out["versao"]["id"] == r["versao_id"]
    assert len(out["grade"]) == 1
    assert out["grade"][0]["conta"] == "1|100"
    assert out["grade"][0]["linha"] == "CUSTO VARIAVEL"


def test_regerar_a_versao_preserva_o_ajuste_manual(tmp_path, monkeypatch):
    """Critério de aceite 3, pelo caminho que a aplicação usa de verdade.

    O teste antigo chamava `gravar_baseline` direto e por isso passava mesmo com
    `gerar()` sempre criando versão nova — o `ON CONFLICT` nunca era alcançado em
    produção. Aqui a regeração vai por `gerar(versao_id=...)`, o mesmo que o botão
    "Regerar" da tela dispara."""
    destino = tmp_path / "orcamento.db"
    monkeypatch.setattr(arm, "DB_PATH", destino)
    monkeypatch.setattr(svc, "ler_ajustes", lambda: {})
    hoje = date(2026, 7, 1)
    meses_base = sql_mod.meses_fechados(hoje, 12)
    contas = ["1|100", "1|101"]

    def fake_query(sql, params=None):
        if sql == sql_mod.HIST_CONTA_SQL:
            return [{"conta": c, "mes": m, "valor": -100.0}
                    for c in contas for m in meses_base]
        if sql == sql_mod.AGRUP_CONTA_SQL:
            return [{"conta": c, "agrupador": "CV - COMBUSTIVEL"} for c in contas]
        return []

    monkeypatch.setattr(svc.db, "query", fake_query)

    r1 = svc.gerar(2026, "Orçamento 2026", 0.0, "teste", hoje=hoje)
    arm.ajustar(destino, r1["versao_id"], "1|100", 3, -777.0, "controladoria")

    # a conta 1|101 some do histórico: a regeração não pode deixar o baseline velho
    contas.remove("1|101")
    r2 = svc.gerar(2026, "Orçamento 2026", -0.10, "teste", hoje=hoje,
                   versao_id=r1["versao_id"])

    assert r2["versao_id"] == r1["versao_id"], "regerar não pode criar versão nova"
    assert r2["regerada"] is True
    assert len(arm.listar_versoes(destino)) == 1
    assert r2["celulas_zeradas"] == 12          # os 12 meses de 1|101

    linhas = {(l["conta"], l["mes"]): l for l in arm.ler_linhas(destino, r1["versao_id"])}
    ajustada = linhas[("1|100", 3)]
    assert ajustada["valor_ajustado"] == -777.0, "o ajuste manual tem que sobreviver"
    assert ajustada["valor_efetivo"] == -777.0
    assert ajustada["valor_baseline"] == -90.0, "o baseline recalcula com o novo fator"
    assert linhas[("1|100", 4)]["valor_efetivo"] == -90.0
    assert linhas[("1|101", 4)]["valor_baseline"] == 0.0, "conta que saiu vai a zero"
    assert linhas[("1|101", 4)]["origem"] == "sem_base"


def test_regerar_versao_inexistente_da_erro(tmp_path, monkeypatch):
    destino = tmp_path / "orcamento.db"
    monkeypatch.setattr(arm, "DB_PATH", destino)
    monkeypatch.setattr(svc, "ler_ajustes", lambda: {})
    hoje = date(2026, 7, 1)
    meses_base = sql_mod.meses_fechados(hoje, 12)

    def fake_query(sql, params=None):
        if sql == sql_mod.HIST_CONTA_SQL:
            return [{"conta": "1|100", "mes": m, "valor": -100.0} for m in meses_base]
        if sql == sql_mod.AGRUP_CONTA_SQL:
            return [{"conta": "1|100", "agrupador": "CV - COMBUSTIVEL"}]
        return []

    monkeypatch.setattr(svc.db, "query", fake_query)
    import pytest
    with pytest.raises(KeyError):
        svc.gerar(2026, "x", 0.0, "teste", hoje=hoje, versao_id=999)


# ---------------------------------------------------------------- I3: meses circulares

def test_mes_circular_fica_fora_do_acumulado_mas_aparece_no_mensal():
    """Orçar ano sobreposto à base: o espelho de jan é o próprio jan, então o
    desvio acumulado seria só o fator lido de volta (-5% vira -5,26% em toda
    linha — revisão final, I3). O mês circular sai das linhas/contas/KPIs e
    continua no gráfico mensal, marcado."""
    linhas_orc = [_orc("1|103", m, 5000.0) for m in range(1, 13)]
    realizado = {("1|103", 1): 5263.16, ("1|103", 2): 4000.0}
    r = montar_comparativo(linhas_orc, realizado, MAPA, ate_mes=2,
                           meses_excluidos={1})
    rb = next(l for l in r["linhas"] if l["linha"] == "RECEITA BRUTA")
    assert rb["orcado"] == 5000.0          # só fevereiro
    assert rb["realizado"] == 4000.0
    assert r["meses_circulares"] == [1]
    m1 = next(m for m in r["mensal"] if m["mes"] == 1)
    m2 = next(m for m in r["mensal"] if m["mes"] == 2)
    assert m1["circular"] is True and m1["orcado"] == 5000.0
    assert m2["circular"] is False


def test_meses_circulares_derivados_do_ano_e_da_base():
    base = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12",
            "2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
            "2026-06", "2026-07"]
    assert svc.meses_circulares(2026, base) == [1, 2, 3, 4, 5, 6, 7]
    assert svc.meses_circulares(2027, base) == []


def test_gerar_grava_a_base_e_comparativo_exclui_os_circulares(tmp_path, monkeypatch):
    destino = tmp_path / "orcamento.db"
    monkeypatch.setattr(arm, "DB_PATH", destino)
    monkeypatch.setattr(svc, "ler_ajustes", lambda: {})
    hoje = date(2026, 7, 15)                       # base = jul/25..jun/26
    meses_base = sql_mod.meses_fechados(hoje, 12)

    def fake_query(sql, params=None):
        if sql == sql_mod.HIST_CONTA_SQL:
            return [{"conta": "1|103", "mes": m, "valor": 5000.0} for m in meses_base]
        if sql == sql_mod.AGRUP_CONTA_SQL:
            return [{"conta": "1|103", "agrupador": "RECEITA OPERACIONAL BRUTA"}]
        return []

    monkeypatch.setattr(svc.db, "query", fake_query)
    r = svc.gerar(2026, "Orçamento 2026", -0.05, "teste", hoje=hoje)
    assert r["meses_circulares"] == [1, 2, 3, 4, 5, 6]
    assert r["linhas"] == 12 and r["contas_sem_linha"] == []

    # o comparativo aprende os circulares pela base gravada na versão
    monkeypatch.setattr(svc.db, "query", lambda s, p=None: [
        {"conta": "1|103", "mes": f"2026-{m:02d}", "valor": 4750.0}
        for m in range(1, 7)] if s == sql_mod.REAL_CONTA_SQL else fake_query(s, p))
    out = svc.comparativo(r["versao_id"], ate_mes=6, hoje=hoje)
    assert out["meses_circulares"] == [1, 2, 3, 4, 5, 6]
    # jan-jun são todos circulares: nada acumula, nada de -5,26% artificial
    assert out["linhas"] == []
    assert all(m["circular"] for m in out["mensal"][:6])
    assert not any(m["circular"] for m in out["mensal"][6:])


def test_versao_antiga_sem_meses_base_nao_exclui_nada(tmp_path, monkeypatch):
    """Banco criado antes da coluna: a versão não sabe sua base — segue sem
    exclusão (comportamento anterior), sem quebrar."""
    destino = tmp_path / "orcamento.db"
    monkeypatch.setattr(arm, "DB_PATH", destino)
    monkeypatch.setattr(svc, "ler_ajustes", lambda: {})
    arm.init_db(destino)
    vid = arm.criar_versao(destino, 2026, "antiga", 0.0, "t")   # sem meses_base
    arm.gravar_baseline(destino, vid, [
        {"conta": "1|103", "mes": m, "valor_baseline": 100.0,
         "origem": "espelho", "meses_com_dado": 12} for m in range(1, 13)])
    monkeypatch.setattr(svc.db, "query", lambda s, p=None: (
        [{"conta": "1|103", "agrupador": "RECEITA OPERACIONAL BRUTA"}]
        if s == sql_mod.AGRUP_CONTA_SQL else []))
    out = svc.comparativo(vid, ate_mes=3, hoje=date(2026, 7, 15))
    assert out["meses_circulares"] == []
    rb = next(l for l in out["linhas"] if l["linha"] == "RECEITA BRUTA")
    assert rb["orcado"] == 300.0


# ---------------------------------------------------------------- I2: pendências

def test_sem_linha_nasce_do_realizado_nao_so_das_linhas_persistidas():
    """gerar() remove as contas sem linha antes de persistir, então a lista da
    tela vinha SEMPRE vazia (revisão final, I2; critério de aceite 6). A conta
    com movimento real e sem agrupador tem de aparecer como pendência."""
    linhas_orc = [_orc("1|103", 1, 5000.0)]
    realizado = {("1|103", 1): 4800.0, ("9|999", 1): -321.0}
    r = montar_comparativo(linhas_orc, realizado, MAPA, ate_mes=1)
    assert [x["conta"] for x in r["sem_linha"]] == ["9|999"]
    # e ela NÃO entra na cascata (não soma em linha nenhuma)
    assert all(l["linha"] != "9|999" for l in r["linhas"])


def test_conta_nova_do_realizado_entra_na_cascata_com_orcado_zero():
    """Conta que apareceu depois da geração: descartar o realizado dela abriria
    divergência com a DRE Gerencial. Entra com orçado 0 e desvio integral."""
    linhas_orc = [_orc("1|103", 1, 5000.0)]
    realizado = {("1|103", 1): 5000.0, ("1|100", 1): -700.0}   # 1|100 sem orçamento
    r = montar_comparativo(linhas_orc, realizado, MAPA, ate_mes=1)
    cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert cv["orcado"] == 0.0
    assert cv["realizado"] == -700.0
    assert cv["favoravel"] is False
    conta = next(c for c in r["contas"] if c["conta"] == "1|100")
    assert conta["orcado"] == 0.0 and conta["realizado"] == -700.0


def test_grade_marca_base_fraca_pela_conta_nao_pela_primeira_celula():
    """Com a mediana só nos meses com movimento, o mês 1 de uma esporádica é
    sem_base — a origem da grade tem de ser a da CONTA (mediana)."""
    linhas = []
    for m in range(1, 13):
        l = _orc("1|100", m, 0.0)
        l["origem"] = "mediana" if m in (9, 2) else "sem_base"
        linhas.append(l)
    r = montar_comparativo(linhas, {}, MAPA, ate_mes=0)
    g = next(g for g in r["grade"] if g["conta"] == "1|100")
    assert g["origem"] == "mediana"


# ---------------------------------------------------------------- semestre × sazonalidade

def test_serie_por_linha_soma_contas_da_mesma_linha_e_ignora_sem_linha():
    hist24 = {"1|100": {"2026-01": 100.0, "2026-02": 50.0},
             "1|101": {"2026-01": 20.0},
             "9|999": {"2026-01": 999.0}}
    mapa = {"1|100": "CUSTO VARIAVEL", "1|101": "CUSTO VARIAVEL", "9|999": None}
    serie = svc._serie_por_linha(hist24, mapa)
    assert serie == {"CUSTO VARIAVEL": {"2026-01": 120.0, "2026-02": 50.0}}


def test_gerar_semestre_deriva_nivel_x_indice(tmp_path, monkeypatch):
    """fake_query devolve: HIST 6m p/ a conta (600 no total) e HIST 24m p/ os
    índices (linha com dez=40/resto=100 => índice dez=40/95). Confere dez orçado."""
    destino = tmp_path / "orcamento.db"
    monkeypatch.setattr(arm, "DB_PATH", destino)
    monkeypatch.setattr(svc, "ler_ajustes", lambda: {})
    hoje = date(2026, 7, 1)
    meses6 = sql_mod.meses_fechados(hoje, 6)
    meses24 = sql_mod.meses_fechados(hoje, 24)

    def fake_query(sql, params=None):
        if sql == sql_mod.HIST_CONTA_SQL:
            de = (params or {}).get("de")
            if de == f"{meses6[0]}-01":
                return [{"conta": "1|100", "mes": m, "valor": 100.0} for m in meses6]
            return [{"conta": "1|100", "mes": m,
                     "valor": 40.0 if m.endswith("-12") else 100.0} for m in meses24]
        if sql == sql_mod.AGRUP_CONTA_SQL:
            return [{"conta": "1|100", "agrupador": "CV - COMBUSTIVEL"}]
        return []

    monkeypatch.setattr(svc.db, "query", fake_query)
    r = svc.gerar(2026, "Orçamento 2026", 0.0, "teste", hoje=hoje, metodo="semestre")

    assert r["metodo"] == "semestre"
    esperado_dez = round(100.0 * (40.0 / 95.0) * 1.0, 2)   # nível(600/6) x índice x (1+fator)
    linhas = {(l["conta"], l["mes"]): l for l in arm.ler_linhas(destino, r["versao_id"])}
    assert linhas[("1|100", 12)]["valor_baseline"] == esperado_dez
    assert linhas[("1|100", 12)]["origem"] == "semestre"
    assert linhas[("1|100", 3)]["valor_baseline"] == round(100.0 * (100.0 / 95.0), 2)


def test_gerar_semestre_bloqueia_base_incompleta(tmp_path, monkeypatch):
    """5 dos 6 meses com dado -> ValueError com o mês faltante na mensagem."""
    destino = tmp_path / "orcamento.db"
    monkeypatch.setattr(arm, "DB_PATH", destino)
    monkeypatch.setattr(svc, "ler_ajustes", lambda: {})
    hoje = date(2026, 7, 1)
    meses6 = sql_mod.meses_fechados(hoje, 6)
    faltante = meses6[2]

    def fake_query(sql, params=None):
        if sql == sql_mod.HIST_CONTA_SQL:
            return [{"conta": "1|100", "mes": m, "valor": 100.0}
                    for m in meses6 if m != faltante]
        return []

    monkeypatch.setattr(svc.db, "query", fake_query)
    import pytest
    with pytest.raises(ValueError, match=faltante):
        svc.gerar(2026, "x", 0.0, "teste", hoje=hoje, metodo="semestre")


def test_gerar_espelho_continua_identico(tmp_path, monkeypatch):
    """REGRESSÃO: gerar(metodo='espelho') e gerar() sem metodo produzem as
    MESMAS linhas que hoje (fake 12m; comparar com o resultado esperado do
    espelho para 2-3 contas, incluindo uma esporádica pela mediana)."""
    destino = tmp_path / "orcamento.db"
    monkeypatch.setattr(arm, "DB_PATH", destino)
    monkeypatch.setattr(svc, "ler_ajustes", lambda: {})
    hoje = date(2026, 8, 1)
    meses = sql_mod.meses_fechados(hoje, 12)   # ago/25..jul/26

    def fake_query(sql, params=None):
        if sql == sql_mod.HIST_CONTA_SQL:
            linhas = [{"conta": "1|100", "mes": m,
                       "valor": 4000.0 if m.endswith("-12") else 10000.0}
                      for m in meses]
            linhas += [{"conta": "9|900", "mes": "2025-09", "valor": 300.0},
                       {"conta": "9|900", "mes": "2026-02", "valor": 100.0}]
            return linhas
        if sql == sql_mod.AGRUP_CONTA_SQL:
            return [{"conta": "1|100", "agrupador": "CV - COMBUSTIVEL"},
                    {"conta": "9|900", "agrupador": "CV - COMBUSTIVEL"}]
        return []

    monkeypatch.setattr(svc.db, "query", fake_query)

    r_default = svc.gerar(2026, "sem metodo", 0.0, "teste", hoje=hoje)
    r_espelho = svc.gerar(2026, "com espelho", 0.0, "teste", hoje=hoje, metodo="espelho")

    assert r_default["metodo"] == "espelho"
    assert r_espelho["metodo"] == "espelho"
    assert r_default["linhas_flat"] == []
    assert r_espelho["linhas_flat"] == []

    linhas_default = arm.ler_linhas(destino, r_default["versao_id"])
    linhas_espelho = arm.ler_linhas(destino, r_espelho["versao_id"])
    assert linhas_default == linhas_espelho

    por_mes = {(l["conta"], l["mes"]): l for l in linhas_default}
    assert por_mes[("1|100", 12)]["valor_baseline"] == 4000.0
    assert por_mes[("1|100", 12)]["origem"] == "espelho"
    assert por_mes[("1|100", 11)]["valor_baseline"] == 10000.0
    assert por_mes[("9|900", 9)]["valor_baseline"] == 200.0
    assert por_mes[("9|900", 9)]["origem"] == "mediana"
    assert por_mes[("9|900", 2)]["valor_baseline"] == 200.0
    assert por_mes[("9|900", 1)]["valor_baseline"] == 0.0
    assert por_mes[("9|900", 1)]["origem"] == "sem_base"


def test_regerar_usa_metodo_gravado_e_preserva_ajuste(tmp_path, monkeypatch):
    """Gera com metodo='semestre'; ajusta uma célula; regerar SEM metodo (ou
    com metodo='espelho' no body — deve ser ignorado) mantém metodo='semestre',
    re-deriva pela base semestral e o ajuste sobrevive."""
    destino = tmp_path / "orcamento.db"
    monkeypatch.setattr(arm, "DB_PATH", destino)
    monkeypatch.setattr(svc, "ler_ajustes", lambda: {})
    hoje = date(2026, 7, 1)
    meses6 = sql_mod.meses_fechados(hoje, 6)
    meses24 = sql_mod.meses_fechados(hoje, 24)

    def fake_query(sql, params=None):
        if sql == sql_mod.HIST_CONTA_SQL:
            de = (params or {}).get("de")
            if de == f"{meses6[0]}-01":
                return [{"conta": "1|100", "mes": m, "valor": -100.0} for m in meses6]
            return [{"conta": "1|100", "mes": m, "valor": -100.0} for m in meses24]
        if sql == sql_mod.AGRUP_CONTA_SQL:
            return [{"conta": "1|100", "agrupador": "CV - COMBUSTIVEL"}]
        return []

    monkeypatch.setattr(svc.db, "query", fake_query)

    r1 = svc.gerar(2026, "Orçamento 2026", 0.0, "teste", hoje=hoje, metodo="semestre")
    assert r1["metodo"] == "semestre"
    arm.ajustar(destino, r1["versao_id"], "1|100", 3, -777.0, "controladoria")

    # "metodo='espelho' no body" simulado: o parâmetro recebido tem de ser IGNORADO
    r2 = svc.gerar(2026, "Orçamento 2026", -0.10, "teste", hoje=hoje,
                   versao_id=r1["versao_id"], metodo="espelho")

    assert r2["versao_id"] == r1["versao_id"]
    assert r2["metodo"] == "semestre"
    assert r2["regerada"] is True

    v = arm.listar_versoes(destino, 2026)[0]
    assert v["metodo"] == "semestre"          # regravado coerente

    linhas = {(l["conta"], l["mes"]): l for l in arm.ler_linhas(destino, r1["versao_id"])}
    ajustada = linhas[("1|100", 3)]
    assert ajustada["valor_ajustado"] == -777.0
    assert ajustada["valor_efetivo"] == -777.0
    assert ajustada["origem"] == "semestre"
    # baseline recalculado pela base semestral com o novo fator (-10%)
    assert linhas[("1|100", 4)]["valor_baseline"] == -90.0
    assert linhas[("1|100", 4)]["valor_efetivo"] == -90.0


def test_resposta_traz_metodo_e_linhas_flat(tmp_path, monkeypatch):
    destino = tmp_path / "orcamento.db"
    monkeypatch.setattr(arm, "DB_PATH", destino)
    monkeypatch.setattr(svc, "ler_ajustes", lambda: {})
    hoje = date(2026, 7, 1)
    meses6 = sql_mod.meses_fechados(hoje, 6)
    meses12 = sql_mod.meses_fechados(hoje, 12)
    meses24 = sql_mod.meses_fechados(hoje, 24)

    def fake_query(sql, params=None):
        if sql == sql_mod.HIST_CONTA_SQL:
            de = (params or {}).get("de")
            if de == f"{meses6[0]}-01":
                return [{"conta": "1|100", "mes": m, "valor": 100.0} for m in meses6]
            if de == f"{meses12[0]}-01":
                return [{"conta": "1|100", "mes": m, "valor": 100.0} for m in meses12]
            # janela de 24m com só 18 meses: dispara a guarda de dado faltante
            # em indices_sazonais e a linha entra em linhas_flat
            return [{"conta": "1|100", "mes": m, "valor": 100.0} for m in meses24[-18:]]
        if sql == sql_mod.AGRUP_CONTA_SQL:
            return [{"conta": "1|100", "agrupador": "CV - COMBUSTIVEL"}]
        return []

    monkeypatch.setattr(svc.db, "query", fake_query)

    r_esp = svc.gerar(2026, "espelho", 0.0, "teste", hoje=hoje, metodo="espelho")
    assert r_esp["metodo"] == "espelho"
    assert r_esp["linhas_flat"] == []

    r_sem = svc.gerar(2026, "semestre", 0.0, "teste", hoje=hoje, metodo="semestre")
    assert r_sem["metodo"] == "semestre"
    assert r_sem["linhas_flat"] == ["CUSTO VARIAVEL"]


def test_nome_da_conta_acompanha_grade_desvios_e_pendencias():
    """A chave grupo|reduzido sozinha só diz algo para quem decorou o plano de
    contas: o nome (planoconta.descricao) acompanha os três lugares da tela."""
    nomes = {"1|100": "COMBUSTIVEL FROTA", "9|999": "CONTA ORFA"}
    linhas_orc = [_orc("1|100", 1, -1000.0)]
    realizado = {("1|100", 1): -900.0, ("9|999", 1): -5.0}
    r = montar_comparativo(linhas_orc, realizado, MAPA, ate_mes=1, nomes=nomes)
    g = next(x for x in r["grade"] if x["conta"] == "1|100")
    assert g["nome"] == "COMBUSTIVEL FROTA"
    c = next(x for x in r["contas"] if x["conta"] == "1|100")
    assert c["nome"] == "COMBUSTIVEL FROTA"
    assert r["sem_linha"] == [{"conta": "9|999", "nome": "CONTA ORFA"}]
    # sem o dicionário, o nome sai None e nada quebra
    r2 = montar_comparativo(linhas_orc, {}, MAPA, ate_mes=1)
    assert next(x for x in r2["grade"] if x["conta"] == "1|100")["nome"] is None
