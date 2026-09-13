"""A regra dos ajustes de acesso por usuário (api/acessos.py) — sem banco.

Pedido de quem opera (13/09/2026): página inicial por usuário, liberar e tirar
telas por usuário, tirar abas. Três decisões guardadas aqui: TIRAR vence tudo,
ADMINISTRADOR ignora os ajustes, e ABA só se tira onde o servidor recusa a
rota (as de rota própria, `acessos.ABAS`).
"""
from __future__ import annotations

import pytest

from api import acessos, auth

TODAS = list(auth.TELAS.keys())

# Unidade de aba de mentira, com uma rota inventada: os testes de REGRA não
# dependem do registro real (que tem guard próprio contra o disco).
ABA_FALSA = {"fluxo.proj": {"tela": "fluxo", "rotulo": "Projeção",
                            "abas": (("flx", "proj"), ("flx", "proj2")),
                            "rotas": ("/api/financeiro/projecao-falsa",)}}


@pytest.fixture
def aba_falsa(monkeypatch):
    monkeypatch.setattr(acessos, "ABAS", dict(ABA_FALSA))


# ─────────────────────────────────────────────────────── acesso efetivo ────

def test_liberar_acrescenta_e_tirar_remove_do_perfil():
    telas, abas = acessos.efetivas(["fluxo", "dre"],
                                   [("dre", "tirar"), ("cop", "liberar")], False, TODAS)
    assert set(telas) == {"fluxo", "cop"}
    assert abas == []


def test_TIRAR_vence_o_perfil_e_a_ordem_segue_o_registro():
    telas, _ = acessos.efetivas(["dre", "fluxo"], [("fluxo", "tirar")], False, TODAS)
    assert telas == ["dre"]
    telas, _ = acessos.efetivas(["dre", "fluxo"], [], False, TODAS)
    assert telas == [t for t in TODAS if t in {"dre", "fluxo"}], "ordem do registro"


def test_ADMIN_ignora_os_ajustes():
    telas, abas = acessos.efetivas([], [("dre", "tirar")], True, TODAS)
    assert telas == TODAS and abas == []


def test_chave_desconhecida_e_INERTE_nunca_amplia_acesso():
    """Tela aposentada deixa a linha no banco; ela não pode abrir nada."""
    telas, _ = acessos.efetivas(["fluxo"], [("tela_que_nao_existe", "liberar")], False, TODAS)
    assert telas == ["fluxo"]


def test_aba_tirada_so_conta_se_a_pessoa_ve_a_tela(aba_falsa):
    _, abas = acessos.efetivas(["fluxo"], [("fluxo.proj", "tirar")], False, TODAS)
    assert abas == ["fluxo.proj"]
    _, abas = acessos.efetivas(["dre"], [("fluxo.proj", "tirar")], False, TODAS)
    assert abas == [], "sem a tela, a aba não tem o que esconder"


def test_ocultas_devolve_todos_os_pares_da_unidade(aba_falsa):
    assert acessos.ocultas(["fluxo.proj"]) == [["flx", "proj"], ["flx", "proj2"]]
    assert acessos.ocultas(["nao.existe"]) == []


def test_aba_da_rota_respeita_a_fronteira_do_segmento(aba_falsa):
    assert acessos.aba_da_rota("/api/financeiro/projecao-falsa") == "fluxo.proj"
    assert acessos.aba_da_rota("/api/financeiro/projecao-falsa/12") == "fluxo.proj"
    assert acessos.aba_da_rota("/api/financeiro/projecao-falsa-outra") is None
    assert acessos.aba_da_rota("/api/financeiro/projecao") is None


# ──────────────────────────────────────────────────────────── validação ────

def test_validar_aceita_tela_e_aba_e_normaliza(aba_falsa):
    ok, erro = acessos.validar([{"chave": " cop ", "efeito": "liberar"},
                                {"chave": "fluxo.proj", "efeito": "tirar"}], TODAS)
    assert erro is None and ok == [("cop", "liberar"), ("fluxo.proj", "tirar")]


@pytest.mark.parametrize("bruto, pedaco", [
    ("não é lista", "formato"),
    ([{"chave": "cop", "efeito": "ver"}], "efeito"),
    ([{"chave": "inventada", "efeito": "liberar"}], "não é uma tela"),
    ([{"chave": "fluxo.proj", "efeito": "liberar"}], "Aba só se tira"),
    ([{"chave": "cop", "efeito": "liberar"}, {"chave": "cop", "efeito": "tirar"}], "duas vezes"),
    (["cop"], "formato"),
])
def test_validar_recusa_dizendo_o_motivo(aba_falsa, bruto, pedaco):
    ok, erro = acessos.validar(bruto, TODAS)
    assert ok is None and pedaco in erro


def test_validar_tem_teto():
    bruto = [{"chave": t, "efeito": "liberar"} for t in TODAS] * 10
    ok, erro = acessos.validar(bruto[:acessos.MAX_AJUSTES + 1], TODAS)
    assert ok is None and str(acessos.MAX_AJUSTES) in erro


# ───────────────────────────────────────────────────────── página inicial ──

def test_pagina_de_todo_logado_vale_para_qualquer_um():
    assert acessos.pagina_efetiva("radar", [], False) == "radar"


def test_pagina_fora_do_acesso_cai_no_padrao():
    assert acessos.pagina_efetiva("dre", ["fluxo"], False) is None
    assert acessos.pagina_efetiva("dre", ["dre"], False) == "dre"


def test_gestao_e_saude_so_para_admin():
    assert acessos.pagina_efetiva("gestao", TODAS, False) is None
    assert acessos.pagina_efetiva("srv", [], True) == "srv"


def test_permissao_sem_tela_e_chave_inventada_nao_sao_pagina():
    """`dreexc` é permissão de ação, não tela — não abre nada."""
    assert "dreexc" in auth.TELAS_SEM_MENU
    assert acessos.pagina_efetiva("dreexc", ["dreexc"], False) is None
    assert acessos.pagina_efetiva("inventada", [], True) is None
    assert not acessos.pagina_escolhivel("dreexc")
    assert acessos.pagina_escolhivel("radar") and acessos.pagina_escolhivel("dre")


def test_jornada_de_frota_segue_a_jornada():
    assert acessos.pagina_efetiva("jornf", ["jorn"], False) == "jornf"
    assert acessos.pagina_efetiva("jornf", [], False) is None


def test_vazio_e_padrao():
    assert acessos.pagina_efetiva("", TODAS, True) is None
    assert acessos.pagina_efetiva(None, TODAS, True) is None


# ─────────────────────────────────────────────────────────────── trilha ────

def test_diff_diz_o_que_entrou_e_o_que_saiu():
    txt = acessos.diff([("dre", "tirar"), ("cop", "liberar")],
                       [("cop", "liberar"), ("fluxo", "tirar")])
    assert txt == "+tirar fluxo, -tirar dre"
    assert acessos.diff([("cop", "liberar")], [("cop", "liberar")]) == ""
