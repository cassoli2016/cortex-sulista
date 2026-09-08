# -*- coding: utf-8 -*-
"""A coleta do cadastro: junta o ERP e a Smartec e reconstrói o consolidado.

NENHUMA DAS DUAS FONTES CUSTA CHAMADA AQUI
==========================================
As duas leem do banco: o ERP pelo `api/db.py` (réplica somente leitura) e a
Smartec pelas tabelas `smt_*` que a coleta dela já enche todo dia. Por isso
esta rotina pode rodar quantas vezes quiser — e por isso ela roda inteira
depois de qualquer mudança, em vez de tentar ser esperta sobre o que mudou.

Quem fala com o fornecedor é `api/smartec/coleta.py`. A separação é o que
permite reconstruir o cadastro com a Smartec fora do ar, e testar a
consolidação — que é a regra difícil — sem rede nenhuma.

A ORDEM É ERP DEPOIS SMARTEC, E NÃO IMPORTA
===========================================
A precedência é do CATÁLOGO (`campos.py`), não da ordem de gravação: cada
fonte grava a sua linha em `eqp_fonte` e a consolidação decide depois. Gravar
fora de ordem não muda um campo — e isso é de propósito, porque coleta que
depende de ordem quebra no dia em que uma delas falha.
"""
from __future__ import annotations

import logging

from . import armazenamento as arm
from . import consolidacao, erp, smartec

log = logging.getLogger("cortex.equipamentos")

#: A ordem em que a frota é varrida quando alguma coisa é feita por fase.
FASES: tuple[str, ...] = ("proprio", "agregado", "terceiro")


def sincronizar_erp() -> dict:
    """Traz a frota ativa do ERP para `eqp_fonte` e reconstrói o cadastro."""
    linhas = erp.ler()
    gravadas = arm.gravar_fontes(erp.FONTE, linhas)
    resultado = consolidacao.reconstruir()
    log.info("equipamentos: %d do ERP, %d consolidados",
             gravadas, resultado["equipamentos"])
    return {"lidos_do_erp": gravadas, **resultado}


def sincronizar_smartec() -> dict:
    """Traz o que a Smartec já coletou para `eqp_fonte` e reconsolida."""
    r = smartec.sincronizar()
    resultado = consolidacao.reconstruir()
    return {**r, **resultado}


def sincronizar() -> dict:
    """As duas fontes e a consolidação, numa passagem.

    É o que o botão da tela chama e o que uma tarefa agendada chamaria.
    A consolidação roda UMA vez no fim, e não uma por fonte: reconstruir 1.446
    equipamentos duas vezes seguidas daria o mesmo resultado e o dobro do
    trabalho.
    """
    do_erp = arm.gravar_fontes(erp.FONTE, erp.ler())
    da_smartec = arm.gravar_fontes(smartec.FONTE, smartec.ler())
    resultado = consolidacao.reconstruir()
    log.info("equipamentos: ERP %d, Smartec %d, consolidados %d",
             do_erp, da_smartec, resultado["equipamentos"])
    return {"lidos_do_erp": do_erp, "lidos_da_smartec": da_smartec,
            **resultado, "cobertura_smartec": smartec.cobertura()}
