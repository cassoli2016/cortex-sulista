# -*- coding: utf-8 -*-
"""O cartão da Saúde que diz se os relatórios por e-mail estão SAINDO.

A prova de que a tarefa agendada roda é o DADO que ela deixa (a passagem
gravada na agenda), nunca a lista de tarefas do Windows — que, sem elevação,
esconde tarefa registrada como SISTEMA sem erro nenhum.
"""
from __future__ import annotations

from datetime import datetime

from api import servidor


def _ag(**kw):
    base = {"id": 1, "relatorio": "inadimplencia", "destinatarios": "a@b.com",
            "frequencia": "diario", "hora": "13:00", "dia_semana": None,
            "dia_mes": None, "dias_uteis": True, "ativo": True,
            "ultima_execucao": "2026-09-10 13:01:00", "ultimo_resultado": "enviado",
            "criado_em": "2026-09-01 10:00:00", "alterado_em": None}
    return {**base, **kw}


def _cartao(agora, **kw):
    return servidor._relatorios_email(agora=agora, itens=[_ag(**kw)])


def test_a_passagem_que_NAO_aconteceu_e_ERRO():
    """Sexta 14h, e a última passagem é de quinta: a tarefa parou."""
    c = _cartao(datetime(2026, 9, 11, 14, 0))
    assert c["status"] == "erro"
    assert "Inadimplência" in c["detalhe"] and "11/09 13:00" in c["detalhe"]


def test_em_dia_e_OK():
    c = _cartao(datetime(2026, 9, 11, 14, 0), ultima_execucao="2026-09-11 13:01:00")
    assert c["status"] == "ok" and "11/09 13:01" in c["detalhe"]


def test_dentro_da_folga_ainda_nao_e_erro():
    """13h30: a tarefa passa de 15 em 15 min, e três disparos de folga não
    viraram."""
    assert _cartao(datetime(2026, 9, 11, 13, 30))["status"] == "ok"


def test_no_SABADO_o_de_dia_util_nao_devia_sair():
    c = _cartao(datetime(2026, 9, 12, 14, 0), ultima_execucao="2026-09-11 13:01:00")
    assert c["status"] == "ok"


def test_criado_DEPOIS_da_hora_ainda_nao_teve_a_chance():
    c = _cartao(datetime(2026, 9, 11, 14, 0), ultima_execucao=None,
                criado_em="2026-09-11 13:50:00")
    assert c["status"] == "ok"


def test_envio_que_FALHOU_e_alerta():
    c = _cartao(datetime(2026, 9, 11, 14, 0), ultima_execucao="2026-09-11 13:01:00",
                ultimo_resultado="falhou: SMTP recusou")
    assert c["status"] == "alerta" and "SMTP" in c["detalhe"]


def test_nada_ligado_e_info_e_nao_alarme():
    c = servidor._relatorios_email(agora=datetime(2026, 9, 11, 14, 0),
                                   itens=[_ag(ativo=False)])
    assert c["status"] == "info"
