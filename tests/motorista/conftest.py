# -*- coding: utf-8 -*-
"""Bancada do app do motorista: schema descartável e um WhatsApp de mentira.

O REDIRECIONAMENTO DE SCHEMA É DE SEGURANÇA, não de higiene. Em 01/09/2026 os
testes da Monkey redirecionaram um módulo e esqueceram o outro, e cinco rodadas
da suíte escreveram dado de dublê dentro de `cortex.*` em PRODUÇÃO — com a
suíte verde, e o sintoma aparecendo numa tela dias depois. Aqui são DOIS:
`motorista.ESQUEMA` (vínculo, código, sessão) e `auth.ESQUEMA` (o `audit_log`,
que a rota de entrada escreve).
"""
from __future__ import annotations

import pytest

from api import auth, motorista, pglocal


@pytest.fixture
def esq(esquema_pg, monkeypatch):
    monkeypatch.setattr(motorista, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    return esquema_pg


@pytest.fixture
def zap(monkeypatch):
    """Dublê da Z-API que COPIA O CORPO REAL de `whatsapp.envio.enviar`.

    Campos "inúteis" inclusive (`message_id`, `instancia`, `tipo`): dublê mais
    pobre que o real é como um caminho de erro passa despercebido — quem lê o
    retorno acha que ele tem uma chave que na vida real ele não tem, ou o
    contrário. Guarda o texto para o teste provar que o código SAIU na
    mensagem, e nada mais o guarda em lugar nenhum.
    """
    from api.motorista import entrada as ment
    enviadas: list[dict] = []

    def falso(telefone, mensagem, **kw):
        enviadas.append({"telefone": telefone, "mensagem": mensagem, **kw})
        return {"ok": True, "telefone": telefone, "erro": "",
                "message_id": "3EB0" + str(len(enviadas)),
                "instancia": "principal", "tipo": "telefone"}

    monkeypatch.setattr(ment.wa, "enviar", falso)
    return enviadas


def cadastrar(esquema: str, codigo: str, telefone: str, nome: str = "Fulano",
              ativo: bool = True) -> None:
    pglocal.executar(
        """INSERT INTO mot_vinculos(motorista_codigo, telefone, nome, ativo)
           VALUES (%(c)s, %(f)s, %(n)s, %(a)s)""",
        {"c": codigo, "f": telefone, "n": nome, "a": ativo}, esquema)


def codigo_enviado(enviadas: list[dict]) -> str:
    """Os 6 dígitos que saíram na ÚLTIMA mensagem.

    O teste tem de pescar o código do texto porque não há outro lugar de onde
    tirá-lo: no banco só existe o SHA-256. Isso não é inconveniência do teste —
    é a prova de que o código não está gravado.
    """
    import re
    m = re.search(r"\b(\d{6})\b", enviadas[-1]["mensagem"])
    assert m, "a mensagem não trouxe um código de 6 dígitos"
    return m.group(1)
