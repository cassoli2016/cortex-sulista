# -*- coding: utf-8 -*-
"""A tela Ritual — Indicadores e Metas, contra o index.html real.

Este arquivo existe por uma lição desta mesma semana: a tela de Equipamentos
subiu quebrada e passou em TODAS as réguas da casa (altura, largura, tema,
espaçamento, estrutura), porque nenhuma delas percorre o caminho do dado. Um
erro de JavaScript não muda a altura de uma seção.

Aqui a tela é aberta de verdade, com as rotas dubladas, e um único erro de
página reprova.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

CONFIG = {
    "gerencias": [
        {"id": 1, "chave": "com", "nome": "Comercial", "gestor_id": None,
         "gestor_nome": None, "ordem": 1, "ativa": 1, "indicadores": 2},
        {"id": 2, "chave": "ope", "nome": "Operação", "gestor_id": 7,
         "gestor_nome": "Fulana", "ordem": 2, "ativa": 1, "indicadores": 1},
    ],
    "indicadores": [
        # SEM META: é o estado real dos 12 indicadores em 08/09/2026.
        {"id": 10, "gerencia_id": 1, "gerencia_nome": "Comercial",
         "nome": "Receita faturada", "unidade": "R$", "direcao": "maior_melhor",
         "fonte": "receita_faturada_mes", "fonte_onde": "Faturamento",
         "fonte_orfa": False, "automatico": True, "meta_padrao": None,
         "tol_verde": 0.0, "tol_vermelho": -10.0, "casas": 0, "ativo": 1},
        # COM META: a linha que já tem régua.
        {"id": 11, "gerencia_id": 2, "gerencia_nome": "Operação",
         "nome": "Retorno vazio", "unidade": "%", "direcao": "menor_melhor",
         "fonte": "retorno_vazio", "fonte_onde": "Análise de KM",
         "fonte_orfa": False, "automatico": True, "meta_padrao": 18.0,
         "tol_verde": 0.0, "tol_vermelho": -10.0, "casas": 1, "ativo": 1},
    ],
    "fontes": [{"chave": "retorno_vazio", "rotulo": "Retorno vazio",
                "onde": "Análise de KM", "unidade": "%"}],
    "usuarios": [{"id": 7, "nome": "Fulana"}],
}


def _abrir(pagina, config=None):
    pg, base_url = pagina
    chamadas = []

    def rota(route):
        u = route.request.url
        chamadas.append(u.split("/api/")[-1].split("?")[0])
        corpo = (USUARIO if "/api/auth/me" in u
                 else (config if config is not None else CONFIG)
                 if "/api/ritual/config" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#gesind")
    pg.wait_for_selector("#rit-inds tr", timeout=20000)
    return pg, erros, chamadas


def test_a_tela_abre_SEM_erro_de_pagina(pagina):
    _, erros, _ = _abrir(pagina)
    assert not erros, f"a pagina levantou erro de JS: {erros}"


def test_a_tela_le_a_rota_de_CONFIG_e_nao_a_de_preencher(pagina):
    """A separação de acesso vale do lado do navegador também.

    Se a tela chamasse `/api/ritual/cadastro`, ela funcionaria para o gerente
    — e a permissão separada viraria enfeite, porque o servidor nunca seria
    perguntado pela rota protegida.
    """
    _, _, chamadas = _abrir(pagina)
    assert any(c.startswith("ritual/config") for c in chamadas), chamadas
    assert not any(c.startswith("ritual/cadastro") for c in chamadas), chamadas


def test_indicador_SEM_META_e_dito_e_nao_travessao(pagina):
    """Travessão se lê como "não se aplica"; aqui significa "o farol não vai
    acender nesta linha", e o conserto é nesta mesma tela."""
    pg, _, _ = _abrir(pagina)
    tabela = pg.locator("#rit-inds").inner_text()
    assert "sem meta" in tabela
    assert "18" in tabela, "a linha COM meta deveria mostrar o valor"


def test_gerencia_sem_gestor_e_dita(pagina):
    """A lista de pendências existe para dizer A QUEM cobrar. Sem gestor ela
    sabe o que falta e não sabe de quem — e isso precisa aparecer."""
    pg, _, _ = _abrir(pagina)
    assert "sem gestor" in pg.locator("#gesind-gers").inner_text()


def test_os_KPIs_medem_o_PROPRIO_CADASTRO(pagina):
    """É a única tela cujo trabalho é deixar OUTRA tela funcionar: os números
    do topo são as duas faltas que impedem o painel da semana de acender."""
    pg, _, _ = _abrir(pagina)
    texto = pg.locator("#gesind-kpis").inner_text()
    assert "Sem meta" in texto and "Sem gestor" in texto
    assert "aparecem no painel SEM COR" in texto


def test_cadastro_completo_NAO_acusa_falta(pagina):
    """O espelho: guard que só sabe acusar acusa sempre.

    Com meta e gestor em tudo, os avisos somem — senão a tela gritaria para
    sempre e ensinaria a ignorar o aviso.
    """
    completo = {
        **CONFIG,
        "gerencias": [{**g, "gestor_id": 7, "gestor_nome": "Fulana"}
                      for g in CONFIG["gerencias"]],
        "indicadores": [{**i, "meta_padrao": 100.0}
                        for i in CONFIG["indicadores"]],
    }
    pg, _, _ = _abrir(pagina, config=completo)
    assert "sem meta" not in pg.locator("#rit-inds").inner_text()
    assert "sem gestor" not in pg.locator("#gesind-gers").inner_text()
    assert "todos com régua" in pg.locator("#gesind-kpis").inner_text()
