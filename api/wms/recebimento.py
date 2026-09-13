# -*- coding: utf-8 -*-
"""Recebimento — da nota do cliente à mercadoria na doca (tela `wmsrec`).

A CONFERÊNCIA É CEGA. Enquanto o recebimento está aberto, a quantidade da
nota NÃO sai do servidor: quem confere conta o que está na frente dele, e não
"confirma" o número impresso. Conferência que vê a nota vira carimbo — e a
divergência que o recebimento existe para achar some justamente ali. A nota
volta a aparecer quando a conferência fecha, lado a lado com o contado.

A DIVERGÊNCIA não é coluna: é `conferido − nota`, calculada na leitura.

Fechar a conferência é o que dá ENTRADA no estoque — na doca (o que chegou
bom) e na área de avaria (o que chegou avariado). Dali a mercadoria sai por
armazenagem, que é movimentação de estoque, e não mais estado do recebimento.
"""
from __future__ import annotations

from decimal import Decimal

from . import cadastro, comum, estoque
from .comum import auditar, ler, limpar, limpar_todas, transacao
from ..validacao import DadoInvalido, data_br, inteiro, quantidade_br, texto

LISTA_SQL = """
SELECT r.id, r.status, r.origem, r.nf_chave, r.nf_numero, r.nf_serie, r.nf_emissao,
       r.placa, r.criado_em, r.criado_por, r.conferido_em, r.conferido_por,
       r.cancelado_em, r.motivo_cancelamento,
       round(extract(epoch FROM now() - r.criado_em)::numeric / 3600, 1) AS aberto_ha_h,
       d.codigo AS doca, dep.cnpj AS depositante_cnpj, dep.razao_social, dep.nome_fantasia,
       count(i.id) AS itens,
       count(i.qtd_conferida) AS conferidos,
       sum(i.qtd_nf) AS qtd_nf,
       sum(i.qtd_conferida) AS qtd_conferida,
       sum(i.qtd_avaria) AS qtd_avaria,
       count(*) FILTER (WHERE i.qtd_conferida IS NOT NULL
                          AND i.qtd_conferida <> i.qtd_nf) AS itens_divergentes
  FROM wms_recebimento r
  JOIN wms_endereco d ON d.id = r.doca_id
  JOIN wms_depositante dep ON dep.cnpj = r.depositante_cnpj
  LEFT JOIN wms_recebimento_item i ON i.recebimento_id = r.id
 WHERE r.armazem_id = %(a)s
   AND (%(st)s::text IS NULL OR r.status = %(st)s)
   AND (r.status = 'aberto' OR r.criado_em >= now() - make_interval(days => %(dias)s))
 GROUP BY r.id, d.codigo, dep.cnpj
 ORDER BY (r.status = 'aberto') DESC, r.id DESC
 LIMIT %(lim)s
"""


def _cego(r: dict) -> dict:
    """Recebimento aberto não entrega a quantidade da nota, nem nada que a
    deduza (a soma e a contagem de divergentes)."""
    if r.get("status") == "aberto":
        r["qtd_nf"] = None
        r["itens_divergentes"] = None
    return r


def listar(armazem_id: int, *, status: str | None = None, dias: int = 30,
           limite: int = 300, esquema: str | None = None) -> dict:
    if status and status not in ("aberto", "conferido", "cancelado"):
        raise DadoInvalido("Situação desconhecida.")
    linhas = ler(LISTA_SQL, {"a": armazem_id, "st": status or None,
                             "dias": max(1, min(int(dias or 30), 365)),
                             "lim": max(1, min(int(limite or 300), 1000))}, esquema)
    linhas = [_cego(limpar(x)) for x in linhas]
    hoje = ler("""SELECT count(*) FILTER (WHERE status = 'aberto') AS a_conferir,
                         count(*) FILTER (WHERE status = 'conferido'
                                            AND conferido_em::date = current_date) AS conferidos_hoje,
                         count(*) FILTER (WHERE status = 'aberto'
                                            AND criado_em < now() - interval '24 hours') AS abertos_24h
                    FROM wms_recebimento WHERE armazem_id = %s""", (armazem_id,), esquema)[0]
    div = ler("""SELECT count(DISTINCT r.id) AS n FROM wms_recebimento r
                   JOIN wms_recebimento_item i ON i.recebimento_id = r.id
                  WHERE r.armazem_id = %s AND r.status = 'conferido'
                    AND r.conferido_em >= now() - interval '30 days'
                    AND i.qtd_conferida <> i.qtd_nf""", (armazem_id,), esquema)[0]
    conf30 = ler("""SELECT count(*) AS n FROM wms_recebimento
                     WHERE armazem_id = %s AND status = 'conferido'
                       AND conferido_em >= now() - interval '30 days'""", (armazem_id,), esquema)[0]
    return {"recebimentos": linhas,
            "resumo": {**{k: int(v or 0) for k, v in hoje.items()},
                       "divergentes_30d": int(div["n"] or 0),
                       "conferidos_30d": int(conf30["n"] or 0)}}


