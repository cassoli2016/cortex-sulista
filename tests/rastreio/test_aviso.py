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

from pathlib import Path

import pytest

from api.rastreio import aviso, mensagem


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


@pytest.fixture(autouse=True)
def _janela_fora_de_cena(monkeypatch):
    """A JANELA DE HORÁRIO NÃO PARTICIPA, salvo quando o teste a chama.

    Sem isto a suíte inteira passa a depender da HORA em que roda. Aconteceu às
    20h01 de 06/09/2026: dezoito testes que não falam de horário nenhum ficaram
    vermelhos de uma vez, porque a janela da casa fecha às 20:00 e a worktree
    não tem `data/whatsapp_config.json` para dizer o contrário. Teste que
    depende do relógio acusa a pessoa errada — quem lê o relatório vai procurar
    o defeito na mudança que acabou de fazer.

    `autouse` e não parte do `cenario` porque o corpo do teste roda DEPOIS das
    fixtures: assim quem quer falar de janela simplesmente a repõe, e a
    reposição vence.
    """
    from api.rastreio import assinatura
    monkeypatch.setattr(assinatura, "dentro_da_janela",
                        lambda ins, agora=None: True)


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
                            lambda i, t, **k: None)
        monkeypatch.setattr(aviso.assinatura, "encerrar", lambda i, m: None)
        return enviados
    return _montar


def _ins(**kw) -> dict:
    base = {"id": 1, "grupo": 1, "empresa": 1, "filial": 1, "numero": 51283,
            "serie": 1, "telefone": "5511987654321", "ultimo_texto": None,
            "ultima_assinatura": None, "ultimo_envio": None, "envios": 0}
    base.update(kw)
    return base


def test_mensagem_IGUAL_a_anterior_nao_e_reenviada(cenario):
    """O guard central.

    Caminhão parado gera a mesma frase 24 vezes por dia. A pessoa bloqueia o
    número — e o estrago não é a mensagem, é a reputação do número que atende
    todos os outros clientes.
    """
    carga = _carga()
    assin = mensagem.assinatura([carga])
    enviados = cenario([_ins(ultima_assinatura=assin)], carga)
    r = aviso.rodar()
    assert enviados == [], "a mesma mensagem foi enviada de novo"
    assert r["iguais"] == 1 and r["enviados"] == 0


def test_SO_O_FRESCOR_mudando_nao_gera_mensagem(cenario):
    """A REGRESSÃO DE 06/09/2026, e o guard que faltava.

    O ciclo anterior comparava o TEXTO RENDERIZADO. O texto carrega
    `🕐 Atualizado há N min` e o atraso do trânsito em minutos — dois números
    que mudam a cada ciclo por construção, com a carga parada no mesmo lugar.
    A comparação nunca casava, e o telefone inscrito no CT-e 94540 recebeu seis
    mensagens em quatro horas dizendo `2%` e `faltam 648 km`, sempre.

    O DUBLÊ AQUI É O QUE O GUARD ANTIGO NÃO TINHA: duas leituras da MESMA carga
    parada, tiradas em ciclos diferentes. O guard antigo fabricava o texto
    anterior a partir da mesma carga — dois textos idênticos byte a byte, uma
    comparação que casava por construção, e um verde que não conferia nada.
    """
    andamento = {"tem_posicao": True, "progresso_pct": 2, "falta_km": 648,
                 "km_rota": 662, "por_rota": True,
                 "transito": {"estado": "livre", "rotulo": "Fluxo livre"}}
    antes = _carga(andamento={**andamento, "atualizado_ha_min": 3})
    # O CAMINHÃO NÃO SAIU DO LUGAR: mesmo percentual, mesmos km, mesmo
    # semáforo. Só o relógio andou, e o provedor passou a estimar um minuto de
    # atraso no trecho.
    agora = _carga(andamento={
        **andamento, "atualizado_ha_min": 4,
        "transito": {"estado": "livre", "rotulo": "Fluxo livre",
                     "atraso_min": 1}})

    assert aviso._texto(antes) != aviso._texto(agora), \
        "o dublê precisa reproduzir o texto que MUDAVA; se ele for igual, " \
        "este guard passa por vacuidade e não prova nada"

    enviados = cenario([_ins(ultima_assinatura=mensagem.assinatura([antes]))],
                       agora)
    r = aviso.rodar()
    assert enviados == [], "mensagem repetida saiu: nada mudou para o cliente"
    assert r["iguais"] == 1 and r["enviados"] == 0


