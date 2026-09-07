# -*- coding: utf-8 -*-
"""O mural: um comunicado do RH para todos os motoristas de uma vez.

═══════════════════════════════════════════════════════════════════════════
POR QUE ISTO NÃO ENTROU NO CANAL, E ENTROU AO LADO DELE
═══════════════════════════════════════════════════════════════════════════
`conversas.abrir_rh` recusa comunicado em massa por escrito, e a razão continua
valendo: 300 conversas abertas de uma vez entopem a fila que o canal existe
para manter atendível — a caixa ordena pelo mais parado e mede "paradas há 3+
dias", e trezentas linhas destroem os dois números no mesmo instante.

O mesmo comentário disse qual era a saída, e este módulo é ela: **um mural,
sem fila e sem resposta**. Um comunicado, N ciências, UM cartão na tela do RH
com uma fração — não trezentas linhas.

O que se cobra aqui não é atendimento, é CIÊNCIA. Quem quiser FALAR sobre o
comunicado abre um pedido normal, e aí sim entra na fila com dono. As duas
coisas convivem porque são perguntas diferentes: "todo mundo foi avisado?" e
"quem está cuidando do caso do Fulano?".

═══════════════════════════════════════════════════════════════════════════
O PÚBLICO É FOTOGRAFADO NA PUBLICAÇÃO
═══════════════════════════════════════════════════════════════════════════
Uma linha por destinatário, no ato. A alternativa — calcular "todos os ativos"
na leitura — parece mais simples e mente de duas formas:

1. o motorista contratado em novembro passaria a dever ciência de um comunicado
   de setembro, sobre uma convenção que não o alcança;
2. "45 de 80 confirmaram" mudaria de DENOMINADOR sozinho a cada admissão e a
   cada desligamento — a fração andaria para trás sem ninguém ter feito nada,
   que é o jeito mais rápido de um número perder a confiança de quem o lê.

É a mesma regra do "denominador só contém quem pode cumprir a regra" que tirou
terceiros e carretas da cobertura de rastreador. Custa ~300 linhas por
comunicado, e elas são uma LISTA DE PRESENÇA, não uma fila.

═══════════════════════════════════════════════════════════════════════════
O QUE NÃO SAI DAQUI
═══════════════════════════════════════════════════════════════════════════
**Aviso em massa por WhatsApp.** Decidido por quem opera em 07/09/2026 com o
número na mesa: o teto da casa é 60 destinatários DISTINTOS por dia, e ele
protege o número que fala com clientes. Trezentos motoristas seriam cinco dias
de ondas — e no quinto dia o comunicado já não é notícia. Quem avisa é a marca
no app.

**Anexo.** Mesma razão de `conversas.py`: upload é módulo, não campo. Um
comunicado que precise de PDF vira, por enquanto, um texto com o que fazer.
"""
from __future__ import annotations

import logging

from .. import pglocal

log = logging.getLogger("cortex.motorista.mural")

#: Teto do título e do texto. O título entra numa lista de celular; o texto é
#: lido numa tela de 390 px. Recusa LEGÍVEL, nunca truncamento — cortar o que
#: alguém escreveu sem avisar é perder a metade que importava.
MAX_TITULO = 120
MAX_TEXTO = 4000

#: Quantos comunicados a tela do RH lista. Com contador ao lado.
LIMITE = 50


class Recusa(Exception):
    """Recusa legível, para virar 4xx na rota."""


def _esq(esquema: str | None = None) -> str | None:
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


def _texto(bruto: str, teto: int, campo: str) -> str:
    t = " ".join(str(bruto or "").split()) if teto == MAX_TITULO \
        else str(bruto or "").strip()
    if not t:
        raise Recusa("Escreva %s." % campo)
    if len(t) > teto:
        raise Recusa("%s passou de %d caracteres." % (campo.capitalize(), teto))
    return t


# ═══════════════════════════════════════════════════════ publicar (o RH) ═══

def publicar(titulo: str, texto: str, *, autor_id=None, autor_nome: str = "",
             esquema: str | None = None) -> dict:
    """Publica para TODOS os motoristas ativos, num só ato.

    A LISTA DE DESTINATÁRIOS E O COMUNICADO NASCEM NA MESMA TRANSAÇÃO. Se
    fossem duas, uma falha no meio deixaria um comunicado publicado para
    ninguém — visível na tela do RH com "0 de 0", e invisível no app de todo
    mundo. Publicar é atômico ou não aconteceu.
    """
    esq = _esq(esquema)
    tit = _texto(titulo, MAX_TITULO, "um título")
    txt = _texto(texto, MAX_TEXTO, "o comunicado")

    with pglocal.get_conn(esq) as cx:
        with cx.cursor() as cur:
            cur.execute(
                """INSERT INTO mot_comunicados(titulo, texto, autor_id, autor_nome)
                   VALUES (%s,%s,%s,%s) RETURNING id""",
                (tit, txt, autor_id, autor_nome or ""))
            cid = int(cur.fetchone()["id"])
            # A FOTOGRAFIA DO PÚBLICO, aqui e agora — ver o docstring.
            cur.execute(
                """INSERT INTO mot_comunicado_ciencia(comunicado_id, motorista_codigo)
                   SELECT %s, motorista_codigo FROM mot_vinculos WHERE ativo""",
                (cid,))
            destinatarios = cur.rowcount
        cx.commit()

    if not destinatarios:
        # NÃO É ERRO, É INSTALAÇÃO INCOMPLETA — e tem de ser DITO, senão o RH
        # escreve um comunicado, vê "publicado" e acha que 300 pessoas leram.
        log.warning("comunicado %d publicado sem nenhum destinatário", cid)
    return {"id": cid, "destinatarios": destinatarios}


