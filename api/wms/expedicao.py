# -*- coding: utf-8 -*-
"""Separação e expedição — do pedido do cliente ao caminhão (tela `wmsexp`).

LIBERAR É RESERVAR. Liberar um pedido cria as tarefas de separação, e cada
tarefa pendente SAI DO DISPONÍVEL do endereço dela: o físico continua lá até
alguém tirar, mas nenhum outro pedido nem movimentação pode prometê-lo de novo.

A ORDEM É FEFO, DEPOIS FIFO. Primeiro o que vence antes (First Expired, First
Out); sem validade, o que entrou antes. Separar pelo endereço mais perto
deixaria no fundo da rua o lote que vence semana que vem — e a perda por
validade de um armazém nasce exatamente assim.

Liberação é tudo-ou-nada: se falta estoque para um item, nenhuma tarefa é
criada e a recusa diz o que falta. Pedido meio reservado prende estoque de
outros sem que ninguém tenha decidido isso.

"Em separação" e "separado" não são status gravados: saem das tarefas.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from . import comum, estoque
from .comum import auditar, ler, limpar, limpar_todas, transacao, travar_produtos
from ..validacao import DadoInvalido, data_br, quantidade_br, texto

LISTA_SQL = """
SELECT p.id, p.status, p.origem, p.numero, p.nf_chave, p.destinatario, p.previsto_para,
       p.placa, p.motorista, p.criado_em, p.criado_por, p.liberado_em, p.expedido_em,
       p.expedido_por, p.cancelado_em, p.motivo_cancelamento,
       dep.cnpj AS depositante_cnpj, dep.razao_social, dep.nome_fantasia,
       coalesce(i.itens, 0) AS itens, coalesce(i.qtd, 0) AS qtd,
       coalesce(t.pendentes, 0) AS tarefas_pendentes,
       coalesce(t.separadas, 0) AS tarefas_separadas,
       coalesce(t.qtd_prevista, 0) AS qtd_prevista,
       coalesce(t.qtd_separada, 0) AS qtd_separada
  FROM wms_pedido p
  JOIN wms_depositante dep ON dep.cnpj = p.depositante_cnpj
  LEFT JOIN (SELECT pedido_id, count(*) AS itens, sum(qtd) AS qtd
               FROM wms_pedido_item GROUP BY pedido_id) i ON i.pedido_id = p.id
  LEFT JOIN (SELECT pedido_id,
                    count(*) FILTER (WHERE status = 'pendente') AS pendentes,
                    count(*) FILTER (WHERE status = 'separada') AS separadas,
                    sum(qtd) FILTER (WHERE status <> 'cancelada') AS qtd_prevista,
                    sum(qtd_separada) FILTER (WHERE status = 'separada') AS qtd_separada
               FROM wms_tarefa GROUP BY pedido_id) t ON t.pedido_id = p.id
 WHERE p.armazem_id = %(a)s
   AND (p.status IN ('aberto', 'liberado')
        OR p.criado_em >= now() - make_interval(days => %(dias)s))
 ORDER BY CASE p.status WHEN 'liberado' THEN 0 WHEN 'aberto' THEN 1 ELSE 2 END,
          p.previsto_para NULLS LAST, p.id DESC
 LIMIT %(lim)s
