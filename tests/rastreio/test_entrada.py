# -*- coding: utf-8 -*-
"""O webhook de entrada do WhatsApp — a palavra SAIR.

POR QUE ELE EXISTE. Toda mensagem do rastreio termina com "Para parar de
receber, responda SAIR". Prometer e não atender é pior que não prometer: quem
responde e continua recebendo não tenta de novo — bloqueia o número. E o
bloqueio não atinge esta mensagem, atinge o número que fala com todos os outros
clientes.

O QUE ESTES GUARDS PROTEGEM. Esta é uma rota pública que qualquer um pode
postar. Os testes cobram as três contenções: a única ação possível é
descadastrar, só se responde a quem tinha inscrição (senão o webhook vira
amplificador de mensagem), e nada além de SAIR gera resposta.
"""
from __future__ import annotations

import pytest

from api.rastreio import entrada


@pytest.fixture
def cenario(monkeypatch):
    estado = {"cancelados": [], "enviados": []}

    def _montar(quantas=1):
        monkeypatch.setattr(
            entrada.assinatura, "cancelar_por_telefone",
            lambda f: (estado["cancelados"].append(f) or quantas))
        monkeypatch.setattr(
            entrada.wa, "enviar",
            lambda f, t, **k: (estado["enviados"].append((f, t))
                               or {"ok": True}))
        return estado
    return _montar


def _msg(texto="SAIR", fone="5511987654321", **kw):
    base = {"phone": fone, "text": {"message": texto}}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# o caminho feliz
# --------------------------------------------------------------------------
def test_SAIR_cancela_e_confirma(cenario):
    e = cenario(quantas=2)
    r = entrada.receber(_msg("SAIR"))
    assert r["acao"] == "cancelado" and r["inscricoes"] == 2
    assert e["cancelados"] == ["5511987654321"]
    assert len(e["enviados"]) == 1


def test_o_pedido_de_saida_e_reconhecido_com_folga(cenario):
    """Gente escreve de todo jeito. Ser generoso aqui custa nada; ser restrito
    custa a reputação do número, porque quem pediu para sair e continua
    recebendo bloqueia."""
    for texto in ("sair", "SAIR.", "Sair, por favor", "PARAR", "cancelar",
                  "  stop  ", "descadastrar"):
        e = cenario()
        assert entrada.receber(_msg(texto))["acao"] == "cancelado", texto


# --------------------------------------------------------------------------
# o que NÃO gera resposta
# --------------------------------------------------------------------------
def test_mensagem_qualquer_NAO_vira_conversa(cenario):
    """Um 'obrigado' do cliente não pode acionar robô. Responder a tudo
    transformaria o número da empresa num atendente automático que ninguém
    pediu."""
    e = cenario()
    for texto in ("obrigado", "e a minha carga?", "bom dia", "ok"):
        r = entrada.receber(_msg(texto))
        assert r["acao"] == "ignorado", texto
    assert e["enviados"] == []


def test_quem_NAO_tinha_inscricao_nao_recebe_resposta(cenario):
    """O guard do amplificador.

    Sem ele, qualquer POST com um telefone qualquer faria a casa mandar
    mensagem para ele — um webhook aberto virando disparador.
    """
    e = cenario(quantas=0)
    r = entrada.receber(_msg("SAIR", fone="5511900000000"))
    assert r["acao"] == "sem_inscricao"
    assert e["enviados"] == [], "respondeu a quem nunca se inscreveu"


def test_a_nossa_propria_mensagem_nao_e_lida_como_entrada(cenario):
    """A confirmação de saída volta no webhook. Sem este corte, ela seria lida
    como uma nova mensagem de entrada."""
    e = cenario()
    assert entrada.receber(_msg("SAIR", fromMe=True))["acao"] == "ignorado"
    assert e["enviados"] == []


def test_grupo_nao_dispara_nada(cenario):
    e = cenario()
    assert entrada.receber(_msg("SAIR", isGroup=True))["acao"] == "ignorado"
    assert e["enviados"] == []


# --------------------------------------------------------------------------
# o corpo que a Z-API manda
# --------------------------------------------------------------------------
def test_le_o_texto_em_varios_formatos(cenario):
    """Os nomes dos campos variam entre versões da API deles. Ler um só
    faria o SAIR parar de funcionar numa atualização do fornecedor — em
    silêncio, porque a mensagem continuaria chegando."""
    for corpo in ({"phone": "5511987654321", "text": {"message": "SAIR"}},
                  {"phone": "5511987654321", "text": "SAIR"},
                  {"phone": "5511987654321", "body": "SAIR"},
                  {"from": "5511987654321", "message": "SAIR"}):
        cenario()
        assert entrada.receber(corpo)["acao"] == "cancelado", corpo


def test_corpo_incompleto_DESISTE_declarando(cenario):
    """Um `KeyError` aqui viraria HTTP 500, e a Z-API leria isso como falha de
    entrega e reenfileiraria a mesma mensagem."""
    cenario()
    for corpo in ({}, {"phone": "5511987654321"}, {"text": {"message": "SAIR"}}):
        assert entrada.receber(corpo)["acao"] == "sem_dados"


def test_telefone_invalido_nao_quebra(cenario):
    cenario()
    assert entrada.receber(_msg("SAIR", fone="123"))["acao"] == "telefone_invalido"