def encerrar(comunicado_id, *, autor_nome: str = "",
             esquema: str | None = None) -> dict:
    """Para de cobrar ciência, sem apagar.

    Um comunicado de março que segue pedindo "li e entendi" para sempre ensina
    a pessoa a ignorar o pedido — inclusive no de hoje. Encerrar tira do app e
    congela a fração no histórico.
    """
    esq = _esq(esquema)
    n = pglocal.executar(
        """UPDATE mot_comunicados SET encerrado_em = now(), encerrado_por = %(q)s
            WHERE id = %(id)s AND encerrado_em IS NULL""",
        {"id": _id(comunicado_id), "q": autor_nome or ""}, esq)
    return {"ok": True, "encerrado": bool(n)}


def _id(bruto) -> int:
    try:
        return int(bruto)
    except (TypeError, ValueError):
        raise Recusa("Comunicado não encontrado.") from None


_LISTA_SQL = """
SELECT c.id, c.titulo, c.texto, c.autor_nome, c.criado_em,
       c.encerrado_em, c.encerrado_por,
       count(k.*)::int                                            AS destinatarios,
       sum(CASE WHEN k.ciencia_em IS NOT NULL THEN 1 ELSE 0 END)::int AS confirmaram,
       -- ABRIU E NÃO CONFIRMOU é a conversa mais útil das três: essa pessoa
       -- viu o comunicado e escolheu não confirmar, ou não achou o botão.
       sum(CASE WHEN k.ciencia_em IS NULL AND k.visto_em IS NOT NULL
                THEN 1 ELSE 0 END)::int                            AS viram_sem_confirmar
  FROM mot_comunicados c
  LEFT JOIN mot_comunicado_ciencia k ON k.comunicado_id = c.id
 GROUP BY c.id
 ORDER BY (c.encerrado_em IS NOT NULL), c.criado_em DESC
 LIMIT %(lim)s
"""


def listar(esquema: str | None = None) -> dict:
    """Os comunicados, para a tela do RH. UM cartão por comunicado."""
    esq = _esq(esquema)
    linhas = pglocal.query(_LISTA_SQL, {"lim": LIMITE}, esq)
    total = pglocal.um("SELECT count(*)::int AS n FROM mot_comunicados",
                       esquema=esq) or {}
    itens = []
    for l in linhas:
        dest = int(l["destinatarios"] or 0)
        ok = int(l["confirmaram"] or 0)
        itens.append({
            "id": int(l["id"]),
            "titulo": l["titulo"],
            "texto": l["texto"],
            "autor": l["autor_nome"] or "",
            "criado_em": l["criado_em"].isoformat() if l["criado_em"] else None,
            "encerrado": bool(l["encerrado_em"]),
            "encerrado_em": (l["encerrado_em"].isoformat()
                             if l["encerrado_em"] else None),
            "destinatarios": dest,
            "confirmaram": ok,
            "viram_sem_confirmar": int(l["viram_sem_confirmar"] or 0),
            "faltam": dest - ok,
            # PERCENTUAL SÓ COM DENOMINADOR. Sem destinatário, "0%" seria uma
            # medida sobre nada — e zero que é ausência não é desempenho.
            "pct": (round(100.0 * ok / dest, 1) if dest else None),
        })
    return {"comunicados": itens, "mostrados": len(itens),
            "total": int(total.get("n") or 0), "limite": LIMITE,
            "fonte": "CÓRTEX · mural do RH (mot_comunicados)"}


_FALTAM_SQL = """
SELECT v.id AS motorista_id, v.nome, k.visto_em
  FROM mot_comunicado_ciencia k
  JOIN mot_vinculos v ON v.motorista_codigo = k.motorista_codigo
 WHERE k.comunicado_id = %(id)s AND k.ciencia_em IS NULL
 ORDER BY (k.visto_em IS NULL), v.nome
"""


def faltam(comunicado_id, esquema: str | None = None) -> dict:
    """Quem ainda não confirmou — com quem JÁ ABRIU primeiro na lista.

    É a única lista de pessoas deste módulo, e ela existe porque "45 de 80" sem
    os nomes não vira ação nenhuma. Só id opaco e nome: o `motorista_codigo` é
    o CPF para pessoa física e não sai daqui, como em todo o resto do módulo.
    """
    esq = _esq(esquema)
    linhas = pglocal.query(_FALTAM_SQL, {"id": _id(comunicado_id)}, esq)
    return {"faltam": [{"motorista_id": int(l["motorista_id"]),
                        "nome": l["nome"] or "",
                        # "abriu e não confirmou" × "nunca abriu": duas
                        # conversas diferentes com a pessoa.
                        "abriu": bool(l["visto_em"])} for l in linhas],
            "n": len(linhas)}


