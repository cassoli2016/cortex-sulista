# -*- coding: utf-8 -*-
"""O LINK ASSINADO que o WhatsApp manda — o token e a rota que ele abre.

POR QUE ELE EXISTE. O aviso sai de hora em hora. Sem o link, cada mensagem
terminaria mandando a pessoa abrir a página e redigitar o documento e os quatro
dígitos do CNPJ — e um aviso que dá trabalho a cada hora não é usado, é
silenciado.

POR QUE ELE É SEGURO, e é aqui que estes guards moram. O token é a ÚNICA prova
nesta rota, então ele tem de ser três coisas ao mesmo tempo:

1. **Não forjável.** Assinado com HMAC. Trocar um dígito para espiar a carga do
   vizinho tem de dar em nada.
2. **Com prazo.** Um link encaminhado no grupo da família não pode virar acesso
   permanente à operação de um cliente.
3. **Mudo no erro.** Adulterado, vencido e inexistente respondem igual —
   separar os motivos diria a quem tenta se o palpite chegou perto.

E o token viaja no FRAGMENTO da URL (`#c=`), que não sai do aparelho: não chega
ao servidor nem ao log do proxy. É o mesmo caminho do "esqueci minha senha"
desta casa.
"""
from __future__ import annotations

import time

import pytest

from api import auth
from api.rastreio import consulta, detalhe

CHAVES = (1, 1, 2, 359462, 2)


# --------------------------------------------------------------------------
# o token
# --------------------------------------------------------------------------
def test_o_token_volta_exatamente_a_carga_que_entrou():
    t = consulta.link_token(*CHAVES)
    assert consulta.link_abrir(t) == {"g": 1, "e": 1, "f": 2,
                                      "n": 359462, "s": 2}


def test_token_ADULTERADO_nao_abre_nada():
    """Sem a assinatura, o token seria só o número da carga em base64 — e
    somar um viraria a carga do próximo cliente."""
    t = consulta.link_token(*CHAVES)
    dados, ass = t.split(".")
    for falso in (dados + "." + "0" * len(ass),           # assinatura trocada
                  dados[:-2] + "AA" + "." + ass,          # conteúdo trocado
                  dados,                                  # sem assinatura
                  "", "lixo", "a.b"):
        assert consulta.link_abrir(falso) is None, falso


def test_token_VENCIDO_nao_abre(monkeypatch):
    """O prazo é o que impede o encaminhamento de virar acesso permanente."""
    t = consulta.link_token(*CHAVES)
    assert consulta.link_abrir(t) is not None
    futuro = time.time() + (consulta.LINK_DIAS + 1) * 86400
    monkeypatch.setattr(consulta.time, "time", lambda: futuro)
    assert consulta.link_abrir(t) is None


def test_o_prazo_e_CURTO():
    """Guard sobre um número, não sobre código: quem esticar este prazo para
    meses lê aqui o motivo de ele ser semanas."""
    assert 1 <= consulta.LINK_DIAS <= 45


def test_dois_tokens_de_cargas_diferentes_nao_colidem():
    a = consulta.link_token(1, 1, 2, 359462, 2)
    b = consulta.link_token(1, 1, 2, 359463, 2)
    assert a != b
    assert consulta.link_abrir(a) != consulta.link_abrir(b)


# --------------------------------------------------------------------------
# a rota
# --------------------------------------------------------------------------
def test_a_rota_do_link_e_publica_e_o_resto_continua_fechado():
    assert auth._rota_publica("/api/rastreio/link")
    assert not auth._rota_publica("/api/rastreio/linkx")
    assert not auth._rota_publica("/api/visao-geral")


def test_token_invalido_responde_SEM_CARGA_e_sem_dizer_por_que(monkeypatch):
    """Mesma resposta para adulterado, vencido e inexistente. E sem tocar no
    banco: um token forjado não pode nem gerar consulta."""
    def _nao(*a, **k):
        raise AssertionError("consultou o banco com token invalido")
    monkeypatch.setattr(detalhe.db, "query", _nao)
    for falso in ("", "lixo", "a.b"):
        assert detalhe.por_link(falso) == {"ok": True, "carga": None}


def test_carga_inexistente_responde_igual_a_token_invalido(monkeypatch):
    monkeypatch.setattr(detalhe.db, "query", lambda *a, **k: [])
    t = consulta.link_token(*CHAVES)
    assert detalhe.por_link(t) == {"ok": True, "carga": None}


def test_banco_fora_do_ar_NAO_levanta(monkeypatch):
    """A falha vira recusa legível. Uma exceção aqui viraria 500, e o
    Cloudflare troca o corpo de 5xx pela página dele — a mensagem nunca
    chegaria."""
    def _explode(*a, **k):
        raise RuntimeError("banco caiu")
    monkeypatch.setattr(detalhe.db, "query", _explode)
    r = detalhe.por_link(consulta.link_token(*CHAVES))
    assert r["ok"] is False and r["motivo"]


def test_o_payload_do_link_e_o_MESMO_da_busca(monkeypatch):
    """Os dois caminhos passam por `_montar`. Se alguém montar o payload do
    link à parte, um campo novo do ERP entra na página pública por um lado só,
    sem ninguém decidir — e é o lado que não exige o CNPJ."""
    linha = {"grupo": 1, "empresa": 1, "filial": 2, "numero": 359462,
             "serie": 2, "dtemissao": None, "dtprevisaoentrega": None,
             "dtentrega": None, "dtagendamentoentrega": None,
             "dtiniciodescarga": None, "placa": "AAA1A11",
             "cidadecoleta": "DIADEMA", "ufcoleta": "SP",
             "lat_coleta": None, "lng_coleta": None,
             "lat_entrega": None, "lng_entrega": None,
             "destinatario_nome": "CLIENTE X", "destinatario_cidade": "SANTOS",
             "destinatario_uf": "SP"}
    monkeypatch.setattr(detalhe.db, "query", lambda *a, **k: [linha])
    monkeypatch.setattr(detalhe, "_notas", lambda ch: [])
    monkeypatch.setattr(detalhe, "_andamento", lambda ln: {"tem_posicao": False})
    c = detalhe.por_link(consulta.link_token(*CHAVES))["carga"]
    assert c["documento"] == "CT-e 359462"
    assert c["destino"] == "Santos/SP"
    # A PLACA NÃO ATRAVESSA. `_limpo` monta por lista explícita; se alguém
    # trocar isso por uma cópia do registro, a placa aparece aqui.
    assert "AAA1A11" not in str(c)


# --------------------------------------------------------------------------
# a página
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pagina() -> str:
    from pathlib import Path
    return (Path(auth.__file__).resolve().parent / "static" / "rastreio.html"
            ).read_text(encoding="utf-8")


def test_a_pagina_le_o_FRAGMENTO_e_nao_a_query(pagina):
    assert "location.hash" in pagina
    assert "c=" in pagina and "/api/rastreio/link?t=" in pagina


def test_a_pagina_APAGA_o_token_da_barra_de_enderecos(pagina):
    """O celular que passa de mão em mão, o print da tela e o histórico do
    navegador são três jeitos de o token viajar sozinho."""
    assert "history.replaceState" in pagina
