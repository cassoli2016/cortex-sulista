# -*- coding: utf-8 -*-
"""Quando a MESMA pessoa acompanha mais de uma carga.

O QUE ESTES GUARDS PROTEGEM é de novo o número da empresa, e agora com conta
fechada: o teto é de 5 cargas por telefone e a janela tem 14 ciclos por dia.
Uma mensagem por carga daria 70 mensagens diárias para a MESMA pessoa — acima
do teto de 60 por número que a casa impõe. Quem acompanhasse cinco cargas
pararia de receber no meio da tarde, e sem aviso nenhum: as recusas ficam no
nosso log, não no celular dela.

E antes do teto vem o estrago maior. Cinco notificações por hora do mesmo
número é o que faz alguém bloquear o contato — e o bloqueio não atinge estas
mensagens, atinge o número que fala com todos os outros clientes.

A SAÍDA TAMBÉM MUDA. Com várias cargas, a pessoa quase sempre quer parar a que
já chegou e continuar com as outras. Oferecer só o "tudo ou nada" faz quem
queria sair de uma sair de todas — e essa pessoa não volta a se cadastrar.
"""
from __future__ import annotations

import pytest

from api.rastreio import aviso, entrada, mensagem


def _carga(doc, pct=50, estado="em_viagem", **kw):
    a = {"tem_posicao": True, "progresso_pct": pct, "falta_km": 120,
         "km_rota": 300, "por_rota": True, "atualizado_ha_min": 3}
    a.update(kw.pop("andamento", {}))
    return {"documento": "CT-e %s" % doc, "origem": "Joinville/SC",
            "destino": "Santos/SP", "estado": estado, "entregue_em": None,
            "link_token": "tok%s" % doc, "andamento": a}


# --------------------------------------------------------------------------
# a mensagem consolidada
# --------------------------------------------------------------------------
def test_TODAS_as_cargas_cabem_numa_mensagem_so():
    t = mensagem.montar_varias([_carga("111"), _carga("222"), _carga("333")])
    assert t.count("CT-e") == 3
    assert "Suas 3 cargas" in t
    # e cada uma leva o SEU link: o token é por carga, não por pessoa
    for doc in ("111", "222", "333"):
        assert "tok%s" % doc in t


def test_UMA_carga_continua_com_a_mensagem_INTEIRA():
    """A consolidada é mais seca por construção — três linhas por carga.
    Degradar quem acompanha uma só para acomodar quem acompanha cinco seria
    pagar o preço no caso comum."""
    uma = mensagem.montar_varias([_carga("111")])
    assert uma == mensagem.montar(_carga("111"))
    assert "Suas" not in uma
    assert "Em viagem" in uma      # o cabeçalho completo, que a seca não tem


def test_a_carga_ENTREGUE_aparece_junto_das_outras():
    """Ela não some da lista nem vira uma mensagem separada: quem espera três
    cargas quer as três no mesmo lugar."""
    t = mensagem.montar_varias([_carga("111"), _carga("222", estado="entregue")])
    assert "ENTREGUE" in t and "CT-e 111" in t


def test_carga_sem_novidade_nao_esvazia_a_mensagem_das_outras():
    """Uma carga sem posição não pode calar as demais."""
    muda = _carga("222", andamento={"tem_posicao": False,
                                    "progresso_pct": None, "falta_km": None})
    t = mensagem.montar_varias([_carga("111"), muda])
    assert t and "CT-e 111" in t and "CT-e 222" not in t


def test_se_NENHUMA_tem_novidade_a_mensagem_CALA():
    muda = {"documento": "CT-e 1", "andamento": {"tem_posicao": False}}
    assert mensagem.montar_varias([muda, dict(muda, documento="CT-e 2")]) is None
    assert mensagem.montar_varias([]) is None


def test_o_rodape_ENSINA_a_sair_de_uma_quando_ha_varias():
    assert mensagem.rodape(1) == mensagem.RODAPE
    r = mensagem.rodape(3, "94537")
    assert "SAIR 94537" in r and "todas" in r


# --------------------------------------------------------------------------
# um envio por telefone, não por carga
# --------------------------------------------------------------------------
@pytest.fixture
def ciclo(monkeypatch):
    estado = {"enviados": [], "marcados": [], "encerradas": []}

    def _montar(inscricoes, cargas):
        monkeypatch.setattr(aviso.assinatura, "ativas", lambda: inscricoes)
        monkeypatch.setattr(aviso, "_carga_da_inscricao",
                            lambda ins: cargas.get(ins["id"]))
        monkeypatch.setattr(aviso.wa, "enviar",
                            lambda f, t, **k: (estado["enviados"].append((f, t))
                                               or {"ok": True}))
        monkeypatch.setattr(aviso.assinatura, "marcar_envio",
                            lambda i, t: estado["marcados"].append(i))
        monkeypatch.setattr(aviso.assinatura, "encerrar",
                            lambda i, m: estado["encerradas"].append(i))
        return estado
    return _montar


def _ins(ident, numero, fone="5541984251704", **kw):
    base = {"id": ident, "grupo": 1, "empresa": 1, "filial": 2,
            "numero": numero, "serie": 1, "telefone": fone,
            "ultimo_texto": None, "ultimo_envio": None, "envios": 0}
    base.update(kw)
    return base


