# -*- coding: utf-8 -*-
"""O cartão da Saúde que diz se o monitoramento de cliente está SAINDO.

A prova é a PASSAGEM gravada em cada rodada, nunca a lista de tarefas do
Windows (que sem elevação esconde tarefa de SISTEMA sem erro nenhum).
"""
from __future__ import annotations

from datetime import datetime

from api import servidor


def _m(**kw):
    base = {"id": 1, "cliente_raiz": "12345678", "cliente_nome": "CLIENTE TESTE",
            "intervalo_min": 120, "hora_inicio": "06:00", "hora_fim": "22:00",
            "dias_semana": "123456", "ativo": True,
            "ultima_execucao": "2026-09-11 10:01:00", "ultimo_resultado": "enviado",
            "criado_em": "2026-09-01 10:00:00", "alterado_em": None}
    return {**base, **kw}


def _cartao(agora, **kw):
    return servidor._monitoramento_email(agora=agora, itens=[_m(**kw)])


def test_em_dia_e_OK():
    c = _cartao(datetime(2026, 9, 11, 10, 40))
    assert c["status"] == "ok" and "11/09 10:01" in c["detalhe"]


def test_rodada_sem_passagem_depois_da_folga_e_ERRO():
    """12h50: a rodada das 12h passou há 50 min e a última passagem é das
    10h — a tarefa parou, e o cliente está sem notícia."""
    c = _cartao(datetime(2026, 9, 11, 12, 50))
    assert c["status"] == "erro" and "11/09 12:00" in c["detalhe"]


def test_dentro_da_folga_ainda_nao_e_erro():
    assert _cartao(datetime(2026, 9, 11, 12, 30))["status"] == "ok"


def test_fora_dos_dias_marcados_nao_devia_sair():
    c = _cartao(datetime(2026, 9, 13, 12, 50))            # domingo
    assert c["status"] == "ok"


def test_nao_ler_a_operacao_e_ALERTA():
    """Nada foi ao cliente, de propósito — e alguém precisa saber."""
    c = _cartao(datetime(2026, 9, 11, 10, 40),
                ultimo_resultado="falhou: não leu a operação (OperationalError)")
    assert c["status"] == "alerta" and "não leu" in c["detalhe"]


def test_dia_sem_carga_nao_e_falha():
    c = _cartao(datetime(2026, 9, 11, 10, 40),
                ultimo_resultado="sem carga no dia — não enviado")
    assert c["status"] == "ok"


def test_nada_ligado_e_info():
    c = servidor._monitoramento_email(agora=datetime(2026, 9, 11, 10, 40),
                                      itens=[_m(ativo=False)])
    assert c["status"] == "info"
