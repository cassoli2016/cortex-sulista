# -*- coding: utf-8 -*-
"""O painel de TV do RH (`api/rh/tv.py`), sem banco.

As linhas de `sulista.indicadorescorporativos` têm a FORMA que o ERP devolve
(colunas e códigos conferidos na tabela em 16/09/2026); os valores são
pequenos e inventados.
"""
from __future__ import annotations

from datetime import date

import pytest

from api import auth
from api.rh import tv

HOJE = date(2026, 9, 16)


# ---------------------------------------------------------------- filial e nome
@pytest.mark.parametrize("secao,esperado", [
    ("MATRIZ", "Matriz"), ("MATRIZ - FINANCEIRO", "Matriz"), ("FILIAL CURITIBA", "Matriz"),
    ("FILIAL GARUVA", "Joinville"), ("FILIAL SBC", "SBC"), ("FILIAL CRUZEIRO", "Cruzeiro"),
    ("FILIAL POUSO ALEGRE", "Pouso Alegre"), ("FILIAL NOVA", "Nova"), (None, "Sem filial"),
])
def test_a_filial_e_a_da_tv_do_rh(secao, esperado):
    """Matriz soma Curitiba e Garuva é Joinville — é assim que a TV antiga
    fechava 83 e 16. Seção desconhecida aparece com o próprio nome."""
    assert tv.filial_da_tv(secao) == esperado


def test_nome_proprio():
    assert tv.nome_proprio("MARIA DA SILVA DOS SANTOS") == "Maria da Silva dos Santos"
    assert tv.nome_proprio("  JOSE  E  ANA ") == "Jose e Ana"
    assert tv.nome_proprio(None) == ""


# ---------------------------------------------------------------- segurança e qualidade
def _acid(mes, n, classe):
    return {"mes": mes, "indicador": 7, "acidentes": n, "classificacao": classe, "reclamacoesclientes": None}


def _rnc(mes, n):
    return {"mes": mes, "indicador": 16, "acidentes": None, "classificacao": None, "reclamacoesclientes": n}


LINHAS = [
    _acid("2026-01", 2, 1), _acid("2026-02", 2, 1), _acid("2026-03", 4, 1), _acid("2026-03", 1, 2),
    _acid("2026-03", 1, 0),          # ocupacional sem classificação: fica fora
    _acid("2026-04", 1, 3),          # grave: SEM vítima (com vítima é morte, e vem do registro)
    _acid("2025-10", 1, 1),
    _rnc("2025-10", 3), _rnc("2026-03", 7), _rnc("2026-06", 1),
    _acid("2024-01", 9, 1),          # fora da janela de 12 meses
]


def test_leve_medio_e_grave_sao_sem_vitima_e_classe_zero_fica_fora():
    """Quem opera, 16/09/2026: "com vítima seria com morte, e não grave"."""
    r = tv.montar_seguranca(LINHAS, {7: "2026-06", 16: "2026-06"}, HOJE, fatais=[])
    a = {x["mes"]: x for x in r["acidentes"]["serie"]}
    assert a["2026-03"]["sem_vitima"] == 5 and a["2026-03"]["leve"] == 4 and a["2026-03"]["medio"] == 1
    assert a["2026-04"]["sem_vitima"] == 1 and a["2026-04"]["grave"] == 1 and a["2026-04"]["com_vitima"] == 0
    assert r["acidentes"]["sem_vitima_ano"] == 10          # 2 + 2 + 5 + 1, outubro/25 é do ano passado
    assert r["acidentes"]["sem_vitima_12m"] == 11
    assert r["acidentes"]["com_vitima_ano"] == 0
    assert r["rnc"]["ano"] == 8 and r["rnc"]["ultimos_12m"] == 11


def test_com_vitima_vem_do_registro_de_morte_e_conta_todo_mes():
    """O registro é do CÓRTEX: não existe "sem lançamento" nele — o mês depois
    do último lançamento da Qualidade conta a morte registrada normalmente."""
    fatais = ["2026-08-03", "2026-01-15", "2025-10-02", "2024-05-05"]
    r = tv.montar_seguranca(LINHAS, {7: "2026-06", 16: "2026-06"}, HOJE, fatais=fatais)
    a = {x["mes"]: x["com_vitima"] for x in r["acidentes"]["serie"]}
    assert a["2026-08"] == 1 and a["2026-01"] == 1 and a["2025-10"] == 1 and a["2026-09"] == 0
    assert r["acidentes"]["com_vitima_ano"] == 2 and r["acidentes"]["com_vitima_12m"] == 3
    assert r["acidentes"]["registro_fatal"] == "ok"


def test_registro_de_morte_ilegivel_e_ausencia_nunca_zero():
    r = tv.montar_seguranca(LINHAS, {7: "2026-06", 16: "2026-06"}, HOJE, fatais=None)
    assert all(x["com_vitima"] is None for x in r["acidentes"]["serie"])
    assert r["acidentes"]["com_vitima_ano"] is None and r["acidentes"]["registro_fatal"] == "indisponivel"
    assert r["acidentes"]["sem_vitima_ano"] == 10          # o resto da lâmina segue


