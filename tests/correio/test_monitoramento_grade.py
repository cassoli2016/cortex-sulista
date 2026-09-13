# -*- coding: utf-8 -*-
"""A grade do monitoramento de cliente: a cada N horas, numa faixa, em dias.

Função pura (`api/agendamento`), sem banco e sem rede. As guardas são as
mesmas da agenda de relatórios — padrão desligado, passagem que impede o
reenvio, recusa na gravação — mais as duas desta grade: ela é FIXA NO
RELÓGIO, e a rodada atrasada é substituída pela seguinte em vez de se somar
a ela.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from api import agendamento as ag
from api.correio import monitoramento as mo


def _m(**kw):
    base = {"id": 1, "cliente_raiz": "12345678", "cliente_nome": "CLIENTE X",
            "destinatarios": "a@b.com", "intervalo_min": 120,
            "hora_inicio": "06:00", "hora_fim": "22:00", "dias_semana": "123456",
            "ativo": True, "ultima_execucao": None}
    return {**base, **kw}


SEX = datetime(2026, 9, 11)          # sexta
SAB = datetime(2026, 9, 12)          # sábado
DOM = datetime(2026, 9, 13)          # domingo


def _em(dia, h, m=0):
    return dia.replace(hour=h, minute=m)


def test_a_grade_e_FIXA_no_relogio():
    """Máquina que acordou às 09:10 não empurra o dia inteiro para 09:10."""
    assert ag.rodada(_m(), _em(SEX, 9, 10)) == _em(SEX, 8)
    assert ag.rodada(_m(), _em(SEX, 10, 0)) == _em(SEX, 10)
    assert ag.rodada(_m(), _em(SEX, 6, 0)) == _em(SEX, 6)


def test_antes_da_faixa_nao_ha_rodada():
    assert ag.rodada(_m(), _em(SEX, 5, 59)) is None
    pode, porque = ag.deve_rodar_intervalo(_m(), _em(SEX, 5, 30))
    assert not pode and "fora da faixa" in porque


def test_a_ultima_rodada_vale_por_um_intervalo_depois_do_fim():
    """22:00 é a última; às 23:30 ela ainda pode sair (máquina voltou), mas
    à 00:10 do dia seguinte já não é deste dia."""
    assert ag.rodada(_m(), _em(SEX, 23, 30)) == _em(SEX, 22)
    assert ag.rodada(_m(hora_fim="21:00"), _em(SEX, 23, 30)) is None


def test_dia_fora_da_lista_nao_roda():
    pode, porque = ag.deve_rodar_intervalo(_m(), _em(DOM, 10))
    assert not pode and "domingo" in porque
    assert ag.deve_rodar_intervalo(_m(), _em(SAB, 10))[0]


def test_desligado_nao_roda():
    pode, porque = ag.deve_rodar_intervalo(_m(ativo=False), _em(SEX, 10))
    assert not pode and "desligado" in porque


def test_a_passagem_na_rodada_impede_o_reenvio():
    """A tarefa dispara de 15 em 15 min: sem isto seriam oito e-mails por
    rodada para o CLIENTE."""
    m = _m(ultima_execucao="2026-09-11 10:01:00")
    pode, porque = ag.deve_rodar_intervalo(m, _em(SEX, 10, 45))
    assert not pode and "10:00" in porque
    assert ag.deve_rodar_intervalo(m, _em(SEX, 12, 1))[0]


def test_rodada_atrasada_e_SUBSTITUIDA_e_nao_somada():
    """Desligada às 08:00, volta às 10:05: sai a das 10:00, uma vez — não a
    das 08:00 e a das 10:00 em cinco minutos."""
    m = _m(ultima_execucao="2026-09-11 06:01:00")
    pode, porque = ag.deve_rodar_intervalo(m, _em(SEX, 10, 5))
    assert pode and "10:00" in porque


def test_proxima_rodada():
    assert ag.proxima_intervalo(_m(), _em(SEX, 9, 10)) == "2026-09-11 10:00"
    # depois da última do sábado, a próxima é a de segunda (domingo fora)
    assert ag.proxima_intervalo(_m(), _em(SAB, 22, 30)) == "2026-09-14 06:00"
    assert ag.proxima_intervalo(_m(ativo=False)) is None


def test_descricao_le_como_frase():
    assert ag.descrever_intervalo(_m()) == \
        "a cada 2 h, das 06:00 às 22:00, de segunda a sábado"
    assert "todos os dias" in ag.descrever_intervalo(_m(dias_semana="1234567"))


def test_grade_ilegivel_no_banco_nao_derruba_a_rotina():
    assert ag.rodada(_m(hora_inicio="seis horas"), _em(SEX, 10)) is None
    assert not ag.deve_rodar_intervalo(_m(intervalo_min=0), _em(SEX, 10))[0]


# ─────────────────────────────────────────────── a validação da regra ─────

def _v(**kw):
    base = {"cliente_raiz": "12345678", "destinatarios": "a@b.com"}
    return mo.validar({**base, **kw})


def test_monitoramento_nasce_DESLIGADO():
    """Este e-mail vai para o CLIENTE."""
    v = _v()
    assert v["ativo"] is False
    assert v["intervalo_min"] == 120 and v["dias_semana"] == "123456"
    assert v["anexar_planilha"] is True


def test_cliente_sem_raiz_e_recusado():
    for ruim in ("", "1234567", "123456789", "abcdefgh"):
        with pytest.raises(ValueError, match="cliente"):
            _v(cliente_raiz=ruim)


def test_intervalo_fora_da_lista_e_recusado():
    """Quinze minutos viraria spam na caixa do cliente."""
    with pytest.raises(ValueError, match="Intervalo"):
        _v(intervalo_min=15)


def test_faixa_que_atravessa_a_meia_noite_e_recusada():
    with pytest.raises(ValueError, match="00:00 às 23:59"):
        _v(hora_inicio="22:00", hora_fim="06:00")


def test_sem_dia_marcado_e_recusado():
    with pytest.raises(ValueError, match="dia"):
        _v(dias_semana=[])


def test_dias_aceitam_lista_e_saem_em_ordem():
    assert _v(dias_semana=[6, 1, 3, 3, 9])["dias_semana"] == "136"


def test_destinatario_e_resposta_invalidos_sao_recusados():
    with pytest.raises(ValueError, match="nv"):
        _v(destinatarios="nao-e-email")
    with pytest.raises(ValueError, match="resposta"):
        _v(responder_para="torre@")


def test_mercadorias_saem_canonicas():
    """Mesma régua do filtro da tela Minha Operação: "PEÇAS" e "pecas" são
    a mesma escolha, e a ordem não cria duas regras."""
    v = _v(mercadorias=["Escadas", "CONJUNTOS", "escadas"])
    assert v["mercadorias"] == sorted(set(v["mercadorias"])) and len(v["mercadorias"]) == 2


def test_gravar_exige_autor():
    with pytest.raises(ValueError, match="Informe quem"):
        mo.gravar({"cliente_raiz": "12345678", "destinatarios": "a@b.com"}, "")