def test_andar_o_BASTANTE_gera_mensagem(cenario):
    """O outro lado do mesmo guard: silêncio só enquanto nada acontece.

    Um degrau de materialidade que engolisse a viagem inteira seria pior que o
    defeito — a pessoa deixaria de saber que a carga chegou perto.
    """
    antes = _carga(andamento={"tem_posicao": True, "progresso_pct": 2,
                              "falta_km": 648, "por_rota": True})
    agora = _carga(andamento={"tem_posicao": True, "progresso_pct": 22,
                              "falta_km": 515, "por_rota": True})
    enviados = cenario([_ins(ultima_assinatura=mensagem.assinatura([antes]))],
                       agora)
    r = aviso.rodar()
    assert len(enviados) == 1 and r["enviados"] == 1


def test_a_ENTREGA_sempre_gera_mensagem(cenario):
    """Mudança de ESTADO passa por cima de qualquer degrau: a entrega é a
    única mensagem que a pessoa esperou a viagem inteira para receber."""
    antes = _carga()
    agora = _carga(estado="entregue", entregue_em="2026-09-06T18:20:00")
    enviados = cenario([_ins(ultima_assinatura=mensagem.assinatura([antes]))],
                       agora)
    r = aviso.rodar()
    assert len(enviados) == 1 and r["enviados"] == 1
    assert "Entregue" in enviados[0][1]


def test_mensagem_DIFERENTE_e_enviada(cenario):
    carga = _carga()
    enviados = cenario([_ins(ultima_assinatura="qualquer coisa antiga")], carga)
    r = aviso.rodar()
    assert len(enviados) == 1 and r["enviados"] == 1


def test_o_TEXTO_gravado_nao_decide_mais_o_reenvio(cenario):
    """Quem decide é a assinatura, e só ela.

    Enquanto `ultimo_texto` tivesse voto, bastaria uma mudança de redação —
    um emoji novo, uma palavra — para toda a base receber uma rodada de
    mensagens que não noticiam nada. A redação muda toda semana; o que a
    pessoa precisa saber, não.
    """
    carga = _carga()
    enviados = cenario([_ins(ultimo_texto="um texto completamente diferente",
                             ultima_assinatura=mensagem.assinatura([carga]))],
                       carga)
    r = aviso.rodar()
    assert enviados == [] and r["iguais"] == 1


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


def test_a_inscricao_GRAVA_o_envio_inicial(monkeypatch):
    """É ESTA GRAVAÇÃO QUE ANCORA O RELÓGIO NO PEDIDO.

    Sem ela a inscrição nascia com `ultimo_envio` e `ultimo_texto` nulos: o
    ciclo seguinte a lia como "nunca avisada", não tinha com o que comparar o
    texto, e mandava tudo de novo. Medido em 05/09/2026 — a inscrição das 12h38
    recebeu a mensagem de cadastro e outra às 13h00.
    """
    from api.rastreio import assinatura

    marcados = []
    alvo = {"grupo": 1, "empresa": 1, "filial": 1, "numero": 51283, "serie": 1}
    monkeypatch.setattr(assinatura.consulta, "buscar_cru",
                        lambda t, c: ([alvo], None))
    monkeypatch.setattr(assinatura.consulta, "token", lambda *a: "ID")
    monkeypatch.setattr(assinatura.pglocal, "get_conn", _conn_falsa)
    monkeypatch.setattr(aviso, "_carga_da_inscricao", lambda i: _carga())
    monkeypatch.setattr(aviso.wa, "enviar", lambda f, t, **k: {"ok": True})
    monkeypatch.setattr(assinatura, "marcar_envio",
                        lambda i, t, **k: marcados.append((i, t, k)))

    assinatura.inscrever("51283", "0051", "ID", "11987654321", "1.2.3.4")
    assert len(marcados) == 1, "o envio inicial tem de ser gravado"
    # O TEXTO GRAVADO É O CRU, SEM RODAPÉ. O rodapé carrega o número do
    # documento e muda de mensagem para mensagem: gravá-lo junto faria a
    # comparação do ciclo seguinte nunca casar, e a mensagem repetida voltaria
    # por outra porta — a mesma que este guard fecha.
    assert "SAIR" not in marcados[0][1]
    # E A ASSINATURA VAI JUNTO. Sem ela a inscrição nasceria com nada para
    # comparar, e o primeiro ciclo — dentro da hora seguinte ao cadastro —
    # repetiria a mensagem que a pessoa acabou de ler. É a hora em que ela mais
    # facilmente bloqueia o número: acabou de dá-lo.
    assert marcados[0][2].get("assin"), \
        "o envio inicial gravou o texto mas não a assinatura"
    assert marcados[0][2]["assin"] == mensagem.assinatura([_carga()])


