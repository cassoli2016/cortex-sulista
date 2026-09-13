# -*- coding: utf-8 -*-
"""Estoque — saldo, kardex, transferência, ajuste e bloqueio (tela `wmsest`;
a armazenagem da doca é chamada pela `wmsrec`).

TRÊS NÚMEROS, NÃO UM
====================
- FÍSICO: a soma do kardex naquele endereço, produto e lote (`wms_saldo`).
- RESERVADO: o que tarefa de separação PENDENTE já prometeu a um pedido.
- DISPONÍVEL: físico − reservado. É o único que uma movimentação nova pode
  tirar — senão o separador chega no endereço e a mercadoria prometida saiu
  por outra porta.

A trava por produto (`comum.TRAVA`) é pega ANTES de ler o disponível, e é a
mesma que o trigger do kardex usa. Sem ela, duas pessoas leriam o mesmo
disponível ao mesmo tempo e as duas passariam.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from . import comum
from .comum import (ROTULO_TIPO, TIPOS_GUARDA, auditar, ler, limpar_todas,
                    transacao, travar_produtos)
from ..validacao import DadoInvalido, data_br, quantidade_br, texto

SALDO_SQL = """
SELECT s.produto_id, s.endereco_id, s.lote, s.validade, s.qtd,
       s.primeira_entrada, s.ultimo_movimento,
       round(extract(epoch FROM now() - s.primeira_entrada)::numeric / 3600, 1) AS idade_h,
       e.codigo AS endereco, e.tipo AS endereco_tipo, e.bloqueado, e.motivo_bloqueio,
       p.codigo AS produto, p.descricao, p.unidade, p.depositante_cnpj,
       d.razao_social AS depositante, d.nome_fantasia,
       coalesce(r.reservado, 0) AS reservado,
       s.qtd - coalesce(r.reservado, 0) AS disponivel,
       (s.validade - current_date) AS dias_validade
  FROM wms_saldo s
  JOIN wms_endereco e ON e.id = s.endereco_id
  JOIN wms_produto p ON p.id = s.produto_id
  JOIN wms_depositante d ON d.cnpj = p.depositante_cnpj
  LEFT JOIN (SELECT produto_id, endereco_id, lote, sum(qtd) AS reservado
               FROM wms_tarefa WHERE status = 'pendente'
              GROUP BY produto_id, endereco_id, lote) r
         ON r.produto_id = s.produto_id AND r.endereco_id = s.endereco_id AND r.lote = s.lote
 WHERE e.armazem_id = %(a)s
   AND (%(dep)s::text IS NULL OR p.depositante_cnpj = %(dep)s)
   AND (%(tipo)s::text IS NULL OR e.tipo = %(tipo)s)
   AND (%(end)s::int IS NULL OR e.id = %(end)s)
   AND (%(prod)s::int IS NULL OR p.id = %(prod)s)
   AND (%(busca)s::text IS NULL OR p.codigo ILIKE %(busca)s OR p.descricao ILIKE %(busca)s
        OR e.codigo ILIKE %(busca)s OR s.lote ILIKE %(busca)s)
 ORDER BY e.codigo, p.codigo, s.lote
