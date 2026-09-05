# -*- coding: utf-8 -*-
"""O endereço público do CÓRTEX — uma fonte só.

O GUARD DE UM DEFEITO QUE JÁ SAIU PARA UM CELULAR. O domínio mudou de
`cortex.cassolitech.com.br` para `cortex.sulista.com.br`, e no dia seguinte a
mesma pessoa recebeu, no mesmo WhatsApp e com dez minutos de diferença, o resumo
diário com o domínio VELHO e o aviso de carga com o novo. O rastreio tinha sido
feito configurável; o resumo diário e o aviso do suporte tinham a constante
cravada, cada um no seu arquivo.

Desta vez foi inofensivo — os dois domínios ainda respondem. No dia em que o
antigo for desligado, o link simplesmente para de abrir no celular de quem não
tem como saber por quê, e ninguém aqui fica sabendo.
"""
from __future__ import annotations

import pathlib

import pytest

from api import url_publica


@pytest.fixture(autouse=True)
def sem_variavel(monkeypatch):
    for nome in url_publica.VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)


def test_o_padrao_e_o_dominio_da_empresa():
    assert url_publica.base() == "https://cortex.sulista.com.br"
    assert not url_publica.base().endswith("/")


def test_a_variavel_de_ambiente_manda(monkeypatch):
    """Configurável não é firula: este endereço já mudou uma vez, e um domínio
    cravado no código vai junto na mensagem de todo cliente até alguém
    reparar."""
    monkeypatch.setenv("CORTEX_URL_BASE", "https://outro.exemplo.com/")
    assert url_publica.base() == "https://outro.exemplo.com"


def test_a_variavel_ANTIGA_continua_valendo(monkeypatch):
    """`RASTREIO_URL_BASE` nasceu antes deste módulo e pode estar num `.env` de
    produção. Ignorá-la faria a unificação MUDAR o endereço de quem já tinha
    configurado — o oposto do que ela veio consertar."""
    monkeypatch.setenv("RASTREIO_URL_BASE", "https://legado.exemplo.com")
    assert url_publica.base() == "https://legado.exemplo.com"


def test_a_variavel_nova_vence_a_antiga(monkeypatch):
    monkeypatch.setenv("RASTREIO_URL_BASE", "https://legado.exemplo.com")
    monkeypatch.setenv("CORTEX_URL_BASE", "https://nova.exemplo.com")
    assert url_publica.base() == "https://nova.exemplo.com"


def test_o_link_de_tela_usa_HASH_e_nao_query():
    """O roteador da casa é por hash — e o que vem depois do `#` não chega ao
    servidor nem ao log do proxy."""
    u = url_publica.tela("sup", chamado=42)
    assert u == "https://cortex.sulista.com.br/#sup?chamado=42"
    assert url_publica.tela("dre") == "https://cortex.sulista.com.br/#dre"


def test_parametro_NULO_nao_vira_a_palavra_None():
    assert "None" not in url_publica.tela("sup", chamado=None)


# --------------------------------------------------------------------------
# ninguém mais crava o endereço
# --------------------------------------------------------------------------
def test_NENHUM_modulo_crava_o_dominio_de_novo():
    """O guard que impede a próxima cópia.

    Ele varre o código de verdade, não uma lista mantida à mão: qualquer
    arquivo novo que escrever o endereço em vez de pedir a `url_publica`
    aparece aqui. Comentário e docstring podem citar o domínio — é o valor em
    código que não pode.
    """
    raiz = pathlib.Path(url_publica.__file__).resolve().parent
    culpados = []
    for f in list(raiz.rglob("*.py")) + list(raiz.rglob("*.html")):
        if f.name == "url_publica.py":
            continue
        for n, linha in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            nu = linha.strip()
            if nu.startswith("#") or nu.startswith("*") or nu.startswith("--"):
                continue
            if "cortex.cassolitech.com.br" in linha or \
               '"https://cortex.sulista.com.br"' in linha:
                culpados.append("%s:%d" % (f.relative_to(raiz.parent), n))
    assert not culpados, ("endereço cravado em vez de `url_publica.base()`: %s"
                          % culpados)


def test_o_rastreio_usa_a_MESMA_fonte(monkeypatch):
    """As duas mensagens que saem para o telefone de um cliente — o aviso de
    carga e o resumo diário — têm de apontar para o mesmo lugar."""
    from api.rastreio import mensagem
    monkeypatch.setenv("CORTEX_URL_BASE", "https://x.exemplo.com")
    assert mensagem.base() == url_publica.base() == "https://x.exemplo.com"