def detalhe(recebimento_id: int, esquema: str | None = None) -> dict:
    cab = ler("""SELECT r.*, a.codigo AS armazem, d.codigo AS doca,
                        dep.razao_social, dep.nome_fantasia
                   FROM wms_recebimento r
                   JOIN wms_armazem a ON a.id = r.armazem_id
                   JOIN wms_endereco d ON d.id = r.doca_id
                   JOIN wms_depositante dep ON dep.cnpj = r.depositante_cnpj
                  WHERE r.id = %s""", (recebimento_id,), esquema)
    if not cab:
        raise DadoInvalido("Recebimento não encontrado.")
    r = limpar(cab[0])
    itens = limpar_todas(ler("""
        SELECT i.id, i.seq, i.produto_id, i.qtd_nf, i.qtd_conferida, i.qtd_avaria,
               i.lote, i.validade, i.conferido_em, i.conferido_por,
               p.codigo, p.descricao, p.unidade, p.controla_lote, p.controla_validade
          FROM wms_recebimento_item i JOIN wms_produto p ON p.id = i.produto_id
         WHERE i.recebimento_id = %s ORDER BY i.seq""", (recebimento_id,), esquema))
    cego = r["status"] == "aberto"
    falta = sobra = avaria = 0.0
    divergentes = 0
    for i in itens:
        if cego:
            i["qtd_nf"] = None
            i["divergencia"] = None
            continue
        if i["qtd_conferida"] is None:
            i["divergencia"] = None
            continue
        dv = round(i["qtd_conferida"] - i["qtd_nf"], 3)
        i["divergencia"] = dv
        divergentes += dv != 0
        falta += -dv if dv < 0 else 0
        sobra += dv if dv > 0 else 0
        avaria += i["qtd_avaria"] or 0
    r["itens"] = itens
    r["cego"] = cego
    r["resumo"] = {"itens": len(itens),
                   "conferidos": sum(1 for i in itens if i["qtd_conferida"] is not None),
                   "divergentes": None if cego else divergentes,
                   "falta": None if cego else round(falta, 3),
                   "sobra": None if cego else round(sobra, 3),
                   "avaria": round(sum(i["qtd_avaria"] or 0 for i in itens), 3)}
    return r


