# -*- coding: utf-8 -*-
"""Inventário — contagem CEGA por endereço, e o ajuste que ela gera
(aba Inventário da tela `wmsest`).

Abrir BLOQUEIA os endereços do escopo: contar um endereço enquanto alguém
tira mercadoria dele mede um número que já não existe quando a contagem
termina. O bloqueio é marcado como DESTE inventário (`bloqueou`), e fechar só
desbloqueia o que ele bloqueou — o endereço que já estava interditado por
avaria continua interditado.

A CONTAGEM É CEGA pela mesma razão do recebimento: quem conta não vê o saldo.
E fechar exige TODOS os endereços contados — "não contei" e "contei zero" são
afirmações diferentes, e só a segunda autoriza zerar um saldo. Endereço vazio
se registra como vazio.

Fechar gera os ajustes (`doc_tipo = 'inventario'`) na diferença entre o
contado e o saldo do sistema NA HORA DO FECHAMENTO; a acurácia sai deles.
"""
from __future__ import annotations

import re
from decimal import Decimal

from . import comum, estoque
from .comum import TIPOS_GUARDA, auditar, ler, limpar, limpar_todas, transacao, travar_produtos
from ..validacao import DadoInvalido, quantidade_br, texto

ESCOPO_TIPOS = TIPOS_GUARDA + ("avaria",)

LISTA_SQL = """
SELECT iv.id, iv.descricao, iv.status, iv.criado_em, iv.criado_por, iv.fechado_em, iv.fechado_por,
       count(ie.endereco_id) AS enderecos,
       count(ie.contado_em) AS contados,
       (SELECT count(DISTINCT m.endereco_id) FROM wms_movimento m
         WHERE m.doc_tipo = 'inventario' AND m.doc_id = iv.id) AS com_divergencia
  FROM wms_inventario iv
  LEFT JOIN wms_inventario_endereco ie ON ie.inventario_id = iv.id
 WHERE iv.armazem_id = %s
 GROUP BY iv.id
 ORDER BY (iv.status = 'aberto') DESC, iv.id DESC
 LIMIT 100
"""


def _acuracia(enderecos: int, divergentes: int) -> float | None:
    if not enderecos:
        return None
    return round(100.0 * (enderecos - divergentes) / enderecos, 1)


def listar(armazem_id: int, esquema: str | None = None) -> dict:
    linhas = limpar_todas(ler(LISTA_SQL, (armazem_id,), esquema))
    for x in linhas:
        x["acuracia"] = (_acuracia(x["enderecos"], x["com_divergencia"])
                         if x["status"] == "fechado" else None)
    return {"inventarios": linhas}


def detalhe(inventario_id: int, esquema: str | None = None) -> dict:
    cab = ler("SELECT * FROM wms_inventario WHERE id = %s", (inventario_id,), esquema)
    if not cab:
        raise DadoInvalido("Inventário não encontrado.")
    inv = limpar(cab[0])
    enderecos = limpar_todas(ler("""
        SELECT ie.endereco_id, ie.contado_em, ie.contado_por, ie.bloqueou, e.codigo, e.tipo,
               (SELECT count(*) FROM wms_inventario_contagem c
                 WHERE c.inventario_id = ie.inventario_id AND c.endereco_id = ie.endereco_id) AS itens
          FROM wms_inventario_endereco ie JOIN wms_endereco e ON e.id = ie.endereco_id
         WHERE ie.inventario_id = %s ORDER BY e.codigo""", (inventario_id,), esquema))
    contagens = limpar_todas(ler("""
        SELECT c.endereco_id, c.produto_id, c.lote, c.qtd, c.contado_por, c.contado_em,
               p.codigo, p.descricao, p.unidade
          FROM wms_inventario_contagem c JOIN wms_produto p ON p.id = c.produto_id
         WHERE c.inventario_id = %s ORDER BY c.endereco_id, p.codigo""", (inventario_id,), esquema))
    inv["enderecos"] = enderecos
    inv["contagens"] = contagens
    inv["ajustes"] = []
    if inv["status"] == "fechado":
        inv["ajustes"] = limpar_todas(ler("""
            SELECT m.qtd, m.lote, e.codigo AS endereco, p.codigo, p.descricao, p.unidade
              FROM wms_movimento m JOIN wms_endereco e ON e.id = m.endereco_id
              JOIN wms_produto p ON p.id = m.produto_id
             WHERE m.doc_tipo = 'inventario' AND m.doc_id = %s
             ORDER BY e.codigo, p.codigo""", (inventario_id,), esquema))
        div = len({a["endereco"] for a in inv["ajustes"]})
        inv["acuracia"] = _acuracia(len(enderecos), div)
    inv["resumo"] = {"enderecos": len(enderecos),
                     "contados": sum(1 for e in enderecos if e["contado_em"])}
    return inv


