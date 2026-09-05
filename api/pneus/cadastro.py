# -*- coding: utf-8 -*-
"""As tabelas de DOMÍNIO da Prolog — o que a casa precisa antes de desligá-la.

POR QUE ISTO EXISTE, e é a diferença entre replicar e depender. O instantâneo
diz o estado dos pneus HOJE; estas tabelas dizem o que as coisas SIGNIFICAM: os
diagramas de eixo (quais posições um veículo tem), os motivos de descarte e os
motivos de movimentação. Sem elas o nosso banco guarda códigos que só a Prolog
sabe ler — e no dia em que ela sair, `pne_evento.motivo` vira texto órfão e
`posicao` vira um código que ninguém valida.

SÃO BARATAS E QUASE NÃO MUDAM. Os 44 diagramas cabem numa requisição; os
motivos, em duas. Por isso elas entram por completo a cada passada, em vez de
paginar — e por isso podem rodar longe da cota que a coleta do histórico
precisa.

O QUE ELAS RESOLVEM, concretamente:

- `pne_diagrama` estava VAZIA. Sem ela não há como dizer que a posição `3DE`
  existe naquele veículo — e sem isso o módulo próprio não pode registrar
  montagem nenhuma, porque aceitaria qualquer coisa digitada.
- `pne_evento.motivo` está 100% nulo. A regra da casa é que código sem tabela
  de domínio não vira rótulo inventado: agora a tabela existe, e o rótulo passa
  a ter de onde vir.

A GRAMÁTICA DOS EIXOS vem DELES, não de palpite nosso: `axleType` D é eixo
direcional (2 pneus) e T é rodagem dupla (4); `axleKind` diz se ele é
DIRECTIONAL, MOTORIZED ou AUXILIARY. TOCO = D1(2) + T2(4) = 6 pneus; CARRETA
3 EIXOS = T1+T2+T3 = 12. Isso bate exatamente com as posições observadas no
parque, o que é a conferência de que a leitura está certa.
"""
from __future__ import annotations

import json
import logging

from .. import pglocal
from . import cliente

log = logging.getLogger("cortex.pneus.cadastro")

ROTA = "cadastro"


def _gravar_estado(registros: int, erro: str | None) -> None:
    try:
        pglocal.executar("""
            INSERT INTO pne_sync (rota, ultima_em, ultimo_ok_em, registros,
                                  ultimo_erro, atualizado_em)
            VALUES (%s, now(), CASE WHEN %s IS NULL THEN now() END, %s, %s, now())
            ON CONFLICT (rota) DO UPDATE SET
                ultima_em    = now(),
                ultimo_ok_em = CASE WHEN %s IS NULL THEN now()
                               ELSE pne_sync.ultimo_ok_em END,
                registros    = EXCLUDED.registros,
                ultimo_erro  = EXCLUDED.ultimo_erro,
                atualizado_em = now()""",
            (ROTA, erro, registros, erro, erro))
    except Exception:  # noqa: BLE001
        pass


def _diagramas(cli) -> int:
    """Os 44 diagramas de eixo. Uma requisição, sem paginação."""
    d = cli.get("/api/v3/vehicles/diagrams")
    itens = d if isinstance(d, list) else (d.get("content") or [])
    n = 0
    with pglocal.get_conn() as conn, conn.cursor() as cur:
        for x in itens:
            eixos = x.get("axles") or []
            # AS POSIÇÕES SAEM DA ESTRUTURA, não de uma lista à parte: cada
            # eixo diz o tipo, a ordem e quantos pneus tem, e é isso que
            # define quantas posições existem. Guardamos o eixo inteiro para
            # que uma regra futura (rodízio, eixo suspenso) tenha o que ler.
            posicoes = [{"eixo": a.get("axlePosition"),
                         "tipo": a.get("axleType"),
                         "funcao": a.get("axleKind"),
                         "pneus": a.get("tireQuantity"),
                         "suspensivel": bool(a.get("canBeSuspended"))}
                        for a in eixos]
            cur.execute("""
                INSERT INTO pne_diagrama (nome, tem_motor, eixos, posicoes,
                                          prolog_id)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (nome) DO UPDATE SET
                    tem_motor = EXCLUDED.tem_motor,
                    eixos     = EXCLUDED.eixos,
                    posicoes  = EXCLUDED.posicoes,
                    prolog_id = EXCLUDED.prolog_id""",
                ((x.get("name") or "").strip() or "sem nome",
                 bool(x.get("hasEngine")), len(eixos),
                 json.dumps(posicoes, ensure_ascii=False),
                 str(x.get("id") or "")))
            n += 1
    return n