def abrir(dados: dict, usuario: str, *, nf_erp: dict | None = None,
          esquema: str | None = None) -> dict:
    """Abre o recebimento — da nota do Avacorp (`nf_erp`) ou à mão."""
    armazem_id = comum.inteiro_id(dados.get("armazem_id"), "o armazém")
    doca_id = comum.inteiro_id(dados.get("doca_id"), "a doca")
    placa = comum.placa(dados.get("placa"))
    obs = texto(dados.get("observacao"), "a observação", maximo=500)
    with transacao(esquema) as conn, conn.cursor() as cur:
        doca = estoque.endereco(cur, doca_id)
        if doca["armazem_id"] != armazem_id or doca["tipo"] != "doca" or not doca["ativo"]:
            raise DadoInvalido("Escolha uma doca ativa deste armazém.")
        if nf_erp:
            dep = comum.cnpj(dados.get("depositante_cnpj") or nf_erp["remetente"]["cnpj"])
            for parte in (nf_erp.get("remetente") or {}, nf_erp.get("destinatario") or {}):
                if parte.get("cnpj") == dep and parte.get("razao_social"):
                    cadastro.garantir_depositante(cur, parte, usuario)
            if not nf_erp.get("itens"):
                raise DadoInvalido("A nota está no Avacorp sem itens — abra o recebimento manual "
                                   "e informe os itens.")
            chave = comum.chave_nf(nf_erp.get("chave"), obrigatoria=True)
            numero, serie = nf_erp.get("nf_numero"), str(nf_erp.get("nf_serie") or "")[:5]
            emissao = data_br(nf_erp.get("nf_emissao"), "a emissão")
            emitente = comum.cnpj(nf_erp["remetente"]["cnpj"], "o emitente") \
                if nf_erp.get("remetente", {}).get("cnpj") else ""
            valor = nf_erp.get("valor_mercadoria")
            peso = nf_erp.get("peso_kg")
            origem = "erp"
        else:
            dep = comum.cnpj(dados.get("depositante_cnpj"))
            chave = comum.chave_nf(dados.get("nf_chave"))
            n = dados.get("nf_numero")
            numero = None if n in (None, "") else inteiro(n, "o número da nota", minimo=1, maximo=999999999)
            serie = texto(dados.get("nf_serie"), "a série", maximo=5)
            emissao = data_br(dados.get("nf_emissao"), "a emissão")
            emitente, valor, peso, origem = "", None, None, "manual"
        cur.execute("SELECT ativo FROM wms_depositante WHERE cnpj = %s", (dep,))
        d = cur.fetchone()
        if not d:
            raise DadoInvalido("Depositante não cadastrado — cadastre-o (ou traga do Avacorp) antes.")
        if not d["ativo"]:
            raise DadoInvalido("O depositante está inativo.")
        itens: list[tuple[int, Decimal]] = []
        if nf_erp:
            for i in nf_erp["itens"]:
                codigo = (i.get("codigo") or i.get("descricao") or "SEM-CODIGO")[:60]
                pid = cadastro.garantir_produto(cur, dep, codigo, i.get("descricao") or codigo,
                                                i.get("unidade") or "UN")
                q = quantidade_br(i.get("qtd"), "a quantidade da nota") or Decimal(0)
                itens.append((pid, q))
        else:
            brutos = dados.get("itens") or []
            if not isinstance(brutos, list) or not brutos:
                raise DadoInvalido("Informe ao menos um item do recebimento.")
            if len(brutos) > 500:
                raise DadoInvalido("No máximo 500 itens por recebimento.")
            for b in brutos:
                pid = comum.inteiro_id((b or {}).get("produto_id"), "o produto de cada item")
                cur.execute("SELECT depositante_cnpj, ativo FROM wms_produto WHERE id = %s", (pid,))
                p = cur.fetchone()
                if not p or p["depositante_cnpj"] != dep:
                    raise DadoInvalido("Há item de produto que não é deste depositante.")
                q = quantidade_br(b.get("qtd_nf"), "a quantidade da nota")
                if q is None or q <= 0:
                    raise DadoInvalido("Cada item precisa da quantidade da nota, maior que zero.")
                itens.append((pid, q))
        cur.execute(
            """INSERT INTO wms_recebimento(armazem_id, doca_id, depositante_cnpj, origem, nf_chave,
                   nf_numero, nf_serie, nf_emissao, emitente_cnpj, valor_mercadoria, peso_kg,
                   placa, observacao, criado_por)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (armazem_id, doca_id, dep, origem, chave, numero, serie, emissao, emitente,
             valor, peso, placa, obs, usuario or ""))
        novo = cur.fetchone()["id"]
        for seq, (pid, q) in enumerate(itens, start=1):
            cur.execute("""INSERT INTO wms_recebimento_item(recebimento_id, seq, produto_id, qtd_nf)
                           VALUES (%s, %s, %s, %s)""", (novo, seq, pid, q))
        auditar(cur, usuario, "wms_recebimento_abrir", str(novo),
                f"{origem} nf {numero or '-'} {len(itens)} itens")
    return detalhe(novo, esquema)


def _travar_aberto(cur, recebimento_id: int) -> dict:
    cur.execute("SELECT * FROM wms_recebimento WHERE id = %s FOR UPDATE", (recebimento_id,))
    r = cur.fetchone()
    if not r:
        raise DadoInvalido("Recebimento não encontrado.")
    if r["status"] != "aberto":
        raise DadoInvalido(f"Este recebimento já está {r['status']}.")
    return r


def conferir(recebimento_id: int, itens, usuario: str, esquema: str | None = None) -> dict:
    """Grava o que foi contado — parcial: pode-se salvar e continuar depois.

    Item que não vem na lista não muda; `qtd_conferida` vazia DESFAZ a contagem
    daquele item (chave ausente não mexe, chave vazia limpa)."""
    if not isinstance(itens, list) or not itens:
        raise DadoInvalido("Nada para gravar.")
    with transacao(esquema) as conn, conn.cursor() as cur:
        _travar_aberto(cur, recebimento_id)
        for b in itens:
            iid = comum.inteiro_id((b or {}).get("id"), "o item")
            q = quantidade_br(b.get("qtd_conferida"), "a quantidade conferida")
            av = quantidade_br(b.get("qtd_avaria"), "a quantidade avariada") or Decimal(0)
            if q is not None and q < 0 or av < 0:
                raise DadoInvalido("Quantidade conferida não pode ser negativa.")
            if q is not None and av > q:
                raise DadoInvalido("A avaria é parte do conferido — não pode ser maior que ele.")
            if q is None:
                av = Decimal(0)
            val = data_br(b.get("validade"), "a validade")
            cur.execute(
                """UPDATE wms_recebimento_item
                      SET qtd_conferida = %s, qtd_avaria = %s, lote = %s, validade = %s,
                          conferido_em = CASE WHEN %s::numeric IS NULL THEN NULL ELSE now() END,
                          conferido_por = %s
                    WHERE id = %s AND recebimento_id = %s""",
                (q, av, comum.lote(b.get("lote")), val, q,
                 usuario if q is not None else "", iid, recebimento_id))
            if not cur.rowcount:
                raise DadoInvalido("Item não pertence a este recebimento.")
    return detalhe(recebimento_id, esquema)


def fechar(recebimento_id: int, usuario: str, esquema: str | None = None) -> dict:
    """Fecha a conferência e dá ENTRADA no estoque — de uma vez, ou nada."""
    with transacao(esquema) as conn, conn.cursor() as cur:
        r = _travar_aberto(cur, recebimento_id)
        cur.execute("""SELECT i.*, p.codigo, p.controla_lote, p.controla_validade
                         FROM wms_recebimento_item i JOIN wms_produto p ON p.id = i.produto_id
                        WHERE i.recebimento_id = %s ORDER BY i.seq""", (recebimento_id,))
        itens = cur.fetchall()
        faltam = [i["codigo"] for i in itens if i["qtd_conferida"] is None]
        if faltam:
            mais = f" e mais {len(faltam) - 8}" if len(faltam) > 8 else ""
            raise DadoInvalido(f"Faltam conferir {len(faltam)} item(ns): "
                               + ", ".join(faltam[:8]) + mais + ".")
        for i in itens:
            if i["qtd_conferida"] > 0 and i["controla_lote"] and not i["lote"]:
                raise DadoInvalido(f"O produto {i['codigo']} controla lote — informe o lote.")
            if i["qtd_conferida"] > 0 and i["controla_validade"] and not i["validade"]:
                raise DadoInvalido(f"O produto {i['codigo']} controla validade — informe a validade.")
        if not any(i["qtd_conferida"] > 0 for i in itens):
            raise DadoInvalido("Nada foi conferido — se a carga não chegou, cancele o recebimento.")
        area_avaria = None
        if any(i["qtd_avaria"] > 0 for i in itens):
            cur.execute("""SELECT * FROM wms_endereco WHERE armazem_id = %s AND tipo = 'avaria'
                             AND ativo AND NOT bloqueado ORDER BY codigo LIMIT 1""",
                        (r["armazem_id"],))
            area_avaria = cur.fetchone()
            if not area_avaria:
                raise DadoInvalido("Houve avaria e o armazém não tem área de avaria livre — "
                                   "cadastre um endereço do tipo Avaria.")
        comum.travar_produtos(cur, [i["produto_id"] for i in itens])
        for i in itens:
            boa = i["qtd_conferida"] - i["qtd_avaria"]
            if boa > 0:
                estoque.mov(cur, tipo="entrada", produto_id=i["produto_id"],
                            endereco_id=r["doca_id"], lote=i["lote"], validade=i["validade"],
                            qtd=boa, doc_tipo="recebimento", doc_id=recebimento_id,
                            usuario=usuario)
            if i["qtd_avaria"] > 0:
                estoque.mov(cur, tipo="entrada", produto_id=i["produto_id"],
                            endereco_id=area_avaria["id"], lote=i["lote"],
                            validade=i["validade"], qtd=i["qtd_avaria"],
                            doc_tipo="recebimento", doc_id=recebimento_id,
                            usuario=usuario, motivo="avaria no recebimento")
        cur.execute("""UPDATE wms_recebimento SET status = 'conferido', conferido_em = now(),
                              conferido_por = %s WHERE id = %s""", (usuario or "", recebimento_id))
        auditar(cur, usuario, "wms_recebimento_fechar", str(recebimento_id),
                f"{len(itens)} itens")
    return detalhe(recebimento_id, esquema)


def cancelar(recebimento_id: int, motivo, usuario: str, esquema: str | None = None) -> dict:
    motivo = texto(motivo, "o motivo do cancelamento", maximo=200, obrigatorio=True)
    with transacao(esquema) as conn, conn.cursor() as cur:
        _travar_aberto(cur, recebimento_id)
        cur.execute("""UPDATE wms_recebimento SET status = 'cancelado', cancelado_em = now(),
                              cancelado_por = %s, motivo_cancelamento = %s WHERE id = %s""",
                    (usuario or "", motivo, recebimento_id))
        auditar(cur, usuario, "wms_recebimento_cancelar", str(recebimento_id), motivo)
    return {"ok": True}