def abrir(dados: dict, usuario: str, esquema: str | None = None) -> dict:
    armazem_id = comum.inteiro_id(dados.get("armazem_id"), "o armazém")
    descricao = texto(dados.get("descricao"), "a descrição", maximo=120)
    # "Rua A" é o código A ou os que começam por "A-" — e não os que começam
    # pela LETRA A: o prefixo cru casava a área AVARIA junto com a rua A.
    prefixo = re.sub(r"[^A-Z0-9-]", "", str(dados.get("rua") or "").upper()).strip("-")
    with transacao(esquema) as conn, conn.cursor() as cur:
        cur.execute("""SELECT e.id, e.codigo, e.bloqueado FROM wms_endereco e
                        WHERE e.armazem_id = %s AND e.ativo AND e.tipo = ANY(%s)
                          AND (%s = '' OR e.codigo = %s OR e.codigo LIKE %s)
                        ORDER BY e.codigo FOR UPDATE""",
                    (armazem_id, list(ESCOPO_TIPOS), prefixo, prefixo, prefixo + "-%"))
        alvo = cur.fetchall()
        if not alvo:
            raise DadoInvalido("Nenhum endereço de armazenagem ativo neste escopo.")
        ids = [e["id"] for e in alvo]
        cur.execute("""SELECT DISTINCT e.codigo FROM wms_inventario_endereco ie
                         JOIN wms_inventario iv ON iv.id = ie.inventario_id AND iv.status = 'aberto'
                         JOIN wms_endereco e ON e.id = ie.endereco_id
                        WHERE ie.endereco_id = ANY(%s) ORDER BY e.codigo LIMIT 10""", (ids,))
        ja = [r["codigo"] for r in cur.fetchall()]
        if ja:
            raise DadoInvalido("Há endereços deste escopo em outro inventário aberto: "
                               + ", ".join(ja) + ".")
        cur.execute("""SELECT DISTINCT e.codigo FROM wms_tarefa t
                         JOIN wms_endereco e ON e.id = t.endereco_id
                        WHERE t.status = 'pendente' AND t.endereco_id = ANY(%s)
                        ORDER BY e.codigo LIMIT 10""", (ids,))
        com_tarefa = [r["codigo"] for r in cur.fetchall()]
        if com_tarefa:
            raise DadoInvalido("Há separação pendente em endereços deste escopo ("
                               + ", ".join(com_tarefa) + ") — conclua antes de inventariar.")
        cur.execute("""INSERT INTO wms_inventario(armazem_id, descricao, criado_por)
                       VALUES (%s, %s, %s) RETURNING id""", (armazem_id, descricao, usuario or ""))
        novo = cur.fetchone()["id"]
        for e in alvo:
            cur.execute("""INSERT INTO wms_inventario_endereco(inventario_id, endereco_id, bloqueou)
                           VALUES (%s, %s, %s)""", (novo, e["id"], not e["bloqueado"]))
        livres = [e["id"] for e in alvo if not e["bloqueado"]]
        if livres:
            cur.execute("""UPDATE wms_endereco SET bloqueado = true, motivo_bloqueio = %s,
                                  bloqueado_em = now(), bloqueado_por = %s
                            WHERE id = ANY(%s)""", (f"inventário #{novo}", usuario or "", livres))
        auditar(cur, usuario, "wms_inventario_abrir", str(novo),
                f"{len(alvo)} endereços, escopo {prefixo or 'armazém inteiro'}")
    return detalhe(novo, esquema)