"""


def fmt(q) -> str:
    """Quantidade para frase de recusa: 12, 12,5 — sem zeros à direita."""
    d = Decimal(q).normalize()
    s = f"{d:f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def saldo(armazem_id: int, *, depositante: str | None = None, tipo: str | None = None,
          endereco_id: int | None = None, produto_id: int | None = None,
          busca: str | None = None, limite: int = 800,
          esquema: str | None = None) -> dict:
    dep = comum.cnpj(depositante) if depositante else None
    linhas = ler(SALDO_SQL, {"a": armazem_id, "dep": dep, "tipo": tipo or None,
                             "end": endereco_id, "prod": produto_id,
                             "busca": comum.curinga(busca)}, esquema)
    dias = [x["dias_validade"] for x in linhas if x["dias_validade"] is not None]
    resumo = {
        "posicoes": len(linhas),
        "produtos": len({x["produto_id"] for x in linhas}),
        "enderecos": len({x["endereco_id"] for x in linhas}),
        "vencidos": sum(1 for d in dias if d < 0),
        "vencendo_30d": sum(1 for d in dias if 0 <= d <= 30),
        "em_bloqueado": sum(1 for x in linhas if x["bloqueado"]),
        "reservadas": sum(1 for x in linhas if x["reservado"]),
    }
    lim = max(1, min(int(limite), 5000))
    return {"saldo": limpar_todas(linhas[:lim]), "total": len(linhas),
            "mostrando": min(len(linhas), lim), "resumo": resumo}


# ─────────────────────────────────────────────────────────── primitivas
def endereco(cur, endereco_id: int) -> dict:
    cur.execute("SELECT * FROM wms_endereco WHERE id = %s", (endereco_id,))
    e = cur.fetchone()
    if not e:
        raise DadoInvalido("Endereço não encontrado.")
    return e


def endereco_por_codigo(cur, armazem_id: int, codigo: str) -> dict:
    c = "".join(str(codigo or "").upper().split())
    cur.execute("SELECT * FROM wms_endereco WHERE armazem_id = %s AND codigo = %s",
                (armazem_id, c))
    e = cur.fetchone()
    if not e:
        raise DadoInvalido(f"O endereço {c or '(vazio)'} não existe neste armazém.")
    return e


def saldo_em(cur, produto_id: int, endereco_id: int, lote: str):
    """(físico, reservado, validade) de uma posição — lido DENTRO da trava."""
    cur.execute("""SELECT coalesce(sum(qtd), 0) AS qtd, max(validade) AS validade
                     FROM wms_movimento
                    WHERE produto_id = %s AND endereco_id = %s AND lote = %s""",
                (produto_id, endereco_id, lote))
    r = cur.fetchone()
    cur.execute("""SELECT coalesce(sum(qtd), 0) AS r FROM wms_tarefa
                    WHERE status = 'pendente' AND produto_id = %s
                      AND endereco_id = %s AND lote = %s""",
                (produto_id, endereco_id, lote))
    return Decimal(r["qtd"]), Decimal(cur.fetchone()["r"]), r["validade"]


def mov(cur, *, tipo: str, produto_id: int, endereco_id: int, lote: str, validade,
        qtd, doc_tipo: str, doc_id: int | None = None, usuario: str = "",
        grupo=None, motivo: str = "") -> None:
    cur.execute(
        """INSERT INTO wms_movimento(tipo, produto_id, endereco_id, lote, validade, qtd,
                                     doc_tipo, doc_id, usuario, grupo, motivo)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (tipo, produto_id, endereco_id, lote, validade, qtd, doc_tipo, doc_id,
         usuario or "", grupo, motivo[:200]))


# Para onde cada operação pode levar. A doca só recebe pelo recebimento, e a
# expedição só pela separação: mercadoria "movida" para a doca à mão viraria
# um recebimento sem nota.
DESTINOS = {
    "movimentacao": TIPOS_GUARDA + ("avaria",),
    "armazenagem": TIPOS_GUARDA + ("avaria",),
    "separacao": ("expedicao",),
}
ROTULO_DOC = {"movimentacao": "movimentação interna", "armazenagem": "armazenagem",
              "separacao": "separação"}


def transferir_cur(cur, *, origem: dict, destino: dict, produto_id: int, lote: str,
                   qtd: Decimal, usuario: str, doc_tipo: str, doc_id: int | None = None,
                   motivo: str = "", consome_reserva: bool = False,
                   estorno: bool = False) -> dict:
    """As duas pernas de uma transferência, dentro da transação de quem chama.

    `consome_reserva`: a separação tira o que a PRÓPRIA tarefa reservou, então
    não desconta a reserva. `estorno`: a devolução de um pedido cancelado volta
    da expedição para a origem, contra a regra de destino da separação.
    """
    if qtd is None or qtd <= 0:
        raise DadoInvalido("Informe uma quantidade maior que zero.")
    if origem["id"] == destino["id"]:
        raise DadoInvalido("Origem e destino são o mesmo endereço.")
    if origem["armazem_id"] != destino["armazem_id"]:
        raise DadoInvalido("Origem e destino estão em armazéns diferentes — entre armazéns "
                           "é expedição num e recebimento no outro.")
    if not estorno:
        permitidos = DESTINOS.get(doc_tipo)
        if permitidos and destino["tipo"] not in permitidos:
            raise DadoInvalido(
                f"O endereço {destino['codigo']} é {ROTULO_TIPO[destino['tipo']].lower()} "
                f"e não recebe {ROTULO_DOC.get(doc_tipo, doc_tipo)}.")
        if doc_tipo == "movimentacao" and origem["tipo"] == "expedicao":
            raise DadoInvalido("Mercadoria na expedição já pertence a um pedido — cancele o "
                               "pedido para devolvê-la ao estoque.")
    travar_produtos(cur, [produto_id])
    fisico, reservado, validade = saldo_em(cur, produto_id, origem["id"], lote)
    livre = fisico if consome_reserva else fisico - reservado
    if qtd > livre:
        sufixo = f" (lote {lote})" if lote else ""
        if not consome_reserva and reservado > 0 and qtd <= fisico:
            raise DadoInvalido(
                f"No endereço {origem['codigo']} há {fmt(fisico)}{sufixo}, mas {fmt(reservado)} "
                f"estão reservados para separação — disponível {fmt(max(livre, 0))}.")
        raise DadoInvalido(f"No endereço {origem['codigo']} há {fmt(fisico)} deste "
                           f"produto{sufixo} — não dá para tirar {fmt(qtd)}.")
    g = uuid.uuid4()
    for end, q in ((origem, -qtd), (destino, qtd)):
        mov(cur, tipo="transferencia", produto_id=produto_id, endereco_id=end["id"],
            lote=lote, validade=validade, qtd=q, doc_tipo=doc_tipo, doc_id=doc_id,
            usuario=usuario, grupo=g, motivo=motivo)
    return {"grupo": str(g), "origem": origem["codigo"], "destino": destino["codigo"],
            "qtd": float(qtd)}


