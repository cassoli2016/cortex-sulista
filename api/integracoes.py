# -*- coding: utf-8 -*-
"""A Central de Integrações — um lugar por fornecedor, e não três.

POR QUE ESTA TELA EXISTE
========================

Hoje a resposta para "a integração X está bem?" mora em três lugares, e nenhum
deles responde a pergunta inteira:

1. **Gestão › Integrações** (`api/credenciais.py`) diz se está CONFIGURADA —
   qual modo de autenticação está completo, o que falta preencher. Não sabe se
   chegou dado.
2. **Saúde do Servidor** (`api/servidor.py`) diz se está CHEGANDO DADO — última
   coleta, idade, volume. Mas os cartões dos fornecedores dividem a tela com
   CPU, disco, GPU, bancos e túnel, e ali a pergunta é "o servidor está bem?".
3. **O código** sabe o que cada uma alimenta, e ninguém mais.

Uma integração pode estar configurada e parada há cinco dias. Pode estar
chegando dado com a credencial da premiação faltando. Nenhuma das duas telas
mostra as duas metades juntas, e é a JUNÇÃO que responde se dá para confiar no
número que a tela de Telemetria está mostrando agora.

Este módulo é a junção. Ele não coleta nada e não guarda estado: lê as duas
fontes que já existem e as casa por fornecedor.

O QUE ELE NÃO FAZ, DE PROPÓSITO
-------------------------------

**Não mostra e não edita segredo.** Trocar token continua sendo em Gestão, que
é admin. Esta tela diz "falta o token", nunca qual é — é o que permite ela ser
tela de RBAC normal, aberta para quem opera.

**Não dispara coleta.** A pergunta é sobre o que JÁ aconteceu. Uma tela de
monitoramento que bate no fornecedor a cada pintura vira carga, e a casa já tem
a regra: fonte de painel jamais dispara coleta externa.

A PONTE ENTRE AS DUAS FONTES
----------------------------

`CARTAO_DA_SAUDE` casa a chave do fornecedor (a do cofre de credenciais) com o
NOME do cartão na Saúde. É um mapa escrito à mão, e mapa escrito à mão foi o
que já deixou dois guards cegos nesta casa esta semana — por isso
`tests/test_integracoes.py` confere os DOIS lados: todo nome mapeado existe
entre os cartões da Saúde, e todo fornecedor EXTERNO do cofre está mapeado.
Renomear um cartão lá derruba a suíte aqui, com o nome antigo no erro.
"""
from __future__ import annotations

import logging

log = logging.getLogger("cortex.integracoes")

#: Fornecedor externo × nome do cartão na Saúde do Servidor.
#:
#: Ausente aqui = fornecedor sem medição de chegada. Não é erro: o TomTom é
#: consultado sob demanda (não há coleta que possa "parar"), e o SMTP só se
#: prova no envio. O cartão diz isso em vez de fingir um semáforo.
CARTAO_DA_SAUDE: dict[str, str] = {
    "gobrax": "Gobrax (telemetria)",
    "smartec": "Smartec (infrações e licenças)",
    "rasterjor": "Jornada (RasterJOR)",
    "rasterintegra": "RasterIntegra (ger. de risco)",
    "prolog": "Prolog (pneus)",
    "monkey": "Monkey (antecipação Tupy)",
    "zapi": "Z-API (WhatsApp)",
    "tress": "3S (rastreamento das carretas)",
    "tomtom": "TomTom (trânsito)",
}

#: O que está no cofre de credenciais mas NÃO é fornecedor externo.
#: `cortex` é o endereço do próprio painel; `motorista_mestre` é um segredo
#: NOSSO. Os dois estão lá porque é lá que a tela de configuração lê — e sem
#: esta lista eles apareceriam aqui como integrações que nunca respondem.
NAO_SAO_FORNECEDOR = frozenset({"cortex", "motorista_mestre"})

