# tests/correio/test_agenda.py
"""Agendamento dos relatorios por e-mail.

As guardas aqui sao as MESMAS que a emissao de contrapartida pagou caro para
aprender - padrao desligado, passagem marcada mesmo sem enviar, e recusa em
vez de suposicao silenciosa. Nenhum teste vai a rede nem envia e-mail.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from api.correio import agenda


def _ag(**kw):
    base = {"id": 1, "relatorio": "digest", "destinatarios": "a@b.com",
            "frequencia": "diario", "hora": "07:00", "dia_semana": None,
            "dia_mes": None, "ativo": True, "ultima_execucao": None}
    return {**base, **kw}


def test_agendamento_nasce_DESLIGADO():
    """Ausencia de decisao nunca pode significar "manda e-mail para fora da
    empresa" - mesmo principio da automacao de emissao."""
    v = agenda.validar({"relatorio": "digest", "destinatarios": "a@b.com"})
    assert v["ativo"] is False


def test_desligado_nao_roda():
    pode, porque = agenda.deve_rodar(_ag(ativo=False))
    assert not pode and "desligado" in porque


def test_antes_da_hora_nao_roda():
    pode, porque = agenda.deve_rodar(_ag(), datetime(2026, 8, 27, 6, 30))
    assert not pode and "faltam" in porque


def test_na_hora_roda():
    pode, porque = agenda.deve_rodar(_ag(), datetime(2026, 8, 27, 7, 2))
    assert pode and "na hora" in porque


def test_ja_enviado_na_janela_nao_repete():
    """Sem isto a rotina reenvia a CADA disparo do agendador - o defeito que a
    automacao de emissao viveu por horas sem ninguem notar."""
    ag = _ag(ultima_execucao="2026-08-27 07:01:00")
    pode, porque = agenda.deve_rodar(ag, datetime(2026, 8, 27, 7, 30))
    assert not pode and "enviado" in porque


def test_atrasado_DENTRO_da_janela_ainda_sai():
    """Maquina desligada as 7h e ligada as 9h: o relatorio ainda serve."""
    pode, _ = agenda.deve_rodar(_ag(), datetime(2026, 8, 27, 9, 0))
    assert pode


def test_atrasado_FORA_da_janela_nao_sai():
    """Relatorio da manha chegando a noite ensina a ignorar o remetente."""
    pode, porque = agenda.deve_rodar(_ag(), datetime(2026, 8, 27, 22, 0))
    assert not pode and "janela" in porque


def test_semanal_so_no_dia_marcado():
    ag = _ag(frequencia="semanal", dia_semana=3)          # quarta
    assert agenda.deve_rodar(ag, datetime(2026, 8, 26, 8, 0))[0]
    assert not agenda.deve_rodar(ag, datetime(2026, 8, 27, 8, 0))[0]


def test_mensal_nao_aceita_dia_29_a_31():
    """29, 30 e 31 nao existem em todo mes: um mensal marcado no dia 31 nao
    sairia em fevereiro nenhum, e o usuario nunca saberia por que."""
    with pytest.raises(ValueError, match="1 a 28"):
        agenda.validar({"relatorio": "digest", "destinatarios": "a@b.com",
                        "frequencia": "mensal", "dia_mes": 31})


def test_hora_ilegivel_e_RECUSADA_na_gravacao():
    """Recusar aqui e nao no envio: erro que so aparece na rotina
    desassistida e erro que ninguem ve."""
    # string VAZIA nao entra: campo em branco cai no padrao das 07:00, que e
    # o comportamento gentil e esperado de um formulario.
    for ruim in ("7h", "25:00", "07:99", "7:00:00"):
        with pytest.raises(ValueError):
            agenda.validar({"relatorio": "digest", "destinatarios": "a@b.com",
                            "hora": ruim})


def test_relatorio_desconhecido_e_recusado():
    with pytest.raises(ValueError, match="desconhecido"):
        agenda.validar({"relatorio": "inventado", "destinatarios": "a@b.com"})


def test_destinatario_invalido_e_recusado():
    with pytest.raises(ValueError, match="nv"):
        agenda.validar({"relatorio": "digest", "destinatarios": "nao-e-email"})


def test_sem_destinatario_e_recusado():
    with pytest.raises(ValueError, match="destinat"):
        agenda.validar({"relatorio": "digest", "destinatarios": " "})


def test_gravar_exige_autor():
    """Trilha em que o autor vem do cliente nao serve de trilha."""
    with pytest.raises(ValueError, match="Informe quem"):
        agenda.gravar({"relatorio": "digest", "destinatarios": "a@b.com"}, "")


def test_hora_ilegivel_no_banco_nao_derruba_a_rotina():
    """Configuracao corrompida faz UM agendamento parar, nunca os outros."""
    pode, _ = agenda.deve_rodar(_ag(hora="quinze horas"))
    assert not pode


def test_proxima_execucao_e_no_futuro():
    p = agenda.proxima(_ag(), datetime(2026, 8, 27, 9, 0))
    assert p and p > "2026-08-27 09:00"


def test_desligado_nao_tem_proxima():
    """Prometer "proximo envio" para quem esta desligado e mentir na tela."""
    assert agenda.proxima(_ag(ativo=False)) is None


def test_descricao_le_como_frase():
    assert agenda.descrever(_ag()) == "todo dia às 07:00"
    assert "quarta" in agenda.descrever(
        _ag(frequencia="semanal", dia_semana=3))
    assert "dia 5" in agenda.descrever(_ag(frequencia="mensal", dia_mes=5))
