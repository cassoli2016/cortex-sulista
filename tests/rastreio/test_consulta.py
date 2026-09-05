# -*- coding: utf-8 -*-
"""O rastreio público: os guards são de SEGURANÇA antes de serem de produto.

Esta é a única tela da casa sem login. Todo o resto é fail-closed — rota
`/api/*` sem mapeamento é 403, e há Cloudflare Access por cima. Aqui a porta
fica aberta de propósito, então o que passa por ela é decidido em código e
cobrado aqui.

O QUE ESTES TESTES IMPEDEM, um a um:

- que a busca funcione com um campo só (o número sequencial do CT-e cairia por
  varredura: 1160750, 1160751, 1160752…);
- que o CNPJ errado devolva a carga de outra pessoa;
- que a página diga a diferença entre "não existe" e "não é sua" — dizer isso
  a transformaria num confirmador de números de CT-e;
- que valor de frete, motorista, documento completo ou coordenada exata
  escapem para o payload público.
"""
from __future__ import annotations

import time

import pytest

from api.rastreio import consulta


REGISTRO = {
    "grupo": 1, "empresa": 1, "filial": 1, "numero": 51283, "serie": 1,
    "dtemissao": "2026-09-01T08:00:00",
    "placa": "AWC2F41",
    "cidadecoleta": "POUSO ALEGRE", "ufcoleta": "MG",
    "dtprevisaoentrega": "2026-09-05T16:00:00",
    "dtentrega": None, "dtagendamentoentrega": None, "dtiniciodescarga": None,
    "destinatario_nome": "CLIENTE EXEMPLO", "destinatario_cidade": "SANTOS",
    "destinatario_uf": "SP",
    # colunas que o ERP tem e que NAO podem vazar
    "valorfrete": 4200.0, "motorista": "FULANO DE TAL",
    "cnpjcpfcodigotomadorservico": "00514820000606",
    "latitudecoleta": -22.2, "longitudecoleta": -45.9,
}


@pytest.fixture
def banco(monkeypatch):
    def _com(linhas):
        monkeypatch.setattr(consulta.db, "query",
                            lambda sql, params=None: list(linhas))
    return _com


@pytest.fixture(autouse=True)
def _freio_limpo():
    consulta._TENTATIVAS.clear()
    yield
    consulta._TENTATIVAS.clear()


# --------------------------------------------------------------------------
# o segundo fator
# --------------------------------------------------------------------------
def test_sem_o_documento_nao_busca(banco):
    banco([REGISTRO])
    assert consulta.buscar("", "0051")["ok"] is False


def test_sem_os_quatro_digitos_do_cnpj_nao_busca(banco):
    """O guard central da varredura. Só o número do CT-e é sequencial: sem o
    segundo campo, um script anda de 1 em 1 e lê a operação inteira."""
    banco([REGISTRO])
    r = consulta.buscar("51283", "")
    assert r["ok"] is False
    assert "CNPJ" in r["motivo"]


def test_cnpj_com_menos_de_quatro_digitos_nao_passa(banco):
    banco([REGISTRO])
    assert consulta.buscar("51283", "005")["ok"] is False


def test_o_cnpj_entra_na_consulta_como_filtro(monkeypatch):
    """Não basta exigir o campo: ele tem de chegar ao SQL. Um teste que só
    cobrasse a validação passaria com o filtro comentado."""
    vistos = []

    def _query(sql, params=None):
        vistos.append(params)
        return []

    monkeypatch.setattr(consulta.db, "query", _query)
    consulta.buscar("51283", "00.51")
    assert vistos, "nenhuma consulta foi feita"
    assert all(p["cnpj4"] == "0051" for p in vistos), (
        "o CNPJ não chegou ao filtro — a busca aceitaria qualquer um")


# --------------------------------------------------------------------------
# o que sai (e o que não sai)
# --------------------------------------------------------------------------
def test_o_payload_publico_NAO_leva_valor_nem_pessoa(banco):
    """A montagem é por lista explícita, não por cópia do registro: copiar
    faria toda coluna nova do ERP entrar na página pública sozinha."""
    banco([REGISTRO])
    carga = consulta.buscar("51283", "0051")["cargas"][0]
    texto = repr(carga).lower()
    for proibido in ("4200", "fulano", "00514820000606", "-22.2", "-45.9",
                     "valorfrete", "motorista", "latitude"):
        assert proibido.lower() not in texto, (
            "%r vazou para o payload público: %r" % (proibido, carga))