def test_TRES_cargas_do_mesmo_telefone_geram_UM_envio(ciclo):
    """O guard do teto. Três envios por ciclo × 14 ciclos = 42 mensagens por
    dia para a mesma pessoa; com cinco cargas passa de 60 e ela para de receber
    calada."""
    ins = [_ins(1, 111), _ins(2, 222), _ins(3, 333)]
    e = ciclo(ins, {1: _carga("111"), 2: _carga("222"), 3: _carga("333")})
    r = aviso.rodar()
    assert len(e["enviados"]) == 1, "mandou uma mensagem por carga"
    assert r["enviados"] == 1 and r["telefones"] == 1
    # mas TODAS as inscrições ficam marcadas, senão o próximo ciclo repetiria
    assert sorted(e["marcados"]) == [1, 2, 3]


def test_telefones_DIFERENTES_continuam_recebendo_cada_um(ciclo):
    ins = [_ins(1, 111), _ins(2, 222, fone="5511988887777")]
    e = ciclo(ins, {1: _carga("111"), 2: _carga("222")})
    aviso.rodar()
    assert len(e["enviados"]) == 2
    assert {f for f, _ in e["enviados"]} == {"5541984251704", "5511988887777"}


def test_a_ENTREGA_encerra_SO_a_carga_entregue(ciclo):
    """As outras cargas do mesmo telefone seguem sendo avisadas — e é isso que
    a consolidação tornou possível dizer: antes, encerrar era por mensagem."""
    ins = [_ins(1, 111), _ins(2, 222)]
    e = ciclo(ins, {1: _carga("111"), 2: _carga("222", estado="entregue")})
    aviso.rodar()
    assert e["encerradas"] == [2]


def test_mensagem_IGUAL_a_do_ciclo_anterior_nao_se_repete(ciclo):
    texto = mensagem.montar_varias([_carga("111"), _carga("222")])
    ins = [_ins(1, 111, ultimo_texto=texto), _ins(2, 222, ultimo_texto=texto)]
    e = ciclo(ins, {1: _carga("111"), 2: _carga("222")})
    r = aviso.rodar()
    assert e["enviados"] == [] and r["iguais"] == 2


def test_o_rodape_da_mensagem_enviada_ensina_a_sintaxe(ciclo):
    ins = [_ins(1, 111), _ins(2, 222)]
    e = ciclo(ins, {1: _carga("111"), 2: _carga("222")})
    aviso.rodar()
    _, texto = e["enviados"][0]
    assert "SAIR 111" in texto


# --------------------------------------------------------------------------
# sair de UMA
# --------------------------------------------------------------------------
@pytest.fixture
def saida(monkeypatch):
    estado = {"cancelados": [], "enviados": []}

    def _montar(quantas=1):
        def _cancelar(fone, numero=None):
            estado["cancelados"].append((fone, numero))
            return quantas
        monkeypatch.setattr(entrada.assinatura, "cancelar_por_telefone",
                            _cancelar)
        monkeypatch.setattr(entrada.wa, "enviar",
                            lambda f, t, **k: (estado["enviados"].append(t)
                                               or {"ok": True}))
        return estado
    return _montar


def _msg(texto, fone="5541984251704"):
    return {"phone": fone, "text": {"message": texto}}


def test_SAIR_com_numero_cancela_SO_aquela_carga(saida):
    e = saida()
    r = entrada.receber(_msg("SAIR 94537"))
    assert r["acao"] == "cancelado" and r["numero"] == 94537
    assert e["cancelados"] == [("5541984251704", 94537)]
    # e a confirmação DIZ que as outras continuam — sem isso a pessoa fica na
    # dúvida e manda o SAIR seco por precaução.
    assert "94537" in e["enviados"][0] and "continuam" in e["enviados"][0]


def test_SAIR_sozinho_continua_cancelando_TUDO(saida):
    """Quem responde só SAIR quer parar com tudo. Exigir que ele liste as
    cargas transformaria a saída em formulário."""
    e = saida(quantas=3)
    r = entrada.receber(_msg("SAIR"))
    assert r["acao"] == "cancelado" and r["numero"] is None
    assert e["cancelados"] == [("5541984251704", None)]


def test_a_pessoa_escreve_de_varios_jeitos(saida):
    for texto, esperado in (("SAIR 94537", 94537), ("sair 94537", 94537),
                            ("Sair, 94537", 94537), ("SAIR-94537", 94537),
                            ("parar 102518", 102518), ("SAIR", None),
                            ("sair por favor", None)):
        e = saida()
        entrada.receber(_msg(texto))
        assert e["cancelados"][-1][1] == esperado, texto


def test_numero_que_NAO_e_da_pessoa_nao_cancela_nada(saida):
    """Dedo trocado, ou carga de outro. Cair para "cancela tudo" seria o pior
    desfecho: quem quis sair de uma sairia de todas sem ter pedido."""
    e = saida(quantas=0)
    r = entrada.receber(_msg("SAIR 99999"))
    assert r["acao"] == "carga_nao_encontrada"
    assert e["enviados"] == [], "respondeu a um pedido que não achou nada"
