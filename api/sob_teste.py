# -*- coding: utf-8 -*-
"""Este processo é uma rodada de testes?

A PERGUNTA VALE UMA MENSAGEM NO CELULAR DE ALGUÉM, e em 06/09/2026 por pouco
não custou. `TestClient` dispara o `@app.on_event("startup")` — a mesma porta
por onde a suíte já aplicava migration no banco de produção — e o startup sobe
as threads de agendador. Nesta bancada o WhatsApp e o push estão configurados
DE VERDADE, então o gate de credencial não segura nada: uma suíte de 35 minutos
manda aviso REAL, sem ninguém ter pedido.

Como apareceu: um `RuntimeError` no log da API de produção cuja causa era o
`monkeypatch` de um teste. A thread de um processo de teste, viva, escrevendo
no log da casa.

`"pytest" in sys.modules` E NESTA ORDEM, antes da variável de ambiente. A
`PYTEST_CURRENT_TEST` só existe DURANTE um teste; na coleta, ou numa fixture de
módulo que monta o `TestClient` uma vez para o arquivo inteiro, ela não está lá
— e é justamente aí que o startup costuma rodar. Sozinha, ela deixaria passar
exatamente o caso que se quer barrar.

Variável de ambiente também não serve como mecanismo principal por outro
motivo: exige que alguém lembre de exportá-la, e quem esquece descobre pelo
cliente.

ESTE MÓDULO É NEUTRO DE PROPÓSITO. A regra é de segurança e não pode virar uma
cópia por agendador — no dia em que ela precisar mudar (outro runner, outra
forma de detectar), tem de haver um lugar só para mudar. `api/rastreio/agendador.py`
tem hoje a sua própria cópia, escrita antes desta; ela e esta dizem a mesma
coisa, e a de lá deve passar a delegar para cá.
"""
from __future__ import annotations

import os
import sys


def sob_teste() -> bool:
    """True se este processo for uma rodada de pytest. Ver o docstring acima."""
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))