# --------------------------------------------------------------------------
# o segredo opcional
# --------------------------------------------------------------------------
def test_sem_segredo_configurado_o_webhook_funciona(cenario, monkeypatch):
    """Uma integração que só funciona depois de um segredo que ninguém sabe
    que existe é uma integração quebrada em silêncio — e o silêncio, aqui, é o
    defeito."""
    monkeypatch.delenv("RASTREIO_ZAP_TOKEN", raising=False)
    cenario()
    assert entrada.receber(_msg("SAIR"))["acao"] == "cancelado"


def test_com_segredo_configurado_ele_passa_a_ser_exigido(cenario, monkeypatch):
    monkeypatch.setenv("RASTREIO_ZAP_TOKEN", "s3gr3d0")
    e = cenario()
    assert entrada.receber(_msg("SAIR"))["acao"] == "ignorado"
    assert entrada.receber(_msg("SAIR"), token="errado")["acao"] == "ignorado"
    assert entrada.receber(_msg("SAIR"), token="s3gr3d0")["acao"] == "cancelado"
    assert len(e["enviados"]) == 1


# --------------------------------------------------------------------------
# a janela — e a lição que não foi generalizada da primeira vez
# --------------------------------------------------------------------------
def test_a_confirmacao_de_SAIR_NAO_e_barrada_pela_janela_noturna(monkeypatch):
    """O guard que faltava, e que custou um teste real com o SAIR sem resposta.

    A janela (08:00–20:00) existe para a empresa não DISPARAR mensagem em
    cliente de madrugada, e continua valendo para o aviso de hora em hora. Mas
    a confirmação de saída não é disparo: é resposta a uma palavra que a pessoa
    acabou de escrever. Barrada, ela cancela em silêncio — e quem pede para
    sair e não recebe nada não tenta de novo: bloqueia o número, que é o número
    que fala com todos os outros clientes.

    A MESMA LIÇÃO já tinha sido aprendida na primeira mensagem do cadastro, às
    23h08, e foi consertada só lá. Este teste existe porque generalizar custava
    dois minutos e não foi feito.
    """
    vistos = {}

    monkeypatch.setattr(entrada.assinatura, "cancelar_por_telefone",
                        lambda f: 1)
    monkeypatch.setattr(entrada.wa, "enviar",
                        lambda f, t, **k: (vistos.update(k) or {"ok": True}))
    assert entrada.receber(_msg("SAIR"))["acao"] == "cancelado"

    regras = vistos.get("regras") or {}
    assert regras.get("janela_inicio") == "00:00"
    assert regras.get("janela_fim") == "23:59"
    # `regras` SUBSTITUI a configuração inteira, não remenda: passar só a
    # janela derruba o envio num KeyError em `ativo`.
    for campo in ("ativo", "limite_dia", "intervalo_seg"):
        assert campo in regras, "o envio perdeu %r ao trocar a janela" % campo


def test_a_resposta_imediata_NAO_fura_o_interruptor_geral():
    """Janela aberta não é passe livre. Se a casa desligou o WhatsApp, nem a
    resposta imediata sai — senão o interruptor geral deixaria de valer
    justamente pelo caminho que ninguém está olhando."""
    from api.whatsapp import resposta
    r = resposta.regras()
    from api.whatsapp import config as cfg
    assert r["ativo"] == cfg.ler()["ativo"]
    assert r["limite_dia"] == cfg.ler()["limite_dia"]


# --------------------------------------------------------------------------
# o nono dígito — o que fazia o SAIR "não funcionar"
# --------------------------------------------------------------------------
def test_SAIR_do_numero_SEM_o_nono_digito_cancela_o_mesmo(monkeypatch):
    """O guard do defeito que custou uma manhã inteira de diagnóstico.

    O nono dígito entrou nos celulares brasileiros em 2012, mas o identificador
    que o WhatsApp guarda para uma conta antiga pode continuar sem ele. A mesma
    pessoa é `5541984251704` quando digita o número na página e `554184251704`
    quando responde a mensagem.

    O sintoma foi cruel: o SAIR CHEGAVA, era processado, e o banco não achava
    inscrição nenhuma. De fora, "o SAIR não funciona"; de dentro, silêncio — e
    a pessoa que pede para sair e continua recebendo bloqueia o número.
    """
    from api.rastreio import assinatura

    guardado = "5541984251704"          # como a página gravou
    baixados = []

    def _executar(sql, params=None):
        formas = params[0]
        baixados.extend([f for f in formas if f == guardado])
        return len(baixados)

    monkeypatch.setattr(assinatura.pglocal, "executar", _executar)
    monkeypatch.setattr(entrada.wa, "enviar", lambda f, t, **k: {"ok": True})

    # a Z-API manda SEM o nono
    r = entrada.receber(_msg("SAIR", fone="554184251704"))
    assert r["acao"] == "cancelado", "o número sem o nono dígito não casou"
    assert guardado in baixados


def test_a_busca_aceita_as_duas_formas_mas_o_ENVIO_usa_UMA(monkeypatch):
    """Procurar tem de achar as duas; mandar tem de escolher uma. Enviar para
    as duas formas entregaria a mesma mensagem duas vezes para a mesma
    pessoa."""
    from api.whatsapp import numeros
    from api.rastreio import assinatura

    formas = numeros.variantes("554184251704")
    assert len(formas) == 2 and formas[0] == numeros.normalizar("554184251704")

    enviados = []
    monkeypatch.setattr(assinatura.pglocal, "executar", lambda *a, **k: 1)
    monkeypatch.setattr(entrada.wa, "enviar",
                        lambda f, t, **k: (enviados.append(f) or {"ok": True}))
    entrada.receber(_msg("SAIR", fone="554184251704"))
    assert len(enviados) == 1, "respondeu para as duas formas do mesmo número"