def test_mes_depois_do_ultimo_lancamento_e_ausencia_nao_zero():
    """A TV antiga mostrava zero acidente de julho a setembro: era a Qualidade
    que não tinha lançado. Aqui esses meses vêm None — e não entram na soma."""
    r = tv.montar_seguranca(LINHAS, {7: "2026-06", 16: "2026-03"}, HOJE)
    a = {x["mes"]: x for x in r["acidentes"]["serie"]}
    assert a["2026-06"]["sem_vitima"] == 0 and a["2026-06"]["lancado"]
    for m in ("2026-07", "2026-08", "2026-09"):
        assert a[m]["sem_vitima"] is None and not a[m]["lancado"]
    rnc = {x["mes"]: x["rnc"] for x in r["rnc"]["serie"]}
    assert rnc["2026-03"] == 7 and rnc["2026-04"] is None and rnc["2026-06"] is None
    assert r["rnc"]["ano"] == 7           # a de junho não foi lançada ainda por esta régua


def test_sem_lancamento_nenhum_e_tudo_ausente():
    r = tv.montar_seguranca([], {}, HOJE)
    assert all(x["sem_vitima"] is None for x in r["acidentes"]["serie"])
    assert r["acidentes"]["sem_vitima_ano"] == 0 and r["acidentes"]["ultimo_lancamento"] is None


def test_os_doze_meses_sao_gerados_mesmo_sem_linha():
    r = tv.montar_seguranca([], {7: "2026-09", 16: "2026-09"}, HOJE)
    meses = [x["mes"] for x in r["acidentes"]["serie"]]
    assert meses[0] == "2025-10" and meses[-1] == "2026-09" and len(meses) == 12
    assert all(x["sem_vitima"] == 0 for x in r["acidentes"]["serie"])


def test_o_sql_da_qualidade_nao_tem_porcento_solto():
    import re
    for sql in (tv.QUALIDADE_SQL, tv.ULTIMO_SQL):
        assert not re.search(r"%(?!\(\w+\)s)", sql)


# ---------------------------------------------------------------- desligamento
def test_rescisao_de_quem_segue_ativo_nao_e_desligamento(monkeypatch):
    """Há rescisão lançada para gente que continua no quadro (20 das 35
    'dispensas' de nov/2025): contá-la levava o turnover do mês a 12%. As DUAS
    consultas de rescisão levam a trava."""
    vistos = []

    def falso(sql, p=None):
        vistos.append(sql)
        return [{"n": 1, "m": "2026-09"}]
    monkeypatch.setattr(tv, "_qf", falso)
    tv.turnover.__wrapped__() if hasattr(tv.turnover, "__wrapped__") else tv.turnover()
    try:
        tv.mes(hoje=date(2031, 1, 5))
    except Exception:  # noqa: BLE001 — o dublê não tem as colunas; só interessa o SQL
        pass
    rescisoes = [s for s in vistos if "flp_quitacao" in s]
    assert len(rescisoes) == 2, rescisoes
    assert all(tv.SAIU in s for s in rescisoes)


def test_experiencia_vence_aos_45_e_aos_90_dias(monkeypatch):
    adm = lambda dias: {"adm": date.fromordinal(HOJE.toordinal() - dias)}   # noqa: E731
    # 40 dias de casa: vence o 45º dia em 4 dias; 60 dias: o 90º em 29 (fora);
    # 80 dias: o 90º em 9 dias
    monkeypatch.setattr(tv, "_qf", lambda sql, p=None: [adm(40), adm(60), adm(80)])
    r = tv._experiencia(HOJE)
    assert r["vencendo"] == 2 and r["em_experiencia"] == 3


# ---------------------------------------------------------------- resposta e Copiloto
def test_bloco_que_falha_nao_derruba_a_parede(monkeypatch):
    monkeypatch.setattr(tv, "gente", lambda: {"ativos": 1})
    monkeypatch.setattr(tv, "mes", lambda: (_ for _ in ()).throw(RuntimeError("globus")))
    monkeypatch.setattr(tv, "seguranca", lambda: {"ok": True})
    monkeypatch.setattr(tv, "indicadores", lambda: {})
    r = tv.painel()
    assert r["gente"] == {"ativos": 1} and r["mes"] == {"erro": "indisponivel"} and r["seguranca"] == {"ok": True}


def test_copiloto_so_recebe_contagens_sem_nome(monkeypatch):
    monkeypatch.setattr(tv, "gente", lambda: {"ativos": 194, "afastados": 14, "lideranca": {"lideres": 16}})
    monkeypatch.setattr(tv, "mes", lambda: {
        "aniversariantes": {"total": 2, "hoje": [{"nome": "Fulano de Tal"}]},
        "admitidos": [{"nome": "Beltrano"}], "desligados": [{"nome": "Sicrano"}]})
    monkeypatch.setattr(tv, "seguranca", lambda: tv.montar_seguranca(LINHAS, {7: "2026-06", 16: "2026-06"}, HOJE, fatais=[]))
    r = tv.resumo_copiloto()
    texto = repr(r)
    for nome in ("Fulano", "Beltrano", "Sicrano"):
        assert nome not in texto
    assert r["admitidos_mes"] == 1 and r["desligados_mes"] == 1 and r["ativos"] == 194
    assert all(not isinstance(v, (list, dict)) for v in r.values())


def test_a_rota_e_da_tela_tvrh():
    telas = next(t for pref, t in auth.ROTA_TELAS if "/api/rh/tv".startswith(pref))
    assert telas == frozenset({"tvrh"})
    assert auth.TELAS["tvrh"][1] == "Business Intelligence"
