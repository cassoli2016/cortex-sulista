"""A tela da Smartec renderizada — com o PAYLOAD REAL do banco.

A tela vive no id `mul`, HERDADO da antiga tela de Multas do ERP quando as
duas viraram uma. O id não é detalhe: `mul` já estava concedido aos perfis
Diretoria e Frota, e um id novo faria multas sumirem do menu deles.

Fixture é escrita por quem já sabe o que espera. O dado real traz o campo nulo
em dois terços das linhas, o nome com acento e o LIMIT batendo — foi assim que
três defeitos da ficha do motorista apareceram, e nenhum falhava teste nenhum.

Aqui o payload sai de `leitura` contra um schema de verdade, populado com os
mesmos corpos que o fornecedor devolve.
"""
from __future__ import annotations

import json

import pytest

from api.smartec import armazenamento as arm

from .test_armazenamento import MULTA, NOTIFICACAO

pytest.importorskip("playwright")


@pytest.fixture
def payload(esquema_pg):
    """Payload igual ao da rota, montado do banco."""
    from api.smartec import leitura as lei
    esq = esquema_pg
    arm.gravar_infracoes([MULTA], "multa", esq)
    # uma notificação AINDA NO PRAZO — é o caso que a tela existe para mostrar
    from datetime import date, timedelta
    prazo = (date.today() + timedelta(days=3)).strftime("%d/%m/%Y")
    arm.gravar_infracoes([dict(NOTIFICACAO, PRAZO_INDICACAO=prazo)],
                         "notificacao", esq)
    arm.gravar_veiculos([{"RENAVAM": "1142889448", "PLACA": "BBX3375",
                          "TIPO": "SEMIRREBOQUE", "UF": "PR"}], esq)
    arm.gravar_licencas([{"Renavam": "1142889448", "Placa": "BBX3375",
                          "Frota": "MTZ", "Cronotacografo": "04/07/2026"}], esq)
    arm.gravar_acessos([{"CODIGO": 0, "DESCRICAO": "Acesso OK",
                         "EMPRESA": "TRANSPORTADORA SULISTA S/A",
                         "CNPJ": "76104397000123",
                         "DATA_EXPIRACAO_ACESSO": "28/09/2026"}], "sne", esq)
    arm.gravar_antt([{"AIT": "FELVP00382452026", "PROCESSO": "50501.353726/2026-17",
                      "DATA_INFRACAO": "07/04/2026", "TIPO": "Vale Pedágio",
                      "DESCRICAO": "Vale Pedágio", "PLACA": "ASC3306",
                      "SITUACAO": "Congelado por Defesa Tempestiva",
                      "IMPEDITIVA": 0, "LOCAL": "Rodovia BR116 Km 542"}], esq)
    cid = arm.carga_abrir("multa", esq)
    arm.carga_fechar(cid, "ok", 1, 97, "", esq)
    return {
        "kpis": lei.kpis(esquema=esq),
        "multas": lei.infracoes("multa", 400, esquema=esq),
        "notificacoes": lei.infracoes("notificacao", 600, esquema=esq),
        "por_veiculo": lei.por_veiculo("multa", 40, esquema=esq),
        "por_infracao": lei.por_infracao("multa", 15, esquema=esq),
        "por_orgao": lei.por_orgao("multa", 12, esquema=esq),
        "mensal": lei.mensal(esquema=esq),
        "licencas": lei.licencas(esquema=esq),
        "antt": lei.antt(200, esquema=esq),
        "antt_situacao": lei.antt_por_situacao(esquema=esq),
        "cobertura": {"disponivel": False},
        "historico": lei.historico(100, esquema=esq),
        "cargas": lei.cargas(20, esquema=esq),
    }


def _rotear(pagina, payload):
    """UM handler para todo /api/**, roteando por URL dentro dele.

    É como o resto da casa faz, e evita de vez a ambiguidade de precedência
    entre um catch-all e um mock específico — que foi o que fez esta tela
    renderizar com o payload vazio na primeira tentativa: os KPIs saíam
    zerados, sem erro nenhum, e a tela parecia simplesmente não ter dado.
    """
    def _rota(rota):
        url = rota.request.url
        if "/api/smartec/painel" in url:
            corpo = payload
        elif "/api/auth/me" in url:
            corpo = {"nome": "Teste", "email": "t@s.local", "perfil": "admin",
                     "admin": True, "telas": []}
        else:
            corpo = {}
        rota.fulfill(status=200, content_type="application/json",
                     body=json.dumps(corpo, default=str))
    pagina.route("**/api/**", _rota)