def test_a_placa_NAO_sai_no_payload(banco):
    """Placa pintada na porta + posição ao vivo é ferramenta de roubo de
    carga. Ela é usada por dentro para achar a posição, e não sai."""
    banco([REGISTRO])
    carga = consulta.buscar("51283", "0051")["cargas"][0]
    assert "AWC2F41" not in repr(carga)


def test_o_id_da_carga_e_opaco_e_nao_repete_o_documento(banco):
    """URL vaza — em log de proxy, no histórico, no grupo de WhatsApp para
    onde alguém a encaminha. O identificador do detalhe não pode ser o
    documento."""
    banco([REGISTRO])
    carga = consulta.buscar("51283", "0051")["cargas"][0]
    assert "51283" not in carga["id"]
    assert len(carga["id"]) >= 24


def test_o_id_e_ESTAVEL_para_a_mesma_carga(banco):
    banco([REGISTRO])
    a = consulta.buscar("51283", "0051")["cargas"][0]["id"]
    b = consulta.buscar("51283", "0051")["cargas"][0]["id"]
    assert a == b


# --------------------------------------------------------------------------
# o estado da carga
# --------------------------------------------------------------------------
def test_o_estado_vem_do_CAMPO_e_nao_da_ausencia_de_data():
    """'Sem data de entrega' pode ser carga a caminho ou lançamento atrasado.
    A página pública não pode chamar as duas de a mesma coisa."""
    assert consulta._estado({"dtentrega": "2026-09-02"})[0] == "entregue"
    assert consulta._estado({"dtiniciodescarga": "2026-09-02"})[0] == "descarregando"
    assert consulta._estado({"placa": "AAA1A11"})[0] == "em_viagem"
    assert consulta._estado({})[0] == "preparando"


# --------------------------------------------------------------------------
# o freio
# --------------------------------------------------------------------------
def test_o_freio_corta_a_varredura():
    """São 10.000 combinações de quatro dígitos: sem freio, um script tenta
    todas em minutos e o segundo fator deixa de valer."""
    ip = "203.0.113.7"
    livres = sum(1 for _ in range(consulta.FREIO_MAX + 5)
                 if consulta.freio_livre(ip))
    assert livres == consulta.FREIO_MAX


def test_o_freio_e_por_IP():
    for _ in range(consulta.FREIO_MAX + 2):
        consulta.freio_livre("203.0.113.7")
    assert consulta.freio_livre("203.0.113.8") is True


def test_o_freio_solta_depois_da_janela(monkeypatch):
    ip = "203.0.113.9"
    for _ in range(consulta.FREIO_MAX + 2):
        consulta.freio_livre(ip)
    assert consulta.freio_livre(ip) is False
    agora = time.time()
    monkeypatch.setattr(consulta.time, "time",
                        lambda: agora + consulta.FREIO_JANELA_S + 1)
    assert consulta.freio_livre(ip) is True


# --------------------------------------------------------------------------
# a falha
# --------------------------------------------------------------------------
def test_erro_do_ERP_nao_vira_pagina_quebrada(monkeypatch):
    """Página pública não mostra stack trace nem nome de tabela."""
    def _explode(*a, **k):
        raise RuntimeError("relation \"conhecimento\" does not exist")

    monkeypatch.setattr(consulta.db, "query", _explode)
    r = consulta.buscar("51283", "0051")
    assert r["ok"] is False
    assert "conhecimento" not in r["motivo"]


def test_nada_encontrado_devolve_lista_vazia_sem_explicar(banco):
    """A MESMA resposta para 'não existe' e 'não é sua'. Diferenciar as duas
    transformaria a página num confirmador de números de CT-e."""
    banco([])
    r = consulta.buscar("99999999", "0051")
    assert r["ok"] is True and r["cargas"] == [] and r["total"] == 0
    assert "motivo" not in r