"""


def situacao(p: dict) -> str:
    """O estado que a tela mostra — calculado, nunca gravado."""
    if p["status"] == "liberado":
        return "em_separacao" if p["tarefas_pendentes"] else "separado"
    return p["status"]


def _enfeitar(p: dict) -> dict:
    p["situacao"] = situacao(p)
    prev = p.get("previsto_para")
    p["atrasado"] = bool(prev and p["status"] in ("aberto", "liberado")
                         and str(prev) < date.today().isoformat())
    p["corte"] = (round(p["qtd_prevista"] - p["qtd_separada"], 3)
                  if p["situacao"] == "separado" and p["qtd_prevista"] else 0)
    return p


def listar(armazem_id: int, *, dias: int = 30, limite: int = 300,
           esquema: str | None = None) -> dict:
    linhas = [_enfeitar(limpar(x)) for x in ler(LISTA_SQL, {
        "a": armazem_id, "dias": max(1, min(int(dias or 30), 365)),
        "lim": max(1, min(int(limite or 300), 1000))}, esquema)]
    cont = {s: 0 for s in ("aberto", "em_separacao", "separado")}
    for p in linhas:
        if p["situacao"] in cont:
            cont[p["situacao"]] += 1
    hoje = ler("""SELECT count(*) AS n FROM wms_pedido WHERE armazem_id = %s
                    AND status = 'expedido' AND expedido_em::date = current_date""",
               (armazem_id,), esquema)[0]
    return {"pedidos": linhas,
            "resumo": {"a_liberar": cont["aberto"], "em_separacao": cont["em_separacao"],
                       "aguardando_expedicao": cont["separado"],
                       "expedidos_hoje": int(hoje["n"] or 0),
                       "atrasados": sum(1 for p in linhas if p["atrasado"])}}


def detalhe(pedido_id: int, esquema: str | None = None) -> dict:
    cab = ler("""SELECT p.*, a.codigo AS armazem, dep.razao_social, dep.nome_fantasia
                   FROM wms_pedido p JOIN wms_armazem a ON a.id = p.armazem_id
                   JOIN wms_depositante dep ON dep.cnpj = p.depositante_cnpj
                  WHERE p.id = %s""", (pedido_id,), esquema)
    if not cab:
        raise DadoInvalido("Pedido não encontrado.")
    p = limpar(cab[0])
    p["itens"] = limpar_todas(ler("""
        SELECT i.id, i.seq, i.produto_id, i.qtd, i.lote, pr.codigo, pr.descricao, pr.unidade,
               coalesce(sum(t.qtd_separada) FILTER (WHERE t.status = 'separada'), 0) AS separado
          FROM wms_pedido_item i JOIN wms_produto pr ON pr.id = i.produto_id
          LEFT JOIN wms_tarefa t ON t.pedido_item_id = i.id
         WHERE i.pedido_id = %s GROUP BY i.id, pr.id ORDER BY i.seq""", (pedido_id,), esquema))
    p["tarefas"] = limpar_todas(ler("""
        SELECT t.id, t.status, t.qtd, t.qtd_separada, t.lote, t.validade, t.separado_em,
               t.separado_por, e.codigo AS endereco, pr.codigo, pr.descricao, pr.unidade
          FROM wms_tarefa t JOIN wms_endereco e ON e.id = t.endereco_id
          JOIN wms_produto pr ON pr.id = t.produto_id
         WHERE t.pedido_id = %s ORDER BY e.codigo, t.id""", (pedido_id,), esquema))
    pend = sum(1 for t in p["tarefas"] if t["status"] == "pendente")
    p["situacao"] = ("em_separacao" if pend else "separado") if p["status"] == "liberado" \
        else p["status"]
    return p


def tarefas_pendentes(armazem_id: int, esquema: str | None = None) -> dict:
    """A LISTA DE SEPARAÇÃO, na ordem do endereço — que é a ordem da rua.
    Separar na ordem em que os pedidos chegaram faria o separador cruzar o
    armazém a cada linha."""
    linhas = limpar_todas(ler("""
        SELECT t.id, t.pedido_id, t.qtd, t.lote, t.validade,
               e.codigo AS endereco, e.bloqueado,
               pr.codigo, pr.descricao, pr.unidade,
               pe.numero AS pedido_numero, pe.previsto_para, pe.destinatario,
               dep.razao_social, dep.nome_fantasia
          FROM wms_tarefa t
          JOIN wms_endereco e ON e.id = t.endereco_id
          JOIN wms_produto pr ON pr.id = t.produto_id
          JOIN wms_pedido pe ON pe.id = t.pedido_id
          JOIN wms_depositante dep ON dep.cnpj = pe.depositante_cnpj
         WHERE t.status = 'pendente' AND pe.armazem_id = %s
         ORDER BY e.codigo, t.pedido_id, t.id""", (armazem_id,), esquema))
    return {"tarefas": linhas, "total": len(linhas),
            "pedidos": len({t["pedido_id"] for t in linhas})}


def proposta_de_nf(nf: dict, depositante: str | None, esquema: str | None = None) -> dict:
    """Os itens de uma nota do Avacorp casados com os produtos do depositante
    pelo CÓDIGO DO CLIENTE. O que não casar vem separado e DITO: pedido montado
    em silêncio sem um item da nota é pedido errado com cara de certo."""
    dep = comum.cnpj(depositante or (nf.get("remetente") or {}).get("cnpj"))
    prods = {p["codigo"]: p for p in ler(
        "SELECT id, codigo, descricao, unidade, ativo FROM wms_produto WHERE depositante_cnpj = %s",
        (dep,), esquema)}
    casados, faltando = [], []
    for i in nf.get("itens") or []:
        p = prods.get((i.get("codigo") or "").strip())
        alvo = casados if p and p["ativo"] else faltando
        alvo.append({"produto_id": p["id"] if p else None, "codigo": i.get("codigo") or "",
                     "descricao": (p or i).get("descricao") or "", "qtd": i.get("qtd") or 0,
                     "unidade": (p or i).get("unidade") or ""})
    return {"depositante_cnpj": dep, "nf_chave": nf.get("chave") or "",
            "nf_numero": nf.get("nf_numero"),
            "destinatario": ((nf.get("destinatario") or {}).get("razao_social") or ""),
            "itens": casados, "faltando": faltando}


def criar(dados: dict, usuario: str, esquema: str | None = None) -> dict:
    armazem_id = comum.inteiro_id(dados.get("armazem_id"), "o armazém")
    dep = comum.cnpj(dados.get("depositante_cnpj"))
    numero = texto(dados.get("numero"), "o número do pedido", maximo=40)
    destinatario = texto(dados.get("destinatario"), "o destinatário", maximo=120)
    previsto = data_br(dados.get("previsto_para"), "a data prevista")
    chave = comum.chave_nf(dados.get("nf_chave"))
    obs = texto(dados.get("observacao"), "a observação", maximo=500)
    origem = "erp" if dados.get("origem") == "erp" and chave else "manual"
    brutos = dados.get("itens") or []
    if not isinstance(brutos, list) or not brutos:
        raise DadoInvalido("Informe ao menos um item do pedido.")
    if len(brutos) > 300:
        raise DadoInvalido("No máximo 300 itens por pedido.")
    with transacao(esquema) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM wms_armazem WHERE id = %s AND ativo", (armazem_id,))
        if not cur.fetchone():
            raise DadoInvalido("Armazém não encontrado ou inativo.")
        cur.execute("SELECT ativo FROM wms_depositante WHERE cnpj = %s", (dep,))
        d = cur.fetchone()
        if not d or not d["ativo"]:
            raise DadoInvalido("Depositante não cadastrado ou inativo.")
        itens = []
        for b in brutos:
            pid = comum.inteiro_id((b or {}).get("produto_id"), "o produto de cada item")
            cur.execute("SELECT depositante_cnpj, ativo, codigo FROM wms_produto WHERE id = %s", (pid,))
            p = cur.fetchone()
            if not p or p["depositante_cnpj"] != dep:
                raise DadoInvalido("Há item de produto que não é deste depositante.")
            if not p["ativo"]:
                raise DadoInvalido(f"O produto {p['codigo']} está inativo.")
            q = quantidade_br(b.get("qtd"), "a quantidade")
            if q is None or q <= 0:
                raise DadoInvalido(f"Informe a quantidade do produto {p['codigo']}, maior que zero.")
            itens.append((pid, q, comum.lote(b.get("lote"))))
        cur.execute(
            """INSERT INTO wms_pedido(armazem_id, depositante_cnpj, origem, numero, nf_chave,
                   destinatario, previsto_para, observacao, criado_por)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (armazem_id, dep, origem, numero, chave, destinatario, previsto, obs, usuario or ""))
        novo = cur.fetchone()["id"]
        for seq, (pid, q, lote) in enumerate(itens, start=1):
            cur.execute("""INSERT INTO wms_pedido_item(pedido_id, seq, produto_id, qtd, lote)
                           VALUES (%s, %s, %s, %s, %s)""", (novo, seq, pid, q, lote))
        auditar(cur, usuario, "wms_pedido_criar", str(novo), f"{origem} {len(itens)} itens")
    return detalhe(novo, esquema)