# ─────────────────────────────────────────────────────────── operações
def transferir(dados: dict, usuario: str, esquema: str | None = None) -> dict:
    """Movimentação interna — ou ARMAZENAGEM, quando a origem é uma doca.

    O destino vem pelo id (seletor) ou pelo CÓDIGO digitado — que é como se
    trabalha no chão do armazém, lendo a etiqueta da posição."""
    origem_id = comum.inteiro_id(dados.get("origem_id"), "o endereço de origem")
    produto_id = comum.inteiro_id(dados.get("produto_id"), "o produto")
    lote = comum.lote(dados.get("lote"))
    qtd = quantidade_br(dados.get("qtd"), "a quantidade")
    motivo = texto(dados.get("motivo"), "o motivo", maximo=200)
    with transacao(esquema) as conn, conn.cursor() as cur:
        o = endereco(cur, origem_id)
        if dados.get("destino_id"):
            d = endereco(cur, comum.inteiro_id(dados["destino_id"], "o destino"))
        else:
            d = endereco_por_codigo(cur, o["armazem_id"], dados.get("destino_codigo"))
        doc = "armazenagem" if o["tipo"] == "doca" else "movimentacao"
        r = transferir_cur(cur, origem=o, destino=d, produto_id=produto_id, lote=lote,
                           qtd=qtd, usuario=usuario, doc_tipo=doc, motivo=motivo)
        auditar(cur, usuario, f"wms_{doc}", f"{o['codigo']}>{d['codigo']}",
                f"produto {produto_id} lote {lote or '-'} qtd {fmt(qtd)}")
    return {**r, "operacao": doc}


def ajustar(dados: dict, usuario: str, esquema: str | None = None) -> dict:
    """Ajuste com motivo OBRIGATÓRIO. É a correção fora do inventário (avaria
    descoberta, sinistro, erro de conferência já expedido) — e por ser a porta
    mais fácil de fazer o saldo mentir, é a que mais precisa dizer por quê."""
    endereco_id = comum.inteiro_id(dados.get("endereco_id"), "o endereço")
    produto_id = comum.inteiro_id(dados.get("produto_id"), "o produto")
    lote = comum.lote(dados.get("lote"))
    delta = quantidade_br(dados.get("qtd"), "a quantidade do ajuste")
    if delta is None or delta == 0:
        raise DadoInvalido("Informe o ajuste: positivo para acrescentar, negativo para retirar.")
    motivo = texto(dados.get("motivo"), "o motivo do ajuste", maximo=200, obrigatorio=True)
    if len(motivo) < 5:
        raise DadoInvalido("Diga o motivo do ajuste — é ele que explica o saldo depois.")
    validade = data_br(dados.get("validade"), "a validade")
    with transacao(esquema) as conn, conn.cursor() as cur:
        e = endereco(cur, endereco_id)
        cur.execute("SELECT * FROM wms_produto WHERE id = %s", (produto_id,))
        p = cur.fetchone()
        if not p:
            raise DadoInvalido("Produto não encontrado.")
        travar_produtos(cur, [produto_id])
        fisico, reservado, val_atual = saldo_em(cur, produto_id, endereco_id, lote)
        if delta < 0 and fisico + delta < reservado:
            raise DadoInvalido(f"Há {fmt(reservado)} reservados para separação neste endereço — "
                               f"o ajuste deixaria {fmt(fisico + delta)}.")
        if delta > 0:
            if p["controla_lote"] and not lote:
                raise DadoInvalido(f"O produto {p['codigo']} controla lote — informe o lote.")
            validade = validade or val_atual
            if p["controla_validade"] and not validade:
                raise DadoInvalido(f"O produto {p['codigo']} controla validade — informe a validade.")
        else:
            validade = val_atual
        mov(cur, tipo="ajuste", produto_id=produto_id, endereco_id=endereco_id, lote=lote,
            validade=validade, qtd=delta, doc_tipo="ajuste", usuario=usuario, motivo=motivo)
        auditar(cur, usuario, "wms_ajuste", e["codigo"],
                f"produto {p['codigo']} lote {lote or '-'} {fmt(delta)}: {motivo}")
    return {"ok": True, "endereco": e["codigo"], "qtd": float(delta)}


