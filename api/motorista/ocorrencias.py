# -*- coding: utf-8 -*-
"""O que a casa registrou sobre ele — as ocorrências de motorista do ERP.

═══════════════════════════════════════════════════════════════════════════
POR QUE ISTO É A TELA MAIS DELICADA DO APP
═══════════════════════════════════════════════════════════════════════════
As outras mostram fatos do mundo (uma viagem, um consumo, uma multa de órgão
público). Esta mostra o que COLEGAS DELE escreveram a respeito dele, num
sistema que ele nunca viu, e que pesa na premiação — que é salário indireto.

Daí três decisões que valem mais que o código:

**1. O texto livre NÃO SAI.** `observacao`, `acaoimediataconterproblema` e a
`reclamacao` ficam no ERP. São campos escritos por gente, sem revisão, para
consumo interno, e podem carregar nome de terceiro, opinião e versão de um
lado só de uma discussão. O que sai é o TIPO (que é cadastro, tem descrição
própria e é o mesmo para todo mundo), a data, o veículo e se já foi tratada.
Decidido por quem opera em 07/09/2026, com a alternativa na mesa.

**2. "Demérito" NÃO É DITO A ELE, hoje.** A classe de cada tipo mora em
`prem_ocorrencia_classe` e decide dinheiro na premiação — mas medido em
07/09/2026, **40 dos 54 tipos ainda estão com a PROPOSTA automática** e só 14
foram decididos por uma pessoa. Chamar de demérito, na cara do premiado, uma
classe que ninguém confirmou é transformar um rascunho nosso em veredito
sobre o salário dele. O que se destaca é o MÉRITO, e só quando um humano
classificou: elogio dito a mais ninguém não faz mal a ninguém, e reconhecer é
metade da razão de a tela existir.

**3. `situacao` É CÓDIGO SEM TABELA DE DOMÍNIO — e não vira rótulo
inventado.** Medido sobre 24 meses: situação 3 são 1.261 linhas com 1.170
(92,8%) trazendo `dtsolucao`; situação 1 são 292 com 20 (6,8%); a 2 são 12
linhas. A leitura óbvia é "3 = encerrada", e ela é uma INFERÊNCIA — não há
tabela que diga isso. Então a tela não escreve "encerrada": ela diz "tratada
em DD/MM" quando existe `dtsolucao`, que é um fato, e cala quando não existe.
O código cru viaja no payload para quem administra conferir.

═══════════════════════════════════════════════════════════════════════════
A FONTE
═══════════════════════════════════════════════════════════════════════════
`cadastro_vinculo_motoristaocorrencia` (AVA), chaveada por `cnpjcpfcodigo` —
que é o `cadastro.codigo`, o mesmo `motorista_codigo` do vínculo. Medido em
07/09/2026: 44 dos 80 vinculados têm ocorrência em doze meses.

`regexp_replace(…, '[^ -ÿ]', '', 'g')` NA DESCRIÇÃO, e o filtro é exatamente
esse: o AVA é LATIN1 e uma descrição tem aspa tipográfica UTF-8 que não
converte — a consulta morre em `UntranslatableCharacter` só quando lista
tudo, e passa com `LIMIT 10`. A primeira versão desse filtro no módulo da
premiação tirava TODO não-ASCII e quebrou a classificação em silêncio
("MÉRITO" virou "MRITO"). Fora do LATIN1 é acima de U+00FF, e só.

CACHE COM ÚLTIMA LEITURA BOA (a janela da casa, 2 h): a menor faixa que esta
tela publica é um DIA, então a leitura de duas horas atrás não muda nada do
que está aqui — é o critério de `tests/test_leitura_velha.py`, e é o mesmo de
`viagem.py`.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from .. import db, pglocal
from ..queries import VELHA_ATE, cached

log = logging.getLogger("cortex.motorista.ocorrencias")

#: Janela da lista. Doze meses porque é o ciclo de avaliação da operação e é o
#: que a premiação usa como histórico.
DIAS = 365

#: Janela do destaque "recentes" no resumo.
DIAS_RECENTE = 30

_SQL = """
SELECT m.dt::date                                                   AS data,
       m.dtsolucao::date                                            AS solucao,
       m.ocorrenciamotorista                                        AS codigo,
       regexp_replace(coalesce(o.descricao,''), '[^ -ÿ]', '', 'g')  AS tipo,
       coalesce(nullif(trim(m.veiculo),''),'')                      AS veiculo,
       m.situacao                                                   AS situacao
  FROM cadastro_vinculo_motoristaocorrencia m
  LEFT JOIN ocorrenciamotorista o ON o.codigo = m.ocorrenciamotorista
 WHERE m.cnpjcpfcodigo = %(mot)s
   AND m.dt >= current_date - %(dias)s
 ORDER BY m.dt DESC
