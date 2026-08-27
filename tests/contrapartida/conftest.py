"""Isolamento do banco para os testes de contrapartida.

ESTES TESTES ESCREVIAM NO BANCO DE PRODUÇÃO. Não é regressão da migração para o
PostgreSQL — era assim antes também, com o `data/contrapartida.db` real: nenhum
deles redirecionava o banco, então `config_grava`, `_registra` e o cadastro
gravavam na base de verdade. Ficou visível na migração porque um teste passou a
depender do estado que o outro deixou.

Num módulo FISCAL isso é sério: `lote_config` guarda os interruptores que
liberam emissão em produção, e `emissao` é a numeração dos documentos. Teste
que grava ali pode ligar o que estava desligado ou queimar um número.

A fixture é `autouse`: vale para todo o diretório, e teste novo nasce isolado
sem ninguém lembrar de pedir. Sem banco, pula dizendo por quê.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isola_contrapartida(request, monkeypatch):
    # `pg_disponivel`/`esquema_pg` vivem em tests/conftest.py
    ok, motivo = request.getfixturevalue("pg_disponivel")
    if not ok:
        pytest.skip(motivo)
    esquema = request.getfixturevalue("esquema_pg")
    from api.contrapartida import cadastro
    monkeypatch.setattr(cadastro, "ESQUEMA", esquema)
    return esquema