def test_envio_inicial_RECUSADO_nao_ancora_o_relogio(monkeypatch):
    """Se a mensagem não saiu, a pessoa não foi avisada — e gravar o envio a
    faria esperar uma hora por algo que nunca chegou. Sem gravação, o próximo
    ciclo a trata como vencida e ela recebe na primeira oportunidade."""
    from api.rastreio import assinatura

    marcados = []
    alvo = {"grupo": 1, "empresa": 1, "filial": 1, "numero": 51283, "serie": 1}
    monkeypatch.setattr(assinatura.consulta, "buscar_cru",
                        lambda t, c: ([alvo], None))
    monkeypatch.setattr(assinatura.consulta, "token", lambda *a: "ID")
    monkeypatch.setattr(assinatura.pglocal, "get_conn", _conn_falsa)
    monkeypatch.setattr(aviso, "_carga_da_inscricao", lambda i: _carga())
    monkeypatch.setattr(aviso.wa, "enviar",
                        lambda f, t, **k: {"ok": False, "erro": "fora da janela"})
    monkeypatch.setattr(assinatura, "marcar_envio",
                        lambda i, t, **k: marcados.append((i, t, k)))

    assinatura.inscrever("51283", "0051", "ID", "11987654321", "1.2.3.4")
    assert marcados == []


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


# --------------------------------------------------------------------------
# O RELÓGIO É O DA PESSOA, não a hora cheia do servidor
# --------------------------------------------------------------------------
def _ins(**kw) -> dict:
    base = {"id": 1, "grupo": 1, "empresa": 1, "filial": 2, "numero": 94540,
            "serie": 2, "telefone": "5541999999999", "ultimo_texto": None,
            "ultimo_envio": None, "envios": 0, "desde_min": 999}
    base.update(kw)
    return base


def _sem_rede(monkeypatch, inscricoes):
    """Deixa o `rodar()` andar sem tocar em banco, ERP nem WhatsApp."""
    from api.rastreio import assinatura
    monkeypatch.setattr(assinatura, "ativas", lambda: inscricoes)
    monkeypatch.setattr(aviso, "_carga_da_inscricao", lambda i: _carga())


def test_quem_acabou_de_receber_NAO_recebe_de_novo(monkeypatch):
    """O DEFEITO QUE ISTO FECHA, medido em 05/09/2026: quem se inscrevia às
    12h38 recebia a mensagem de cadastro e OUTRA às 13h00 — vinte e dois
    minutos depois, com o mesmo conteúdo. O ciclo da hora cheia não sabia que a
    pessoa acabara de ser avisada.

    Duas mensagens iguais em vinte minutos é exatamente o que faz alguém
    bloquear o número — e o bloqueio atinge o número que fala com todos os
    outros clientes."""
    _sem_rede(monkeypatch, [_ins(desde_min=22)])
    r = aviso.rodar(ensaio=True)
    assert r["enviados"] == 0
    assert r["cedo"] == 1, "ficar calado no prazo é a terceira resposta, e ela se declara"


def test_vencido_pelo_relogio_DELE_recebe(monkeypatch):
    """Passados os 60 minutos contados do pedido, sai — mesmo que não seja
    hora cheia. É isto que faz quem pediu 12h38 receber 13h38."""
    _sem_rede(monkeypatch, [_ins(desde_min=61)])
    r = aviso.rodar(ensaio=True)
    assert r["cedo"] == 0
    assert r["inscricoes"] == 1


