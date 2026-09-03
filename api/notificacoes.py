# -*- coding: utf-8 -*-
"""Notificações do CÓRTEX — o que o sistema tem a dizer a UMA pessoa.

O DESENHO, EM UMA FRASE
=======================
A notificação é **derivada a cada leitura**; o que se grava é apenas o que a
pessoa já dispensou. Não existe fila, não existe rotina que cria linha, e não
existe o estado "pendente" em lugar nenhum.

A razão é a mesma que já vale para o atraso de ação da Gestão, a vigência de
contrato do CRM e o "cliente ativo" lido do faturamento: **estado que
envelhece sozinho se calcula, não se grava**. Uma fila precisaria de alguém
para enfileirar, e no dia em que essa rotina não rodasse o usuário novo
entraria sem receber nada — sem erro, sem alarme, sem ninguém saber. É o
mesmo formato do marcador de manutenção parado em 77.534 km.

O CORolário incômodo, dito de propósito: **isto não serve para tudo.** Uma
notificação de evento — "a coleta da Gobrax falhou às 3h" — não é derivável do
estado atual, porque o evento passou. Quando ela existir, será uma tabela de
EVENTOS ao lado desta, e não uma adaptação desta. Escrever isso agora evita
que a próxima pessoa force um caso no molde errado.

O QUE JÁ EXISTE
===============
`boas_vindas`: aparece para quem nunca a dispensou. É a primeira e serve de
forma para as próximas.
"""
from __future__ import annotations

import logging
import re

from api import pglocal

log = logging.getLogger(__name__)

# O teste redireciona para um schema proprio (fixture `esquema_pg`), que e o
# padrao da casa para modulo que escreve no banco local.
ESQUEMA: str | None = None


def _esq(esquema: str | None) -> str | None:
    return esquema if esquema is not None else ESQUEMA

# As chaves conhecidas. A lista existe para a rota RECUSAR chave inventada:
# sem ela, um `POST` com `chave="qualquer"` gravaria lixo na tabela para
# sempre, e a tabela é justamente o que decide se algo aparece ou não.
CHAVES = ("boas_vindas",)


def _lidas(usuario_id: int, esquema: str | None = None) -> set[str]:
    linhas = pglocal.query(
        "SELECT chave FROM not_lidas WHERE usuario_id = %s", (usuario_id,),
        esquema=_esq(esquema))
    return {r["chave"] for r in linhas}


def _boas_vindas(sessao: dict) -> dict:
    """A mensagem de estreia.

    O primeiro nome, e não o nome inteiro: "Bem-vindo ao CÓRTEX, MARCOS
    ANTONIO CASSOLI DA SILVA" é um cabeçalho de cadastro, não um cumprimento.
    """
    nome = (sessao.get("nome") or "").strip()
    primeiro = nome.split()[0].title() if nome else ""
    return {
        "chave": "boas_vindas",
        "tipo": "boas_vindas",
        "titulo": "Bem-vindo ao CÓRTEX" + (f", {primeiro}" if primeiro else ""),
        "texto": (
            "Este é o painel de gestão da Sulista: operação, frota, "
            "financeiro e comercial no mesmo lugar. O menu à esquerda agrupa "
            "as telas por área, e a estrela ao lado do título fixa as que "
            "você mais usa no topo."
        ),
        # A dica que economiza a primeira dúvida de todo mundo: onde fica a
        # explicação de cada número. O ⓘ de procedência é o que diferencia
        # este painel de uma planilha bonita, e ninguém o descobre sozinho.
        "dica": (
            "Todo cartão tem um ⓘ no título dizendo de que tabela o número "
            "sai e como ele é calculado — passe o mouse nele quando um valor "
            "surpreender."
        ),
        "acao": {"rotulo": "Abrir a documentação", "view": "doc"},
    }


def listar(sessao: dict, esquema: str | None = None) -> dict:
    """As notificações desta pessoa, agora.

    Devolve `nao_lidas` porque é o número do sino, e ele NÃO é o tamanho da
    lista: uma notificação dispensada some da lista, mas o dia em que houver
    notificação que fica visível depois de lida (um aviso permanente, por
    exemplo) os dois números passam a divergir — e o sino tem de contar o que
    pede atenção, não o que existe.
    """
    uid = sessao.get("id")
    if not uid:
        return {"itens": [], "nao_lidas": 0}
    try:
        lidas = _lidas(uid, esquema)
    except Exception as exc:                       # pragma: no cover
        # Sino quebrado não pode derrubar a barra de topo, que é o que segura
        # o menu inteiro. Degrada para "sem notificação" e registra.
        log.warning("notificacoes: %s: %s", type(exc).__name__, exc)
        return {"itens": [], "nao_lidas": 0, "erro": True}

    itens = []
    # Suporte: itens DERIVADOS do estado do chamado (somem ao abrir a conversa).
    # Falha lá não pode derrubar o sino, que segura a barra de topo inteira.
    try:
        from .suporte import avisos as _sup
        itens += [i for i in _sup.notificacoes(sessao, _esq(esquema))
                  if not i["chave"].startswith("sup_fila:") or i["chave"] not in lidas]
    except Exception as exc:  # noqa: BLE001
        log.warning("notificacoes suporte: %s", type(exc).__name__)
    if "boas_vindas" not in lidas:
        itens.append(_boas_vindas(sessao))
    return {"itens": itens, "nao_lidas": len(itens)}


def marcar_lida(usuario_id: int, chave: str,
                esquema: str | None = None) -> bool:
    """Dispensa uma notificação. Idempotente por construção.

    `ON CONFLICT DO NOTHING` sobre o UNIQUE (usuario_id, chave): dois cliques
    no botão não criam duas linhas, e a rota não precisa saber disso.
    """
    # `sup:<id>` é a marca de leitura do chamado (não grava em not_lidas: duas
    # verdades sobre "lido"); `sup_fila:<n>` é dispensável como as demais.
    m = re.match(r"^sup:(\d+)$", chave)
    if m:
        from .suporte import chamados as _ch
        return _ch.marcar_lido(int(m.group(1)), "usuario", usuario_id, _esq(esquema))
    if chave not in CHAVES and not re.match(r"^sup_fila:\d+$", chave):
        return False
    pglocal.executar(
        "INSERT INTO not_lidas (usuario_id, chave) VALUES (%s, %s) "
        "ON CONFLICT (usuario_id, chave) DO NOTHING",
        (usuario_id, chave), esquema=_esq(esquema))
    return True