@pytest.fixture
def tela(pagina, base_url, payload):
    """Abre a tela #smt com o payload real interceptado."""
    _rotear(pagina, payload)
    pagina.goto(f"{base_url}/static/index.html#mul")
    pagina.wait_for_selector("#view-mul.on", timeout=15000)
    pagina.wait_for_function(
        "document.querySelectorAll('#kpis-smtmul .kpi').length > 0", timeout=15000)
    return pagina


def test_a_tela_abre_e_os_kpis_saem_preenchidos(tela):
    txt = tela.inner_text("#kpis-smtmul")
    assert "Multas em aberto" in txt
    # o valor tem de aparecer formatado em pt-BR, nao cru
    assert "130,16" in txt, f"valor nao formatado: {txt}"


def test_a_aba_do_grafico_NASCE_VISIVEL(tela):
    """O ECharts mede o contêiner uma vez, no init.

    Medida feita sob `hidden` vale zero para sempre, e o sintoma é mudo: o
    gráfico aparece com os eixos certos e quase todos os rótulos do eixo X
    suprimidos, fazendo uma série de cinco pontos parecer ter um.
    """
    assert tela.is_visible("#aba-smtmul"), "a aba com gráfico nasceu escondida"
    caixa = tela.evaluate(
        "()=>{const e=document.getElementById('chart-smtmes');"
        "const r=e.getBoundingClientRect(); return {w:r.width,h:r.height};}")
    assert caixa["w"] > 200, f"contêiner do gráfico mediu {caixa}"


def test_notificacao_no_prazo_aparece_com_o_prazo_em_destaque(tela):
    tela.click("#tabsmt-not")
    tela.wait_for_selector("#aba-smtnot:not([hidden])")
    linhas = tela.inner_text("#tb-smtnot")
    assert "em 3 dias" in linhas, f"prazo não destacado: {linhas[:300]}"


def test_as_duas_especies_NAO_se_somam_na_tela(tela):
    """O KPI de multas não pode ter absorvido a notificação."""
    mul = tela.inner_text("#kpis-smtmul")
    tela.click("#tabsmt-not")
    tela.wait_for_selector("#aba-smtnot:not([hidden])")
    not_ = tela.inner_text("#kpis-smtnot")
    # 1 de cada; se somasse, o cartao de multas diria 2
    assert "\n1\n" in mul or ">1<" in mul or " 1 " in f" {mul} "
    assert "Notificações em aberto" in not_


def test_o_acesso_ao_SNE_vira_KPI_com_os_dias(tela):
    """Vencimento do acesso é KPI, não nota de rodapé — ele desliga tudo."""
    tela.click("#tabsmt-lic")
    tela.wait_for_selector("#aba-smtlic:not([hidden])")
    txt = tela.inner_text("#kpis-smtlic")
    assert "Acesso ao SNE" in txt
    assert "dias" in txt or "expirado" in txt


def test_a_aba_da_ANTT_separa_da_multa_de_transito(tela):
    tela.click("#tabsmt-antt")
    tela.wait_for_selector("#aba-smtantt:not([hidden])")
    txt = tela.inner_text("#tb-smtantt")
    assert "Vale Pedágio" in txt
    assert "FELVP00382452026" in txt


def test_nenhum_erro_de_javascript_na_tela(pagina, base_url, payload):
    """Um ReferenceError dentro do try do loader vira banner, não erro visível.

    Foi assim que três telas ficaram quebradas por meses com um retângulo
    cinza dizendo "leafletPromise is not defined" em letra miúda.
    """
    erros = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    _rotear(pagina, payload)
    pagina.goto(f"{base_url}/static/index.html#mul")
    pagina.wait_for_selector("#view-mul.on", timeout=15000)
    pagina.wait_for_timeout(700)
    assert not erros, f"erro de JS na tela: {erros}"