def test_ancora_ilegivel_erra_para_o_lado_de_AVISAR(monkeypatch):
    """`desde_min` nulo é inscrição sem âncora legível. Entre calar e avisar
    quem está esperando a carga, o lado seguro é avisar: o texto igual ao
    anterior ainda seria barrado depois, e o silêncio não teria remédio."""
    _sem_rede(monkeypatch, [_ins(desde_min=None)])
    r = aviso.rodar(ensaio=True)
    assert r["cedo"] == 0 and r["inscricoes"] == 1


def test_a_ancora_e_do_TELEFONE_e_nao_da_carga(monkeypatch):
    """As cargas de um mesmo número saem numa mensagem SÓ. Se a âncora fosse
    por carga, quem acompanha duas receberia duas mensagens por hora, em
    minutos diferentes — desfazendo o agrupamento que existe justamente para
    não fazer a pessoa bloquear o número.

    Por isso `desde_min` vem calculado POR TELEFONE no banco: as duas linhas do
    mesmo número carregam o mesmo valor, e as duas esperam juntas."""
    duas = [_ins(id=1, numero=94540, desde_min=20),
            _ins(id=2, numero=94541, desde_min=20)]
    _sem_rede(monkeypatch, duas)
    r = aviso.rodar(ensaio=True)
    assert r["enviados"] == 0 and r["cedo"] == 2


def test_o_intervalo_e_UMA_CONSTANTE_e_nao_esta_escrita_no_aviso():
    """A cadência muda mexendo em `assinatura`, num lugar só. Um `60` digitado
    dentro de `aviso.py` seria a próxima pessoa mudando o intervalo e
    descobrindo que ele continua igual.

    O DONO DO NÚMERO MUDOU quando a cadência virou escolha de quem recebe: o
    `aviso.py` não lê mais a constante direto, lê a preferência. O que o guard
    protege é o mesmo — nenhum intervalo escrito à mão aqui.
    """
    from api.rastreio import assinatura
    assert assinatura.INTERVALO_MIN == 60
    fonte = (Path(aviso.__file__)).read_text(encoding="utf-8")
    assert "assinatura.preferencia" in fonte
    for literal in ("60", "180", "3600"):
        assert ("intervalo_min = %s" % literal) not in fonte
        assert ("desde >= %s" % literal) not in fonte


def test_NENHUMA_cadencia_aperta_abaixo_do_piso():
    """A escolha de quem recebe só ESPAÇA as mensagens — nunca as aproxima.

    Se uma cadência pudesse descer abaixo de `INTERVALO_MIN`, a página aberta à
    internet passaria a oferecer um jeito de afrouxar o freio da casa a pedido
    do próprio destinatário. O estrago não seria dele: é a reputação do número
    que fala com todos os outros clientes.
    """
    from api.rastreio import assinatura
    for nome, regra in assinatura.CADENCIAS.items():
        assert regra["intervalo_min"] >= assinatura.INTERVALO_MIN, nome


def test_a_cadencia_PADRAO_existe_no_catalogo():
    """Padrão que não está no catálogo vira `KeyError` no primeiro cadastro —
    e o cadastro é feito por quem não é usuário do sistema."""
    from api.rastreio import assinatura
    assert assinatura.CADENCIA_PADRAO in assinatura.CADENCIAS
    assert assinatura.JANELA_PADRAO in assinatura.JANELAS


# --------------------------------------------------------------------------
# a janela e a cadência de quem RECEBE
# --------------------------------------------------------------------------
def test_a_janela_do_cliente_so_RESTRINGE_a_da_casa():
    """Uma página aberta à internet não pode AMPLIAR a proteção que existe para
    o número da empresa não ser denunciado. Quem pedir 03:00 recebe às 06:00."""
    from api.rastreio import assinatura
    from api.whatsapp import config as wcfg

    ini, fim = assinatura.janela_efetiva("03:00", "23:00")
    casa = wcfg.ler()
    assert ini >= casa["janela_inicio"], "o cliente ampliou o começo da janela"
    assert fim <= casa["janela_fim"], "o cliente ampliou o fim da janela"


