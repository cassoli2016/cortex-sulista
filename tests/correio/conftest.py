"""Isolamento dos testes de correio.

MEUS TESTES LIAM O BANCO DE PRODUÇÃO. `relatorios.montar()` monta o relatório
de verdade, e montar significa consultar o AVA, o registro de emissões e a
configuração da automação — dados reais, na base real. Era leitura, então nada
foi corrompido, mas duas coisas ruins vinham junto:

1. A suíte ficava dependente do estado do dia. "Passou" às 17h e "falhou" às
   18h porque a fila mudou não é teste, é termômetro.
2. Rodando `tests/correio` antes de `tests/contrapartida`, dois testes de lá
   quebravam. O diretório vizinho já tinha ganhado uma fixture de isolamento;
   o meu não, e a interferência só aparecia na ordem alfabética — que é
   exatamente a ordem em que o CI roda.

A fixture é `autouse` pelo mesmo motivo que a do vizinho: teste novo nasce
isolado sem ninguém precisar lembrar.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isola_correio(request, monkeypatch):
    """Redireciona a agenda e a trilha para um schema descartável.

    Sem banco, os testes que dependem dele pulam dizendo por quê — os de
    layout do e-mail (a maioria) não tocam em banco nenhum e continuam
    valendo.
    """
    ok, _motivo = request.getfixturevalue("pg_disponivel")
    if not ok:
        return None
    esquema = request.getfixturevalue("esquema_pg")
    from api.correio import agenda, registro
    monkeypatch.setattr(agenda, "ESQUEMA", esquema)
    monkeypatch.setattr(registro, "ESQUEMA", esquema)
    return esquema
