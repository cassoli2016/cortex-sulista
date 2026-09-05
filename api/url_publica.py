# -*- coding: utf-8 -*-
"""ONDE O CÓRTEX MORA, para quem está de fora.

UM LUGAR SÓ, e este módulo existe porque não era. O endereço público mudou de
`cortex.cassolitech.com.br` para `cortex.sulista.com.br` em 09/2026, e no dia
seguinte à troca uma pessoa recebeu, no mesmo WhatsApp e com dez minutos de
diferença, o resumo diário apontando para o domínio VELHO e o aviso de carga
apontando para o novo. O rastreio tinha sido feito com o endereço configurável;
o resumo diário e o aviso do suporte tinham a constante cravada no código, cada
um no seu arquivo.

O sintoma foi visual e inofensivo desta vez — os dois domínios ainda respondem.
Não seria inofensivo no dia em que o antigo for desligado: o link simplesmente
para de abrir, no celular de quem não tem como saber por quê, e ninguém aqui
fica sabendo.

LIDO A CADA CHAMADA, nunca no import: trocar a variável de ambiente não deve
exigir reiniciar a API, e é isso que permite o teste trocá-la.
"""
from __future__ import annotations

import os

PADRAO = "https://cortex.sulista.com.br"

#: A variável nova e a antiga, nesta ordem. `RASTREIO_URL_BASE` nasceu antes
#: deste módulo e pode estar num `.env` de produção — ignorá-la faria a
#: unificação MUDAR o endereço de quem já tinha configurado.
VARIAVEIS = ("CORTEX_URL_BASE", "RASTREIO_URL_BASE")


def base() -> str:
    """A raiz do endereço público, sem barra no fim."""
    for nome in VARIAVEIS:
        v = (os.environ.get(nome) or "").strip()
        if v:
            return v.rstrip("/")
    return PADRAO


def painel() -> str:
    """O link para o painel. Cai no login de sempre — o link não abre nada
    sozinho, e é por isso que ele pode ir num WhatsApp."""
    return base()


def tela(chave: str, **params) -> str:
    """O link de uma tela do painel, pelo roteador de hash.

    `#` e não `?`: o roteador da casa é por hash, e o que vem depois dele não
    chega ao servidor nem ao log do proxy.
    """
    q = "&".join("%s=%s" % (k, v) for k, v in params.items() if v is not None)
    return "%s/#%s%s" % (base(), chave, ("?" + q) if q else "")