"""


def _esq(esquema: str | None = None) -> str | None:
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


def _meritos(esquema: str | None) -> set[int]:
    """Os tipos que uma PESSOA classificou como mérito.

    A proposta automática não entra: ela é um rascunho nosso, e um rascunho
    que vira elogio na tela é tão errado quanto um que vira demérito — só é
    menos perigoso. `atualizado_por` com '@' é a assinatura de quem decidiu
    (a proposta grava 'proposta').

    Sem a tabela (banco novo, migration da premiação não aplicada) o resultado
    é conjunto vazio: a lista sai sem destaque nenhum, que é a degradação
    certa — nunca uma exceção que derruba a tela inteira por causa do enfeite.
    """
    try:
        linhas = pglocal.query(
            """SELECT codigo FROM prem_ocorrencia_classe
                WHERE classe = 'merito' AND atualizado_por LIKE '%%@%%'""",
            esquema=esquema)
    except Exception as exc:  # noqa: BLE001
        log.info("classe de ocorrência indisponível: %s", type(exc).__name__)
        return set()
    return {int(l["codigo"]) for l in linhas if l["codigo"] is not None}


def _d(v) -> str | None:
    if isinstance(v, datetime):
        v = v.date()
    return v.isoformat() if isinstance(v, date) else None


@cached(ttl=300, velha_ate=VELHA_ATE)
def _consultar(motorista_codigo: str) -> dict:
    """DEVOLVE DICIONÁRIO, e a lista vai DENTRO dele — isto não é estilo.

    `cached(velha_ate=)` só serve a última leitura boa quando o que guardou é
    um `dict` (`isinstance(hit[1], dict)`); devolvendo uma lista, a rede
    simplesmente não existe e a exceção sobe — a tela morre no dia ruim do ERP,
    em silêncio, sem nada acusar que a proteção nunca esteve ligada.
    """
    return {"linhas": [dict(r) for r in db.query(
        _SQL, {"mot": str(motorista_codigo), "dias": DIAS})]}


def minhas(sessao: dict, esquema: str | None = None) -> dict:
    """As ocorrências de QUEM ESTÁ LOGADO. O código sai da sessão."""
    bruto = _consultar(str(sessao["motorista_codigo"]))
    linhas = bruto["linhas"]
    meritos = _meritos(_esq(esquema))
    hoje = date.today()

    itens, recentes, sem_solucao = [], 0, 0
    for l in linhas:
        d = _d(l["data"])
        item = {
            "data": d,
            "tipo": (l["tipo"] or "").strip() or "Ocorrência sem descrição no cadastro",
            "codigo": l["codigo"],
            "veiculo": l["veiculo"],
            "tratada_em": _d(l["solucao"]),
            # O código cru viaja; o rótulo NÃO é inventado (ver o docstring).
            "situacao_codigo": l["situacao"],
            "merito": l["codigo"] in meritos,
        }
        itens.append(item)
        if d and (hoje - date.fromisoformat(d)).days <= DIAS_RECENTE:
            recentes += 1
        if not item["tratada_em"]:
            sem_solucao += 1

    return {
        "itens": itens,
        "resumo": {
            "total_12m": len(itens),
            "recentes_30d": recentes,
            "sem_solucao": sem_solucao,
            "meritos": sum(1 for i in itens if i["merito"]),
        },
        "janela_dias": DIAS,
        "recente_dias": DIAS_RECENTE,
        "fonte": "ERP AVA · cadastro_vinculo_motoristaocorrencia",
        # O CARIMBO ATRAVESSA. `cached` marca o dicionário QUE ELE GUARDOU, e
        # esta função monta outro por cima — sem repassar, a rede existiria no
        # servidor e a tarja nunca apareceria na tela: número velho servido
        # CALADO, que é o pior dos três estados possíveis. Quem transforma isto
        # no cabeçalho `X-Leitura-Velha` é o `JSONResponse` da casa.
        **_carimbo(bruto),
    }


def _carimbo(bruto: dict) -> dict:
    """As três chaves que o `cached` põe quando serve a última leitura boa.

    Só saem quando há o que dizer: um `leitura_velha: False` fixo no payload
    faria o `JSONResponse` avaliar falso e não carimbar, o que funciona — mas
    põe no corpo um campo que mente sobre existir uma medição de idade.
    """
    if not bruto.get("leitura_velha"):
        return {}
    return {"leitura_velha": True,
            "leitura_idade_seg": bruto.get("leitura_idade_seg"),
            "leitura_em": bruto.get("leitura_em")}