def bloquear(endereco_id: int, motivo, usuario: str, esquema: str | None = None) -> dict:
    motivo = texto(motivo, "o motivo do bloqueio", maximo=80, obrigatorio=True)
    with transacao(esquema) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM wms_endereco WHERE id = %s FOR UPDATE", (endereco_id,))
        e = cur.fetchone()
        if not e:
            raise DadoInvalido("Endereço não encontrado.")
        if e["bloqueado"]:
            raise DadoInvalido(f"O endereço {e['codigo']} já está bloqueado ({e['motivo_bloqueio']}).")
        cur.execute("SELECT count(*) AS n FROM wms_tarefa WHERE endereco_id = %s AND status = 'pendente'",
                    (endereco_id,))
        if cur.fetchone()["n"]:
            raise DadoInvalido(f"Há separação pendente no endereço {e['codigo']} — confirme ou "
                               "cancele o pedido antes de bloquear.")
        cur.execute("""UPDATE wms_endereco SET bloqueado = true, motivo_bloqueio = %s,
                              bloqueado_em = now(), bloqueado_por = %s WHERE id = %s""",
                    (motivo, usuario or "", endereco_id))
        auditar(cur, usuario, "wms_endereco_bloquear", e["codigo"], motivo)
    return {"ok": True}


def desbloquear(endereco_id: int, usuario: str, esquema: str | None = None) -> dict:
    with transacao(esquema) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM wms_endereco WHERE id = %s FOR UPDATE", (endereco_id,))
        e = cur.fetchone()
        if not e:
            raise DadoInvalido("Endereço não encontrado.")
        if not e["bloqueado"]:
            raise DadoInvalido(f"O endereço {e['codigo']} não está bloqueado.")
        cur.execute("""SELECT iv.id FROM wms_inventario_endereco ie
                         JOIN wms_inventario iv ON iv.id = ie.inventario_id
                        WHERE ie.endereco_id = %s AND iv.status = 'aberto' AND ie.bloqueou""",
                    (endereco_id,))
        inv = cur.fetchone()
        if inv:
            raise DadoInvalido(f"O endereço {e['codigo']} está no inventário #{inv['id']} — "
                               "ele é liberado quando o inventário fecha.")
        cur.execute("""UPDATE wms_endereco SET bloqueado = false, motivo_bloqueio = '',
                              bloqueado_em = NULL, bloqueado_por = '' WHERE id = %s""",
                    (endereco_id,))
        auditar(cur, usuario, "wms_endereco_desbloquear", e["codigo"], e["motivo_bloqueio"])
    return {"ok": True}


# ─────────────────────────────────────────────────────────── leitura
KARDEX_SQL = """
SELECT m.id, m.criado_em, m.usuario, m.tipo, m.doc_tipo, m.doc_id, m.qtd, m.lote,
       m.validade, m.motivo, m.grupo,
       e.codigo AS endereco, e.tipo AS endereco_tipo,
       p.codigo AS produto, p.descricao, p.unidade,
       d.razao_social AS depositante, d.nome_fantasia,
       count(*) OVER () AS total
  FROM wms_movimento m
  JOIN wms_endereco e ON e.id = m.endereco_id
  JOIN wms_produto p ON p.id = m.produto_id
  JOIN wms_depositante d ON d.cnpj = p.depositante_cnpj
 WHERE e.armazem_id = %(a)s
   AND m.criado_em >= now() - make_interval(days => %(dias)s)
   AND (%(prod)s::int IS NULL OR m.produto_id = %(prod)s)
   AND (%(end)s::int IS NULL OR m.endereco_id = %(end)s)
   AND (%(doc)s::text IS NULL OR m.doc_tipo = %(doc)s)
   AND (%(busca)s::text IS NULL OR p.codigo ILIKE %(busca)s OR p.descricao ILIKE %(busca)s
        OR e.codigo ILIKE %(busca)s OR m.lote ILIKE %(busca)s OR m.usuario ILIKE %(busca)s)
 ORDER BY m.id DESC
 LIMIT %(lim)s
"""