CANDIDATOS_SQL = """
SELECT s.endereco_id, s.lote, s.validade, s.primeira_entrada, e.codigo,
       s.qtd - coalesce(r.res, 0) AS livre
  FROM wms_saldo s
  JOIN wms_endereco e ON e.id = s.endereco_id
  LEFT JOIN (SELECT endereco_id, lote, sum(qtd) AS res FROM wms_tarefa
              WHERE status = 'pendente' AND produto_id = %(p)s
              GROUP BY endereco_id, lote) r
         ON r.endereco_id = s.endereco_id AND r.lote = s.lote
 WHERE s.produto_id = %(p)s AND e.armazem_id = %(a)s
   AND e.ativo AND NOT e.bloqueado
   AND e.tipo IN ('porta_palete', 'picking', 'blocado')
   AND (%(lote)s = '' OR s.lote = %(lote)s)
 ORDER BY s.validade ASC NULLS LAST, s.primeira_entrada ASC, e.codigo, s.lote
"""


def _area_expedicao(cur, armazem_id: int) -> dict:
    cur.execute("""SELECT * FROM wms_endereco WHERE armazem_id = %s AND tipo = 'expedicao'
                     AND ativo AND NOT bloqueado ORDER BY codigo LIMIT 1""", (armazem_id,))
    e = cur.fetchone()
    if not e:
        raise DadoInvalido("O armazém não tem área de expedição livre — cadastre um endereço "
                           "do tipo Expedição.")
    return e