#: Fornecedor sem coleta periódica: não há "última coleta" para envelhecer.
#: Dizer "sem dado" deles seria alarme falso todo dia.
SOB_DEMANDA: dict[str, str] = {
    "tomtom": "consultado na hora, por viagem — não há coleta que possa parar",
    "qualp": "consultado na hora, por rota — não há coleta que possa parar",
    "smtp": "só se prova no envio; a falha aparece na fila do Correio",
}

#: Ordem do semáforo, do pior para o melhor. O cartão vale o PIOR dos dois
#: lados: configuração ativa com coleta parada há cinco dias não é "ok".
_PESO = {"erro": 0, "alerta": 1, "info": 2, "ok": 3}


def _pior(*estados: str | None) -> str:
    validos = [e for e in estados if e in _PESO]
    return min(validos, key=lambda e: _PESO[e]) if validos else "info"


def _cartoes_por_nome(cartoes: list[dict]) -> dict[str, dict]:
    return {c.get("nome", ""): c for c in cartoes}


def panorama(cartoes: list[dict] | None = None) -> dict:
    """Uma linha por fornecedor, com as duas metades casadas.

    `cartoes` é a saída de `servidor._servicos()`. Entra por parâmetro para o
    teste poder montar o caso sem subir a Saúde inteira — e para a rota poder
    reaproveitar uma coleta que já tenha em mãos.
    """
    from api import credenciais

    if cartoes is None:
        from api import servidor
        try:
            cartoes = servidor._servicos()
        except Exception as exc:  # noqa: BLE001
            log.warning("integracoes: a Saude nao respondeu: %s", type(exc).__name__)
            cartoes = []
    por_nome = _cartoes_por_nome(cartoes)

    linhas: list[dict] = []
    for svc in credenciais.panorama():
        chave = svc["chave"]
        if chave in NAO_SAO_FORNECEDOR:
            continue

        nome_cartao = CARTAO_DA_SAUDE.get(chave)
        cartao = por_nome.get(nome_cartao) if nome_cartao else None

        # A CHEGADA TEM QUATRO RESPOSTAS, e "não sei" é uma delas.
        #
        # Sem esta separação, fornecedor sob demanda e fornecedor com coleta
        # parada cairiam no mesmo cinza — e é a diferença entre "está certo
        # assim" e "alguém precisa olhar hoje".
        if chave in SOB_DEMANDA:
            chegada = {"regime": "sob_demanda", "status": "info",
                       "detalhe": SOB_DEMANDA[chave]}
        elif cartao is not None:
            chegada = {"regime": "coleta", "status": cartao.get("status", "info"),
                       "detalhe": cartao.get("detalhe", "")}
        else:
            chegada = {"regime": "sem_medicao", "status": "info",
                       "detalhe": "esta integração ainda não tem medição de "
                                  "chegada na Saúde do Servidor"}

        # A CONFIGURAÇÃO VIRA SEMÁFORO AQUI, e "desligada" NÃO é vermelho:
        # integração que ninguém contratou não é defeito, é recurso que não
        # existe nesta instalação. Pintar de vermelho o que está certo é como
        # se ensina a ignorar vermelho.
        conf = {"ativa": "ok", "incompleta": "alerta",
                "desligada": "info"}.get(svc["estado"], "info")

        linhas.append({
            "chave": chave,
            "nome": svc["nome"],
            "resumo": svc["resumo"],
            "alimenta": svc["alimenta"],
            "estado": _pior(conf, chegada["status"]),
            "configuracao": {"estado": svc["estado"], "status": conf,
                             "falta": svc["falta"], "modo": svc["modo_ativo"],
                             "regime": svc.get("regime")},
            "chegada": chegada,
        })

    linhas.sort(key=lambda l: (_PESO.get(l["estado"], 9), l["nome"].lower()))
    return {
        "integracoes": linhas,
        "resumo": {
            "total": len(linhas),
            "ok": sum(1 for l in linhas if l["estado"] == "ok"),
            "atencao": sum(1 for l in linhas if l["estado"] in ("alerta", "erro")),
            "sem_medicao": sum(1 for l in linhas
                               if l["chegada"]["regime"] == "sem_medicao"),
        },
    }
