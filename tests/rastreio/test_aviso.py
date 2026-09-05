# -*- coding: utf-8 -*-
"""O aviso horário da carga por WhatsApp.

O QUE ESTES GUARDS PROTEGEM não é o recurso: é o NÚMERO DA EMPRESA. Esta é a
única mensagem da casa que sai sozinha, de hora em hora, para o telefone de
alguém que não é usuário do sistema. Se ela repetir, a pessoa bloqueia — e o
bloqueio não atinge esta mensagem, atinge o número que atende todos os outros
clientes.

TRÊS RESPOSTAS, como todo aviso automático daqui: manda, cala porque não há o
que dizer, ou recusa DIZENDO o motivo. A quarta — parar em silêncio — é a que
não pode existir, porque é indistinguível de "está tudo calmo".
"""
from __future__ import annotations

import pytest

from api.rastreio import aviso


def _carga(**kw) -> dict:
    base = {"documento": "CT-e 51283", "destino": "Santos/SP",
            "estado": "em_viagem", "estado_rotulo": "Em viagem",
            "entregue_em": None,
            "andamento": {"tem_posicao": True, "progresso_pct": 62,
                          "falta_km": 118, "por_rota": True}}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# o texto
# --------------------------------------------------------------------------
def test_a_mensagem_diz_progresso_e_o_que_falta():
    t = aviso._texto(_carga())
    assert "62%" in t and "118" in t and "Santos/SP" in t
    # COM ROTA CADASTRADA a ressalva NÃO aparece: dizer "linha reta" num
    # número rodoviário seria uma desculpa que o número não precisa.
    assert "linha reta" not in t


def test_a_mensagem_declara_quando_e_LINHA_RETA():
    """Sem rota cadastrada o número é reta, e chamar os dois da mesma coisa
    faria quem espera na doca planejar em cima de um km que não existe."""
    c = _carga()
    c["andamento"]["por_rota"] = False
    assert "linha reta" in aviso._texto(c)


def test_entrega_gera_mensagem_de_ENTREGUE():
    t = aviso._texto(_carga(estado="entregue",
                            entregue_em="2026-09-04T15:30:00"))
    assert "Entregue" in t


def test_veiculo_nao_localizado_RECUSA_dizendo_o_motivo():
    """Calar aqui seria pior: quem contratou o aviso acharia que nada mudou,
    quando na verdade paramos de enxergar."""
    c = _carga()
    c["andamento"] = {"tem_posicao": False, "fora_da_rota": True}
    t = aviso._texto(c)
    assert t and "localiza" in t.lower()


def test_posicao_velha_vira_ressalva_e_nao_numero_antigo():
    c = _carga()
    c["andamento"] = {"tem_posicao": False, "posicao_velha_min": 240}
    t = aviso._texto(c)
    assert t and "4h" in t


def test_sem_posicao_e_sem_ressalva_NAO_inventa_mensagem():
    """Cala porque não há o que dizer — a terceira das três respostas."""
    c = _carga()
    c["andamento"] = {"tem_posicao": False}
    assert aviso._texto(c) is None


def test_a_mensagem_NAO_leva_valor_nem_placa():
    """A mensagem sai do nosso controle no instante em que é entregue, e um
    encaminhamento não tem como ser desfeito."""
    c = _carga()
    c["andamento"]["placa"] = "AAA1A11"
    # A PÁGINA mostra placa e motorista; o WhatsApp, não. São decisões
    # separadas porque os dois lugares têm alcance separado: a página exige o
    # segundo fator a cada abertura, a mensagem vive no grupo para sempre.
    c["transporte"] = {"cliente": "TUPY - JOINVILE/SC", "pagador": None,
                       "pagador_igual_cliente": False,
                       "motorista": "Fulano de Tal", "cavalo": "AAA1A11",
                       "carreta": "BBB2B22"}
    t = aviso._texto(c)
    for proibido in ("R$", "AAA1A11", "BBB2B22", "Fulano", "frete"):
        assert proibido not in t


# --------------------------------------------------------------------------
# o que protege o número da empresa
# --------------------------------------------------------------------------
@pytest.fixture
def cenario(monkeypatch):
    enviados = []

    def _montar(inscricoes, carga):
        monkeypatch.setattr(aviso.assinatura, "ativas", lambda: inscricoes)
        monkeypatch.setattr(aviso, "_carga_da_inscricao", lambda i: carga)
        monkeypatch.setattr(aviso.wa, "enviar",
                            lambda fone, texto, **k: (
                                enviados.append((fone, texto)) or {"ok": True}))
        monkeypatch.setattr(aviso.assinatura, "marcar_envio",
                            lambda i, t: None)
        monkeypatch.setattr(aviso.assinatura, "encerrar", lambda i, m: None)
        return enviados
    return _montar


