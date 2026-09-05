# -*- coding: utf-8 -*-
"""CARGAS — a pessoa pergunta o que está acompanhando.

POR QUE NO WHATSAPP E NÃO NA PÁGINA, que é onde ela foi pedida. A página é
pública e não sabe quem está do outro lado; um campo "digite seu telefone e
veja suas cargas" transformaria a tela num consultor de quem-acompanha-o-quê —
bastaria ter o número de alguém. No WhatsApp a prova de identidade é a própria
mensagem: só quem tem o aparelho manda dele.

E POR QUE ELA PRECISAVA EXISTIR: sem uma lista sob demanda, o único lugar com
os números das cargas era a última mensagem horária. Quem quisesse sair de UMA
à noite teria de rolar a conversa para trás até achá-la — e esse atrito é
exatamente o que faz a pessoa mandar o SAIR seco e sumir de todas.
"""
from __future__ import annotations

import pytest

from api.rastreio import entrada, mensagem


def _carga(doc, pct=50):
    return {"documento": "CT-e %s" % doc, "origem": "Joinville/SC",
            "destino": "Santos/SP", "estado": "em_viagem", "entregue_em": None,
            "link_token": "tok%s" % doc,
            "andamento": {"tem_posicao": True, "progresso_pct": pct,
                          "falta_km": 120, "km_rota": 300, "por_rota": True}}


def _ins(ident, numero):
    return {"id": ident, "grupo": 1, "empresa": 1, "filial": 2,
            "numero": numero, "serie": 1, "telefone": "5541984251704"}


@pytest.fixture
def cenario(monkeypatch):
    estado = {"enviados": []}

    def _montar(inscricoes, cargas=None):
        cargas = cargas or {}
        monkeypatch.setattr(entrada.assinatura, "listar_por_telefone",
                            lambda f: inscricoes)
        monkeypatch.setattr(entrada.wa, "enviar",
                            lambda f, t, **k: (estado["enviados"].append(t)
                                               or {"ok": True}))
        from api.rastreio import aviso
        monkeypatch.setattr(aviso, "_carga_da_inscricao",
                            lambda ins: cargas.get(ins["id"]))
        return estado
    return _montar


def _msg(texto, fone="5541984251704"):
    return {"phone": fone, "text": {"message": texto}}


# --------------------------------------------------------------------------
# a resposta
# --------------------------------------------------------------------------
def test_CARGAS_lista_o_que_a_pessoa_acompanha(cenario):
    e = cenario([_ins(1, 111), _ins(2, 222)],
                {1: _carga("111"), 2: _carga("222")})
    r = entrada.receber(_msg("CARGAS"))
    assert r["acao"] == "lista" and r["cargas"] == 2
    texto = e["enviados"][0]
    assert "CT-e 111" in texto and "CT-e 222" in texto
    # e ENSINA a sair de uma, que é para isso que a pessoa pediu a lista
    assert "SAIR 111" in texto


def test_a_pessoa_pergunta_de_varios_jeitos(cenario):
    """Ser generoso custa nada; quem pergunta e não é entendido não pergunta
    de novo."""
    for texto in ("CARGAS", "cargas", "minhas cargas", "Lista", "status",
                  "acompanhando", "listar"):
        e = cenario([_ins(1, 111)], {1: _carga("111")})
        assert entrada.receber(_msg(texto))["acao"] in ("lista", "lista_vazia"), texto


def test_quem_NAO_acompanha_nada_recebe_resposta_dizendo_isso(cenario):
    """Silêncio aqui pareceria defeito. É diferente do aviso automático, onde
    calar é a resposta certa: aqui alguém PERGUNTOU."""
    e = cenario([])
    r = entrada.receber(_msg("CARGAS"))
    assert r["acao"] == "lista_vazia"
    assert e["enviados"] and "nenhuma carga" in e["enviados"][0]


def test_inscricao_sem_posicao_ainda_gera_RESPOSTA(cenario):
    """Duas coisas diferentes: não ter inscrição e não ter novidade. A segunda
    ainda merece resposta — quem perguntou está esperando uma."""
    e = cenario([_ins(1, 111)], {})     # inscrita, mas o ERP não devolveu nada
    r = entrada.receber(_msg("CARGAS"))
    assert r["acao"] == "lista"
    assert "1 carga" in e["enviados"][0]


# --------------------------------------------------------------------------
# CARGAS não é SAIR
# --------------------------------------------------------------------------
def test_CARGAS_nao_cancela_nada(cenario, monkeypatch):
    """O pior desfecho possível deste comando seria descadastrar quem só quis
    olhar."""
    def _nao(*a, **k):
        raise AssertionError("CARGAS cancelou inscrição")
    monkeypatch.setattr(entrada.assinatura, "cancelar_por_telefone", _nao)
    cenario([_ins(1, 111)], {1: _carga("111")})
    assert entrada.receber(_msg("CARGAS"))["acao"] == "lista"


def test_CANCELAR_continua_sendo_saida_e_nao_listagem(cenario, monkeypatch):
    """"cancelar" casa nas duas expressões. Quem escreve isso quer sair."""
    chamou = []
    monkeypatch.setattr(entrada.assinatura, "cancelar_por_telefone",
                        lambda f, numero=None: (chamou.append(numero) or 1))
    cenario([_ins(1, 111)], {1: _carga("111")})
    assert entrada.receber(_msg("cancelar"))["acao"] == "cancelado"
    assert chamou == [None]


# --------------------------------------------------------------------------
# o rodapé ensina o comando
# --------------------------------------------------------------------------
def test_o_rodape_DIZ_que_CARGAS_existe():
    """Comando que ninguém sabe que existe não existe — e o custo de descobrir
    sozinho é a pessoa mandar SAIR e sumir de todas."""
    r = mensagem.rodape(3, "94537")
    assert "CARGAS" in r and "SAIR 94537" in r


def test_com_UMA_carga_o_rodape_continua_simples():
    """Ensinar dois comandos a quem acompanha uma só é ruído: ali SAIR resolve
    tudo."""
    assert mensagem.rodape(1) == mensagem.RODAPE
    assert "CARGAS" not in mensagem.RODAPE