# ═══════════════════════════════════════════════ o lado do motorista ═══════

_MEUS_SQL = """
SELECT c.id, c.titulo, c.texto, c.autor_nome, c.criado_em,
       k.visto_em, k.ciencia_em
  FROM mot_comunicado_ciencia k
  JOIN mot_comunicados c ON c.id = k.comunicado_id
 WHERE k.motorista_codigo = %(mot)s AND c.encerrado_em IS NULL
 ORDER BY c.criado_em DESC
"""


def meus(sessao: dict, esquema: str | None = None) -> dict:
    """Os comunicados DELE. O código sai da sessão, nunca do pedido.

    Encerrado não aparece: o mural mostra o que ainda vale. O histórico é do
    RH, que é quem precisa provar depois que comunicou.
    """
    linhas = pglocal.query(_MEUS_SQL,
                           {"mot": str(sessao["motorista_codigo"])},
                           _esq(esquema))
    itens = [{"id": int(l["id"]), "titulo": l["titulo"], "texto": l["texto"],
              "autor": l["autor_nome"] or "",
              "quando": l["criado_em"].isoformat() if l["criado_em"] else None,
              "confirmado": bool(l["ciencia_em"]),
              "confirmado_em": (l["ciencia_em"].isoformat()
                                if l["ciencia_em"] else None)}
             for l in linhas]
    return {"comunicados": itens,
            "pendentes": sum(1 for i in itens if not i["confirmado"])}


def _meu(motorista_codigo: str, comunicado_id, esquema) -> dict:
    """A linha de ciência DELE. O dono entra no WHERE, junto do id.

    Mesma regra de `conversas._minha`: nunca uma busca por id seguida de um
    `if` conferindo o dono — o `if` é a linha que alguém apaga, e o sintoma é
    dar ciência no comunicado de outra pessoa.
    """
    linha = pglocal.um(
        """SELECT k.comunicado_id, k.ciencia_em
             FROM mot_comunicado_ciencia k
             JOIN mot_comunicados c ON c.id = k.comunicado_id
            WHERE k.comunicado_id = %(id)s AND k.motorista_codigo = %(mot)s
              AND c.encerrado_em IS NULL""",
        {"id": _id(comunicado_id), "mot": str(motorista_codigo)}, esquema)
    if not linha:
        raise Recusa("Comunicado não encontrado.")
    return dict(linha)


def marcar_visto(sessao: dict, comunicado_id, esquema: str | None = None) -> dict:
    """Ele ABRIU. Não é ciência — e é por isso que são dois campos."""
    esq = _esq(esquema)
    _meu(sessao["motorista_codigo"], comunicado_id, esq)
    pglocal.executar(
        """UPDATE mot_comunicado_ciencia SET visto_em = coalesce(visto_em, now())
            WHERE comunicado_id = %(id)s AND motorista_codigo = %(mot)s""",
        {"id": _id(comunicado_id), "mot": str(sessao["motorista_codigo"])}, esq)
    return {"ok": True}


def dar_ciencia(sessao: dict, comunicado_id, esquema: str | None = None) -> dict:
    """"Li e entendi". IDEMPOTENTE: dois toques não viram duas ciências, e o
    carimbo que vale é o do PRIMEIRO — é ele que responde "quando ele leu?"."""
    esq = _esq(esquema)
    linha = _meu(sessao["motorista_codigo"], comunicado_id, esq)
    if linha["ciencia_em"]:
        return {"ok": True, "ja_tinha": True}
    pglocal.executar(
        """UPDATE mot_comunicado_ciencia
              SET ciencia_em = now(), visto_em = coalesce(visto_em, now())
            WHERE comunicado_id = %(id)s AND motorista_codigo = %(mot)s
              AND ciencia_em IS NULL""",
        {"id": _id(comunicado_id), "mot": str(sessao["motorista_codigo"])}, esq)
    return {"ok": True, "ja_tinha": False}


def contagem(esquema: str | None = None) -> dict:
    """Para a Saúde do Servidor e o Copiloto. SÓ CONTAGENS."""
    r = pglocal.um(
        """SELECT (SELECT count(*) FROM mot_comunicados)::int AS total,
                  (SELECT count(*) FROM mot_comunicados
                    WHERE encerrado_em IS NULL)::int AS vivos,
                  (SELECT count(*) FROM mot_comunicado_ciencia k
                     JOIN mot_comunicados c ON c.id = k.comunicado_id
                    WHERE c.encerrado_em IS NULL
                      AND k.ciencia_em IS NULL)::int AS ciencias_pendentes""",
        esquema=_esq(esquema)) or {}
    return {"total": r.get("total") or 0, "vivos": r.get("vivos") or 0,
            "ciencias_pendentes": r.get("ciencias_pendentes") or 0}