def _travar(cur, pedido_id: int) -> dict:
    cur.execute("SELECT * FROM wms_pedido WHERE id = %s FOR UPDATE", (pedido_id,))
    p = cur.fetchone()
    if not p:
        raise DadoInvalido("Pedido não encontrado.")
    return p


def liberar(pedido_id: int, usuario: str, esquema: str | None = None) -> dict:
    with transacao(esquema) as conn, conn.cursor() as cur:
        p = _travar(cur, pedido_id)
        if p["status"] != "aberto":
            raise DadoInvalido(f"O pedido está {p['status']} — só se libera pedido aberto.")
        _area_expedicao(cur, p["armazem_id"])
        cur.execute("""SELECT i.*, pr.codigo, pr.unidade FROM wms_pedido_item i
                         JOIN wms_produto pr ON pr.id = i.produto_id
                        WHERE i.pedido_id = %s ORDER BY i.seq""", (pedido_id,))
        itens = cur.fetchall()
        travar_produtos(cur, [i["produto_id"] for i in itens])
        faltas, criadas = [], 0
        for it in itens:
            falta = Decimal(it["qtd"])
            # as tarefas entram UMA A UMA: o item seguinte do mesmo produto já
            # enxerga a reserva que este acabou de fazer
            cur.execute(CANDIDATOS_SQL, {"p": it["produto_id"], "a": p["armazem_id"],
                                         "lote": it["lote"]})
            for c in cur.fetchall():
                if falta <= 0:
                    break
                livre = Decimal(c["livre"])
                if livre <= 0:
                    continue
                q = min(livre, falta)
                cur.execute("""INSERT INTO wms_tarefa(pedido_id, pedido_item_id, produto_id,
                                   endereco_id, lote, validade, qtd)
                               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                            (pedido_id, it["id"], it["produto_id"], c["endereco_id"],
                             c["lote"], c["validade"], q))
                criadas += 1
                falta -= q
            if falta > 0:
                lote = f" (lote {it['lote']})" if it["lote"] else ""
                faltas.append(f"{it['codigo']}{lote}: faltam {estoque.fmt(falta)} {it['unidade']}")
        if faltas:
            raise DadoInvalido("Estoque disponível insuficiente — nada foi reservado. "
                               + "; ".join(faltas) + ".")
        cur.execute("""UPDATE wms_pedido SET status = 'liberado', liberado_em = now(),
                              liberado_por = %s WHERE id = %s""", (usuario or "", pedido_id))
        auditar(cur, usuario, "wms_pedido_liberar", str(pedido_id), f"{criadas} tarefas")
    return detalhe(pedido_id, esquema)


def confirmar_tarefa(tarefa_id: int, qtd, usuario: str, esquema: str | None = None) -> dict:
    """O separador tirou do endereço e levou para a expedição. Quantidade menor
    que a prevista é CORTE (faltou no endereço) — fica registrado e o pedido
    sai com o que foi separado."""
    with transacao(esquema) as conn, conn.cursor() as cur:
        cur.execute("""SELECT t.*, p.armazem_id, p.status AS pedido_status
                         FROM wms_tarefa t JOIN wms_pedido p ON p.id = t.pedido_id
                        WHERE t.id = %s FOR UPDATE OF t""", (tarefa_id,))
        t = cur.fetchone()
        if not t:
            raise DadoInvalido("Tarefa não encontrada.")
        if t["status"] != "pendente":
            raise DadoInvalido(f"Esta tarefa já está {t['status']}.")
        if t["pedido_status"] != "liberado":
            raise DadoInvalido(f"O pedido está {t['pedido_status']}.")
        q = quantidade_br(qtd, "a quantidade separada")
        q = Decimal(t["qtd"]) if q is None else q
        if q < 0 or q > t["qtd"]:
            raise DadoInvalido(f"A quantidade separada fica entre 0 e {estoque.fmt(t['qtd'])}.")
        destino = _area_expedicao(cur, t["armazem_id"])
        if q > 0:
            estoque.transferir_cur(cur, origem=estoque.endereco(cur, t["endereco_id"]),
                                   destino=destino, produto_id=t["produto_id"], lote=t["lote"],
                                   qtd=q, usuario=usuario, doc_tipo="separacao",
                                   doc_id=t["pedido_id"], consome_reserva=True)
        cur.execute("""UPDATE wms_tarefa SET status = 'separada', qtd_separada = %s,
                              separado_em = now(), separado_por = %s, destino_id = %s
                        WHERE id = %s""", (q, usuario or "", destino["id"], tarefa_id))
        auditar(cur, usuario, "wms_tarefa_confirmar", str(tarefa_id),
                f"pedido {t['pedido_id']} qtd {estoque.fmt(q)} de {estoque.fmt(t['qtd'])}")
    return {"ok": True, "corte": float(Decimal(t["qtd"]) - q)}


def expedir(pedido_id: int, dados: dict, usuario: str, esquema: str | None = None) -> dict:
    placa = comum.placa(dados.get("placa"), obrigatoria=True)
    motorista = texto(dados.get("motorista"), "o motorista", maximo=80)
    chave = comum.chave_nf(dados.get("nf_chave"))
    with transacao(esquema) as conn, conn.cursor() as cur:
        p = _travar(cur, pedido_id)
        if p["status"] == "aberto":
            raise DadoInvalido("Libere o pedido para separação antes de expedir.")
        if p["status"] != "liberado":
            raise DadoInvalido(f"O pedido já está {p['status']}.")
        cur.execute("SELECT count(*) AS n FROM wms_tarefa WHERE pedido_id = %s AND status = 'pendente'",
                    (pedido_id,))
        pend = cur.fetchone()["n"]
        if pend:
            raise DadoInvalido(f"Ainda há {pend} tarefa(s) de separação pendente(s).")
        cur.execute("""SELECT produto_id, lote, destino_id, max(validade) AS validade,
                              sum(qtd_separada) AS q
                         FROM wms_tarefa
                        WHERE pedido_id = %s AND status = 'separada' AND qtd_separada > 0
                        GROUP BY produto_id, lote, destino_id""", (pedido_id,))
        grupos = cur.fetchall()
        if not grupos:
            raise DadoInvalido("Nada foi separado — cancele o pedido em vez de expedir.")
        travar_produtos(cur, [g["produto_id"] for g in grupos])
        for g in grupos:
            estoque.mov(cur, tipo="saida", produto_id=g["produto_id"], endereco_id=g["destino_id"],
                        lote=g["lote"], validade=g["validade"], qtd=-Decimal(g["q"]),
                        doc_tipo="expedicao", doc_id=pedido_id, usuario=usuario)
        cur.execute("""UPDATE wms_pedido SET status = 'expedido', placa = %s, motorista = %s,
                              nf_chave = CASE WHEN %s = '' THEN nf_chave ELSE %s END,
                              expedido_em = now(), expedido_por = %s WHERE id = %s""",
                    (placa, motorista, chave, chave, usuario or "", pedido_id))
        auditar(cur, usuario, "wms_pedido_expedir", str(pedido_id), placa)
    return detalhe(pedido_id, esquema)


def cancelar(pedido_id: int, motivo, usuario: str, esquema: str | None = None) -> dict:
    """Cancela; o que já tinha sido separado VOLTA para o endereço de origem
    (estorno com movimento novo — o kardex guarda a ida e a volta)."""
    motivo = texto(motivo, "o motivo do cancelamento", maximo=200, obrigatorio=True)
    with transacao(esquema) as conn, conn.cursor() as cur:
        p = _travar(cur, pedido_id)
        if p["status"] not in ("aberto", "liberado"):
            raise DadoInvalido(f"O pedido já está {p['status']}.")
        cur.execute("""SELECT * FROM wms_tarefa WHERE pedido_id = %s AND status = 'separada'
                          AND qtd_separada > 0""", (pedido_id,))
        for t in cur.fetchall():
            estoque.transferir_cur(cur, origem=estoque.endereco(cur, t["destino_id"]),
                                   destino=estoque.endereco(cur, t["endereco_id"]),
                                   produto_id=t["produto_id"], lote=t["lote"],
                                   qtd=Decimal(t["qtd_separada"]), usuario=usuario,
                                   doc_tipo="separacao", doc_id=pedido_id,
                                   motivo="estorno: pedido cancelado",
                                   consome_reserva=True, estorno=True)
        cur.execute("UPDATE wms_tarefa SET status = 'cancelada' WHERE pedido_id = %s AND status = 'pendente'",
                    (pedido_id,))
        cur.execute("""UPDATE wms_pedido SET status = 'cancelado', cancelado_em = now(),
                              cancelado_por = %s, motivo_cancelamento = %s WHERE id = %s""",
                    (usuario or "", motivo, pedido_id))
        auditar(cur, usuario, "wms_pedido_cancelar", str(pedido_id), motivo)
    return {"ok": True}