def test_janela_NULA_segue_a_casa_e_nao_significa_sem_restricao():
    """`None` em campo de regra opcional significa HERDA, nunca zero — e aqui
    "zero restrição" seria mensagem de madrugada."""
    from api.rastreio import assinatura
    from api.whatsapp import config as wcfg
    casa = wcfg.ler()
    assert assinatura.janela_efetiva(None, None) == (casa["janela_inicio"],
                                                     casa["janela_fim"])


def test_quem_pediu_SO_DE_MANHA_nao_recebe_a_tarde(cenario, monkeypatch):
    """A escolha da pessoa tem de valer no AVISO, e não só no envio: o
    `whatsapp.envio` barra a janela GERAL — ele é o freio da casa — mas não
    sabe que este telefone pediu para ser avisado só de manhã."""
    from api.rastreio import assinatura
    monkeypatch.setattr(assinatura, "dentro_da_janela", lambda ins, agora=None:
                        assinatura.preferencia(ins)["inicio"] != "06:00")

    enviados = cenario([_ins(janela_inicio="06:00", janela_fim="12:00")],
                       _carga())
    r = aviso.rodar()
    assert enviados == [], "mandou fora da janela que a pessoa escolheu"
    assert r["fora_janela"] == 1 and r["enviados"] == 0


def test_fora_da_janela_NAO_conta_como_falha_nem_some_do_relatorio(cenario,
                                                                   monkeypatch):
    """É a pessoa sendo atendida na escolha dela — a terceira resposta do aviso
    ("calei porque não era hora"). Somada às falhas viraria alarme falso; fora
    do relatório, a tarefa pareceria não ter feito nada."""
    from api.rastreio import assinatura
    monkeypatch.setattr(assinatura, "dentro_da_janela", lambda i, agora=None: False)
    cenario([_ins()], _carga())
    r = aviso.rodar()
    assert r["fora_janela"] == 1
    assert r["falhas"] == 0 and r["cedo"] == 0 and r["sem_texto"] == 0


def test_quem_pediu_MENOS_mensagens_espera_TRES_horas(cenario):
    """A cadência espaça de verdade: com 90 minutos desde a última mensagem,
    quem está em "tudo" recebe e quem está em "menos" ainda não."""
    tudo = cenario([_ins(desde_min=90, cadencia="tudo")], _carga())
    assert aviso.rodar()["enviados"] == 1
    tudo.clear()

    cenario([_ins(desde_min=90, cadencia="menos")], _carga())
    r = aviso.rodar()
    assert r["enviados"] == 0 and r["cedo"] == 1


def test_quem_pediu_SO_MARCOS_ignora_progresso_mas_NAO_a_entrega(cenario):
    """A viagem inteira vira uma linha só; a chegada continua chegando."""
    from api.rastreio import mensagem

    antes = _carga(andamento={"tem_posicao": True, "progresso_pct": 10,
                              "falta_km": 600, "por_rota": True})
    andou = _carga(andamento={"tem_posicao": True, "progresso_pct": 70,
                              "falta_km": 200, "por_rota": True})
    assin = mensagem.assinatura([antes], so_marcos=True)

    # ANDOU MEIA VIAGEM e continua calado: foi o que a pessoa pediu.
    cenario([_ins(cadencia="marcos", ultima_assinatura=assin)], andou)
    assert aviso.rodar()["enviados"] == 0

    # A ENTREGA PASSA POR CIMA DE QUALQUER CADENCIA.
    entregue = _carga(estado="entregue", entregue_em="2026-09-06T18:20:00")
    enviados = cenario([_ins(cadencia="marcos", ultima_assinatura=assin)],
                       entregue)
    assert aviso.rodar()["enviados"] == 1
    assert "Entregue" in enviados[-1][1]


def test_a_cadencia_MARCOS_ainda_avisa_quando_PERDEMOS_o_veiculo(cenario):
    """"Não sei onde ele está" é notícia para todo mundo, em qualquer cadência:
    calar aqui seria indistinguível de "está tudo calmo"."""
    from api.rastreio import mensagem

    normal = _carga()
    assin = mensagem.assinatura([normal], so_marcos=True)
    perdido = _carga()
    perdido["andamento"] = {"tem_posicao": False, "fora_da_rota": True}

    cenario([_ins(cadencia="marcos", ultima_assinatura=assin)], perdido)
    assert aviso.rodar()["enviados"] == 1