def _travar_aberto(cur, inventario_id: int) -> dict:
    cur.execute("SELECT * FROM wms_inventario WHERE id = %s FOR UPDATE", (inventario_id,))
    inv = cur.fetchone()
    if not inv:
        raise DadoInvalido("Inventário não encontrado.")
    if inv["status"] != "aberto":
        raise DadoInvalido(f"O inventário já está {inv['status']}.")
    return inv


def contar(inventario_id: int, endereco_id: int, itens, usuario: str,
           esquema: str | None = None) -> dict:
    """Registra a contagem de UM endereço — substituindo a anterior dele.
    Lista vazia é "o endereço está vazio", que é uma contagem."""
    if not isinstance(itens, list):
        raise DadoInvalido("Contagem inválida.")
    if len(itens) > 200:
        raise DadoInvalido("No máximo 200 itens por endereço.")
    with transacao(esquema) as conn, conn.cursor() as cur:
        _travar_aberto(cur, inventario_id)
        cur.execute("""SELECT 1 FROM wms_inventario_endereco
                        WHERE inventario_id = %s AND endereco_id = %s""", (inventario_id, endereco_id))
        if not cur.fetchone():
            raise DadoInvalido("Este endereço não está no escopo do inventário.")
        vistos, linhas = set(), []
        for b in itens:
            pid = comum.inteiro_id((b or {}).get("produto_id"), "o produto")
            lote = comum.lote(b.get("lote"))
            q = quantidade_br(b.get("qtd"), "a quantidade contada")
            if q is None or q < 0:
                raise DadoInvalido("Informe a quantidade contada de cada item (zero ou mais).")
            if (pid, lote) in vistos:
                raise DadoInvalido("O mesmo produto e lote aparece duas vezes — some numa linha só.")
            vistos.add((pid, lote))
            cur.execute("SELECT 1 FROM wms_produto WHERE id = %s", (pid,))
            if not cur.fetchone():
                raise DadoInvalido("Produto não encontrado.")
            if q > 0:
                linhas.append((pid, lote, q))
        cur.execute("DELETE FROM wms_inventario_contagem WHERE inventario_id = %s AND endereco_id = %s",
                    (inventario_id, endereco_id))
        for pid, lote, q in linhas:
            cur.execute("""INSERT INTO wms_inventario_contagem(inventario_id, endereco_id, produto_id,
                               lote, qtd, contado_por) VALUES (%s, %s, %s, %s, %s, %s)""",
                        (inventario_id, endereco_id, pid, lote, q, usuario or ""))
        cur.execute("""UPDATE wms_inventario_endereco SET contado_em = now(), contado_por = %s
                        WHERE inventario_id = %s AND endereco_id = %s""",
                    (usuario or "", inventario_id, endereco_id))
    return {"ok": True, "itens": len(linhas)}