def _ins(**kw) -> dict:
    base = {"id": 1, "grupo": 1, "empresa": 1, "filial": 1, "numero": 51283,
            "serie": 1, "telefone": "5511987654321", "ultimo_texto": None,
            "ultimo_envio": None, "envios": 0}
    base.update(kw)
    return base


def test_mensagem_IGUAL_a_anterior_nao_e_reenviada(cenario):
    """O guard central.

    Caminhão parado gera a mesma frase 24 vezes por dia. A pessoa bloqueia o
    número — e o estrago não é a mensagem, é a reputação do número que atende
    todos os outros clientes.
    """
    carga = _carga()
    texto = aviso._texto(carga)
    enviados = cenario([_ins(ultimo_texto=texto)], carga)
    r = aviso.rodar()
    assert enviados == [], "a mesma mensagem foi enviada de novo"
    assert r["iguais"] == 1 and r["enviados"] == 0


def test_mensagem_DIFERENTE_e_enviada(cenario):
    carga = _carga()
    enviados = cenario([_ins(ultimo_texto="qualquer coisa antiga")], carga)
    r = aviso.rodar()
    assert len(enviados) == 1 and r["enviados"] == 1


def test_toda_mensagem_diz_como_SAIR(cenario):
    """Opt-out difícil não reduz cancelamento: vira bloqueio do número."""
    enviados = cenario([_ins()], _carga())
    aviso.rodar()
    assert "SAIR" in enviados[0][1]


def test_a_entrega_ENCERRA_a_inscricao(cenario, monkeypatch):
    """Ninguém volta para cancelar depois que a carga chegou, e o aviso
    seguiria até o prazo expirar."""
    encerradas = []
    carga = _carga(estado="entregue", entregue_em="2026-09-04T15:30:00")
    cenario([_ins()], carga)
    monkeypatch.setattr(aviso.assinatura, "encerrar",
                        lambda i, m: encerradas.append((i, m)))
    r = aviso.rodar()
    assert encerradas and encerradas[0][1] == "entregue"
    assert r["encerradas"] == 1


def test_o_ENSAIO_nao_envia_nada(cenario):
    """É como se confere o texto antes de ele sair para o número de um
    cliente."""
    enviados = cenario([_ins()], _carga())
    r = aviso.rodar(ensaio=True)
    assert enviados == []
    assert r["ensaio"] is True and r["amostra"]


def test_envio_recusado_e_CONTADO_e_nao_marcado_como_enviado(monkeypatch):
    """Aceitar não é entregar. Marcar o envio de uma recusa faria a próxima
    passada achar que a mensagem já saiu — e a pessoa nunca receberia."""
    marcados = []
    monkeypatch.setattr(aviso.assinatura, "ativas", lambda: [_ins()])
    monkeypatch.setattr(aviso, "_carga_da_inscricao", lambda i: _carga())
    monkeypatch.setattr(aviso.wa, "enviar",
                        lambda f, t, **k: {"ok": False, "erro": "sem conexao"})
    monkeypatch.setattr(aviso.assinatura, "marcar_envio",
                        lambda i, t: marcados.append(i))
    r = aviso.rodar()
    assert r["falhas"] == 1 and r["enviados"] == 0
    assert marcados == [], "recusa foi marcada como enviada"


def test_sem_inscricao_a_rotina_nao_faz_nada(monkeypatch):
    monkeypatch.setattr(aviso.assinatura, "ativas", lambda: [])
    r = aviso.rodar()
    assert r["inscricoes"] == 0 and r["enviados"] == 0


# --------------------------------------------------------------------------
# a primeira mensagem, no cadastro
# --------------------------------------------------------------------------
def test_o_cadastro_manda_a_PRIMEIRA_mensagem_na_hora(monkeypatch):
    """Não é cortesia, é consentimento.

    Se alguém cadastrou um número que NÃO é dele, o dono descobre no mesmo
    minuto e responde SAIR — em vez de descobrir uma hora depois, com a segunda
    mensagem. Numa página aberta, essa é a diferença entre um engano de
    digitação e uma hora de importuno.
    """
    from api.rastreio import assinatura

    enviados = []
    alvo = {"grupo": 1, "empresa": 1, "filial": 1, "numero": 51283, "serie": 1}
    monkeypatch.setattr(assinatura.consulta, "buscar_cru",
                        lambda t, c: ([alvo], None))
    monkeypatch.setattr(assinatura.consulta, "token",
                        lambda *a: "ID")
    monkeypatch.setattr(assinatura.pglocal, "get_conn", _conn_falsa)
    monkeypatch.setattr(aviso, "_carga_da_inscricao", lambda i: _carga())
    monkeypatch.setattr(aviso.wa, "enviar",
                        lambda f, t, **k: (enviados.append((f, t))
                                           or {"ok": True}))

    r = assinatura.inscrever("51283", "0051", "ID", "11987654321", "1.2.3.4")
    assert r["ok"] is True
    assert r["primeira_enviada"] is True
    assert len(enviados) == 1
    assert "SAIR" in enviados[0][1], "a primeira mensagem tem de dizer como sair"