def _motivos(cli) -> int:
    """Os motivos de descarte.

    UMA TRANSAÇÃO POR ENDPOINT, e isto veio de um erro meu na primeira versão:
    os dois endpoints dividiam a mesma conexão, o segundo respondeu HTTP 400 e
    o `rollback` levou junto os 18 motivos que o primeiro já tinha gravado.
    Falha de um fornecedor não pode desfazer o que o outro caminho conseguiu.

    O CAMPO CHAMA `reasonName`, e não `description` nem `name` — a primeira
    versão lia três nomes plausíveis e nenhum deles era o certo, então a tabela
    entrava vazia sem erro nenhum. É a lição de ler a resposta INTEIRA do
    fornecedor uma vez, de novo.

    `reasons/transactions` FICA DE FORA por enquanto: o spec diz que os
    parâmetros são opcionais e o servidor responde 400 sem eles — ele quer a
    filial e o par origem/destino, o que viraria uma varredura de dezenas de
    requisições contra uma cota de dez. Os motivos de DESCARTE, que são os que
    `pne_evento.motivo` precisa para a sucata, vêm inteiros numa só.
    """
    d = cli.get("/api/v3/tire-relocations/disposal-reasons")
    itens = d if isinstance(d, list) else (d.get("content") or [])
    n = 0
    with pglocal.get_conn() as conn, conn.cursor() as cur:
        for x in itens:
            if not isinstance(x, dict):
                continue
            ident = x.get("id") or x.get("reasonId") or x.get("code")
            rot = (x.get("reasonName") or x.get("description")
                   or x.get("name") or x.get("reason") or "")
            if ident is None or not str(rot).strip():
                continue
            cur.execute("""
                INSERT INTO pne_motivo (especie, prolog_id, rotulo, ativo)
                VALUES ('descarte',%s,%s,%s)
                ON CONFLICT (especie, prolog_id) DO UPDATE SET
                    rotulo = EXCLUDED.rotulo, ativo = EXCLUDED.ativo""",
                (str(ident), str(rot).strip(),
                 bool(x.get("isActive", x.get("active", True)))))
            n += 1
    return n


def sincronizar() -> dict:
    """Traz as tabelas de domínio. NUNCA levanta.

    Três requisições no total. Elas quase não mudam, então cabe rodar isto uma
    vez por dia — e não junto com a coleta do histórico, que precisa da cota.
    """
    if not cliente.pronto():
        return {"ok": False, "erro": "integração da Prolog não configurada"}
    cli = cliente.Cliente()
    diag = mot = 0
    erros = []
    # CADA PASSO FALHA POR CONTA PROPRIA. Na primeira versao os dois estavam no
    # mesmo `try` e o 400 do segundo apagou o resultado do primeiro — o
    # fornecedor tem endpoints com maturidades diferentes, e um deles fora do ar
    # nao pode zerar a coleta inteira.
    for nome, passo in (("diagramas", _diagramas), ("motivos", _motivos)):
        try:
            n = passo(cli)
            if nome == "diagramas":
                diag = n
            else:
                mot = n
        except Exception as exc:  # noqa: BLE001
            erros.append("%s: %s" % (nome, type(exc).__name__))
            log.warning("cadastro de pneus, %s: %s", nome, str(exc)[:160])
    erro = " · ".join(erros) or None
    _gravar_estado(diag + mot, erro)
    return {"ok": erro is None, "erro": erro,
            "diagramas": diag, "motivos": mot}


def estado() -> dict:
    """O que já está no banco da casa — para a Saúde poder DIZER."""
    try:
        d = pglocal.query("SELECT count(*) AS n FROM pne_diagrama")[0]["n"]
        m = pglocal.query("SELECT especie, count(*) AS n FROM pne_motivo "
                          "GROUP BY 1")
        return {"diagramas": d,
                "motivos": {r["especie"]: r["n"] for r in m}}
    except Exception as exc:  # noqa: BLE001
        return {"erro": type(exc).__name__}