def fechar(inventario_id: int, usuario: str, esquema: str | None = None) -> dict:
    with transacao(esquema) as conn, conn.cursor() as cur:
        _travar_aberto(cur, inventario_id)
        cur.execute("""SELECT ie.endereco_id, ie.bloqueou, ie.contado_em, e.codigo
                         FROM wms_inventario_endereco ie JOIN wms_endereco e ON e.id = ie.endereco_id
                        WHERE ie.inventario_id = %s ORDER BY e.codigo""", (inventario_id,))
        escopo = cur.fetchall()
        faltam = [e["codigo"] for e in escopo if not e["contado_em"]]
        if faltam:
            mais = f" e mais {len(faltam) - 10}" if len(faltam) > 10 else ""
            raise DadoInvalido(f"Faltam contar {len(faltam)} endereço(s): "
                               + ", ".join(faltam[:10]) + mais
                               + ". Endereço sem mercadoria se registra como vazio.")
        ids = [e["endereco_id"] for e in escopo]
        cur.execute("""SELECT produto_id, endereco_id, lote, sum(qtd) AS q, max(validade) AS v
                         FROM wms_movimento WHERE endereco_id = ANY(%s)
                        GROUP BY produto_id, endereco_id, lote HAVING sum(qtd) <> 0""", (ids,))
        sistema = {(r["produto_id"], r["endereco_id"], r["lote"]): r for r in cur.fetchall()}
        cur.execute("""SELECT produto_id, endereco_id, lote, qtd FROM wms_inventario_contagem
                        WHERE inventario_id = %s""", (inventario_id,))
        contado = {(r["produto_id"], r["endereco_id"], r["lote"]): Decimal(r["qtd"])
                   for r in cur.fetchall()}
        chaves = set(sistema) | set(contado)
        travar_produtos(cur, [k[0] for k in chaves])
        ajustes, divergentes = 0, set()
        mais_q, menos_q = Decimal(0), Decimal(0)
        for k in sorted(chaves):
            s = Decimal(sistema[k]["q"]) if k in sistema else Decimal(0)
            diff = contado.get(k, Decimal(0)) - s
            if diff == 0:
                continue
            estoque.mov(cur, tipo="ajuste", produto_id=k[0], endereco_id=k[1], lote=k[2],
                        validade=sistema[k]["v"] if k in sistema else None, qtd=diff,
                        doc_tipo="inventario", doc_id=inventario_id, usuario=usuario,
                        motivo=f"inventário #{inventario_id}")
            ajustes += 1
            divergentes.add(k[1])
            if diff > 0:
                mais_q += diff
            else:
                menos_q += -diff
        bloqueados = [e["endereco_id"] for e in escopo if e["bloqueou"]]
        if bloqueados:
            cur.execute("""UPDATE wms_endereco SET bloqueado = false, motivo_bloqueio = '',
                                  bloqueado_em = NULL, bloqueado_por = ''
                            WHERE id = ANY(%s)""", (bloqueados,))
        cur.execute("""UPDATE wms_inventario SET status = 'fechado', fechado_em = now(),
                              fechado_por = %s WHERE id = %s""", (usuario or "", inventario_id))
        auditar(cur, usuario, "wms_inventario_fechar", str(inventario_id),
                f"{len(escopo)} endereços, {len(divergentes)} com divergência, {ajustes} ajustes")
    return {"ok": True, "enderecos": len(escopo), "com_divergencia": len(divergentes),
            "ajustes": ajustes, "acuracia": _acuracia(len(escopo), len(divergentes)),
            "sobra": float(mais_q), "falta": float(menos_q)}


def cancelar(inventario_id: int, usuario: str, esquema: str | None = None) -> dict:
    with transacao(esquema) as conn, conn.cursor() as cur:
        _travar_aberto(cur, inventario_id)
        cur.execute("""UPDATE wms_endereco SET bloqueado = false, motivo_bloqueio = '',
                              bloqueado_em = NULL, bloqueado_por = ''
                        WHERE id IN (SELECT endereco_id FROM wms_inventario_endereco
                                      WHERE inventario_id = %s AND bloqueou)""", (inventario_id,))
        cur.execute("UPDATE wms_inventario SET status = 'cancelado' WHERE id = %s", (inventario_id,))
        auditar(cur, usuario, "wms_inventario_cancelar", str(inventario_id), "")
    return {"ok": True}