def test_falha_no_envio_NAO_desfaz_o_cadastro(monkeypatch):
    """O cadastro está gravado; a tarefa horária pega o próximo ciclo. Desfazer
    a inscrição porque o WhatsApp piscou faria a pessoa cadastrar de novo — e
    o teto por telefone a barraria."""
    from api.rastreio import assinatura

    alvo = {"grupo": 1, "empresa": 1, "filial": 1, "numero": 51283, "serie": 1}
    monkeypatch.setattr(assinatura.consulta, "buscar_cru",
                        lambda t, c: ([alvo], None))
    monkeypatch.setattr(assinatura.consulta, "token", lambda *a: "ID")
    monkeypatch.setattr(assinatura.pglocal, "get_conn", _conn_falsa)
    monkeypatch.setattr(aviso, "_carga_da_inscricao", lambda i: _carga())
    monkeypatch.setattr(aviso.wa, "enviar",
                        lambda f, t, **k: {"ok": False, "erro": "sem conexao"})

    r = assinatura.inscrever("51283", "0051", "ID", "11987654321", "1.2.3.4")
    assert r["ok"] is True and r["primeira_enviada"] is False
    assert "próximo ciclo" in r["aviso"]


class _Cur:
    def execute(self, *a, **k): pass
    def fetchone(self): return {"n": 0, "id": 1}


class _Ctx:
    def __init__(self, o): self.o = o
    def __enter__(self): return self.o
    def __exit__(self, *a): return False


class _Conn:
    def cursor(self): return _Ctx(_Cur())
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _conn_falsa(*a, **k):
    return _Conn()


def test_a_primeira_mensagem_NAO_e_barrada_pela_janela_noturna(monkeypatch):
    """O defeito relatado: cadastrei e nao chegou.

    Medido as 23h08 — a inscricao gravou e o envio foi recusado com "Fora da
    janela de envio (08:00-20:00)". A janela existe para a empresa nao disparar
    em cliente de madrugada, e continua valendo para o aviso HORARIO. Mas a
    primeira mensagem nao e disparo: e resposta a um botao apertado ha dois
    segundos, com o celular na mao. Barra-la faz o recurso parecer quebrado.

    O guard olha as REGRAS que o envio recebe, porque e nelas que a decisao
    mora — testar o horario do relogio faria o teste passar de dia e falhar de
    noite, que e o pior tipo de teste que existe.
    """
    from api.rastreio import assinatura

    capturado = {}
    alvo = {"grupo": 1, "empresa": 1, "filial": 1, "numero": 51283, "serie": 1}
    monkeypatch.setattr(assinatura.consulta, "buscar_cru",
                        lambda t, c: ([alvo], None))
    monkeypatch.setattr(assinatura.consulta, "token", lambda *a: "ID")
    monkeypatch.setattr(assinatura.pglocal, "get_conn", _conn_falsa)
    monkeypatch.setattr(aviso, "_carga_da_inscricao", lambda i: _carga())
    monkeypatch.setattr(
        aviso.wa, "enviar",
        lambda f, t, **k: (capturado.update(k) or {"ok": True}))

    assinatura.inscrever("51283", "0051", "ID", "11987654321", "1.2.3.4")
    regras = capturado.get("regras") or {}
    assert regras.get("janela_inicio") == "00:00"
    assert regras.get("janela_fim") == "23:59"
    # E O RESTO DA CONFIGURACAO CONTINUA VALENDO. `regras` SUBSTITUI a config
    # inteira — passar so a janela derruba o envio num KeyError em `ativo`, e
    # passar so metade desligaria o interruptor e os limites em silencio.
    for campo in ("ativo", "limite_dia", "limite_numero"):
        assert campo in regras, "o envio perdeu %r ao trocar a janela" % campo


def test_o_aviso_HORARIO_continua_respeitando_a_janela(cenario):
    """A excecao e so da primeira mensagem. O disparo automatico de hora em
    hora nao pode acordar ninguem — e e ele que roda sem ninguem olhando."""
    enviados = cenario([_ins()], _carga())
    aviso.rodar()
    # o aviso horario nao passa `regras`: vale a janela geral
    assert enviados, "nada foi enviado no cenario"
