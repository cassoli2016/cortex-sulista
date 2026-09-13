"""Sem senha do ERP, a consulta recusa NA HORA — não em 15 s.

Até 12/09/2026, sem `POSTGRES_PASSWORD` o pool tentava o endereço padrão e só
desistia no `timeout` de 15 s, a cada consulta. Na produção isso nunca aparece
(a senha está no `.env`); no CI e no clone de desenvolvedor aparecia em tudo:
uma fatia do CI estourou os 30 min esperando o ERP que não existe, e cada
tela que lê o ERP pendurava 15 s para dizer "não há ERP aqui".

A recusa precisa ser RÁPIDA e dizer O QUE FALTA — "instalação incompleta", não
"o ERP caiu", que é outra coisa e pede outra reação de quem lê.
"""
from __future__ import annotations

import time

import pytest

from api import db


def test_sem_senha_o_erp_recusa_na_hora_dizendo_o_que_falta(monkeypatch):
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    t0 = time.monotonic()
    with pytest.raises(db.ErpNaoConfigurado, match="POSTGRES_PASSWORD"):
        db.query("SELECT 1")
    assert time.monotonic() - t0 < 2, "recusou, mas depois de esperar o pool"


def test_senha_em_branco_conta_como_ausente(monkeypatch):
    """`POSTGRES_PASSWORD=` com espaço é o `.env` recém-copiado do modelo."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "   ")
    assert not db.configurado()
    monkeypatch.setenv("POSTGRES_PASSWORD", "x")
    assert db.configurado()