DOCS = ("recebimento", "armazenagem", "movimentacao", "separacao", "expedicao",
        "inventario", "ajuste")


def kardex(armazem_id: int, *, produto_id: int | None = None, endereco_id: int | None = None,
           doc_tipo: str | None = None, busca: str | None = None, dias: int = 30,
           limite: int = 400, esquema: str | None = None) -> dict:
    if doc_tipo and doc_tipo not in DOCS:
        raise DadoInvalido("Tipo de documento desconhecido.")
    dias = max(1, min(int(dias or 30), 730))
    lim = max(1, min(int(limite or 400), 2000))
    linhas = ler(KARDEX_SQL, {"a": armazem_id, "dias": dias, "prod": produto_id,
                              "end": endereco_id, "doc": doc_tipo or None,
                              "busca": comum.curinga(busca), "lim": lim}, esquema)
    total = int(linhas[0]["total"]) if linhas else 0
    for x in linhas:
        x.pop("total", None)
    return {"movimentos": limpar_todas(linhas), "total": total,
            "mostrando": len(linhas), "dias": dias}


def doca(armazem_id: int, esquema: str | None = None) -> dict:
    """O que está PARADO na doca, com o destino sugerido para cada posição.

    A sugestão junta primeiro com o mesmo produto e lote (consolidar libera
    posição), e só então abre um endereço vazio — porta-palete antes de
    blocado antes de picking, na ordem do código, que é a ordem da rua. Um
    endereço vazio não é sugerido a duas linhas: seria o mesmo lugar prometido
    duas vezes."""
    linhas = saldo(armazem_id, tipo="doca", limite=500, esquema=esquema)["saldo"]
    if not linhas:
        return {"doca": [], "total": 0, "idade_max_h": None}
    vazios = ler("""
        SELECT e.id, e.codigo, e.tipo FROM wms_endereco e
         WHERE e.armazem_id = %s AND e.ativo AND NOT e.bloqueado
           AND e.tipo IN ('porta_palete','blocado','picking')
           AND NOT EXISTS (SELECT 1 FROM wms_saldo s WHERE s.endereco_id = e.id)
           AND NOT EXISTS (SELECT 1 FROM wms_tarefa t WHERE t.endereco_id = e.id
                                                        AND t.status = 'pendente')
         ORDER BY CASE e.tipo WHEN 'porta_palete' THEN 0 WHEN 'blocado' THEN 1 ELSE 2 END,
                  e.codigo
         LIMIT 600""", (armazem_id,), esquema)
    produtos = sorted({x["produto_id"] for x in linhas})
    mesmos: dict[tuple, dict] = {}
    for m in ler("""
        SELECT s.produto_id, s.lote, e.id, e.codigo FROM wms_saldo s
          JOIN wms_endereco e ON e.id = s.endereco_id
         WHERE e.armazem_id = %s AND e.ativo AND NOT e.bloqueado
           AND e.tipo IN ('porta_palete','blocado','picking')
           AND s.produto_id = ANY(%s)
         ORDER BY e.codigo""", (armazem_id, produtos), esquema):
        mesmos.setdefault((m["produto_id"], m["lote"]), {"id": m["id"], "codigo": m["codigo"]})
    livres = iter(vazios)
    for x in linhas:
        junto = mesmos.get((x["produto_id"], x["lote"]))
        if junto:
            x["sugestao"] = {**junto, "motivo": "junta com o mesmo produto e lote"}
            continue
        v = next(livres, None)
        x["sugestao"] = ({"id": v["id"], "codigo": v["codigo"], "motivo": "endereço vazio"}
                         if v else None)
    idades = [x["idade_h"] for x in linhas if x["idade_h"] is not None]
    return {"doca": linhas, "total": len(linhas),
            "idade_max_h": max(idades) if idades else None}
