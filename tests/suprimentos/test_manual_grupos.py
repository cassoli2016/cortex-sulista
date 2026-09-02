"""O manual (tela #doc) tem de agrupar cada tela no MESMO grupo do RBAC.

`api/auth.py` é o registro canônico das telas. O manual.yaml punha Ordens de
Compra e Painel de Custos em Financeiro e Agregados/Make-vs-Buy em Suprimentos
— o inverso do menu, do VIEW_GROUP e do RBAC — e nenhum teste comparava:
`test_toda_tela_do_painel_esta_em_algum_grupo` só exige "algum grupo".
"""
from __future__ import annotations

from pathlib import Path

import yaml

from api import auth

MANUAL = Path(__file__).resolve().parents[2] / "docs" / "manual.yaml"

# nomes do manual que traduzem um grupo do RBAC
SINONIMOS = {"Pessoas": "Recursos Humanos"}
# telas fora do RBAC (§3 do CLAUDE.md) e grupos do manual sem contraparte no RBAC
FORA = {"srv", "gestao", "jornf"}
GRUPOS_LIVRES = {"Visão geral", "Gestão", "Administração", "Business Intelligence", "Telemetria", "ANTT"}


def test_grupo_do_manual_e_o_grupo_do_rbac():
    dados = yaml.safe_load(MANUAL.read_text(encoding="utf-8"))
    do_manual = {}
    for g in dados["grupos"]:
        for tela in g.get("telas") or []:
            do_manual[tela] = SINONIMOS.get(g["nome"], g["nome"])
    erros = []
    for tela, (_titulo, grupo) in auth.TELAS.items():
        if tela in FORA or tela not in do_manual:
            continue
        if do_manual[tela] in GRUPOS_LIVRES:
            continue
        if do_manual[tela] != grupo:
            erros.append(f"{tela}: manual diz {do_manual[tela]!r}, RBAC diz {grupo!r}")
    assert not erros, "a tela #doc mostra o grupo errado -> " + " · ".join(erros)


def test_suprimentos_no_manual_e_o_modulo_de_compras():
    dados = yaml.safe_load(MANUAL.read_text(encoding="utf-8"))
    sup = next(g for g in dados["grupos"] if g["nome"] == "Suprimentos")
    assert set(sup["telas"]) == {"oc", "custos"}
    termos = {t["termo"] for t in dados["glossario"]}
    assert any("aprovação" in t.lower() and "oc" in t.lower() for t in termos), "glossário sem o fluxo de aprovação da OC"
    assert any("alçada" in t.lower() for t in termos)
    assert any("sem nota" in t.lower() for t in termos)
