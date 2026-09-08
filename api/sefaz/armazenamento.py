# -*- coding: utf-8 -*-
"""A caixa e os documentos no banco da casa — e as regras que os protegem.

Este módulo é PURO sobre o banco: nada aqui fala com a SEFAZ. Quem fala é
`distribuicao.py`, e a separação é o que permite testar as duas regras difíceis
(o resumo que vira documento, e o NSU que só avança) sem rede nenhuma.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from .. import pglocal

log = logging.getLogger("cortex.sefaz")

# Redirecionado pelos testes para o schema descartável (fixture `esquema_pg`).
# Um ponto só para esquecer — e esquecer aqui escreve em PRODUÇÃO.
ESQUEMA: str | None = None

#: NSU tem 15 dígitos, zero à esquerda. Comparar como TEXTO só funciona porque
#: o zero à esquerda é obrigatório — e é por isso que ele nunca é guardado como
#: inteiro: `'000000000000012' < '000000000000100'` é verdade, `12 < 100`
#: também, mas `'12' < '100'` é FALSO. Um `int()` no meio do caminho e a
#: varredura passa a achar que já leu o que não leu.
NSU_ZERO = "0" * 15


def _esq() -> str | None:
    return ESQUEMA


def nsu(valor) -> str:
    """Normaliza para os 15 dígitos com zero à esquerda."""
    d = re.sub(r"[^0-9]", "", str(valor or ""))
    return d.rjust(15, "0")[-15:] if d else NSU_ZERO


# ------------------------------------------------------------------ a caixa

def caixa(cnpj: str) -> dict | None:
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM dfe_caixa WHERE cnpj = %s", (cnpj,))
        r = cur.fetchone()
        return dict(r) if r else None


def caixas(so_ativas: bool = True) -> list[dict]:
    sql = "SELECT * FROM dfe_caixa"
    if so_ativas:
        sql += " WHERE ativo"
    sql += " ORDER BY cnpj"
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def abrir_caixa(cnpj: str, apelido: str = "", uf: str = "") -> dict:
    """Registra um CNPJ na recolha. Idempotente: reabrir NÃO zera o NSU.

    Zerar seria reler meses de documento e queimar a cota do serviço por um
    clique repetido — e o `DO NOTHING` é o que impede isso.
    """
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO dfe_caixa (cnpj, apelido, uf) VALUES (%s, %s, %s) "
            "ON CONFLICT (cnpj) DO UPDATE SET apelido = EXCLUDED.apelido, "
            "uf = coalesce(EXCLUDED.uf, dfe_caixa.uf), ativo = true",
            (cnpj, apelido or None, (uf or "").upper()[:2] or None))
        conn.commit()
    return caixa(cnpj)


def marcar_consulta(cnpj: str, *, ultimo_nsu: str | None = None,
                    max_nsu: str | None = None, cstat: str = "",
                    motivo: str = "") -> None:
    """Grava o resultado de UM lote. Chamado a cada lote, não no fim.

    O NSU SÓ AVANÇA. Um lote que volte com NSU menor (a SEFAZ repetindo, uma
    resposta fora de ordem, um retry) não pode fazer a varredura andar para
    trás — seria reler o que já está guardado e, pior, ficar em laço. A guarda
    é aqui, no `greatest`, e não em quem chama: quem chama esquece.
    """
    campos = ["ultima_consulta = now()", "ultimo_cstat = %s", "ultimo_motivo = %s"]
    args: list = [cstat or None, (motivo or None)]
    if ultimo_nsu is not None:
        campos.append("ultimo_nsu = greatest(ultimo_nsu, %s)")
        args.append(nsu(ultimo_nsu))
    if max_nsu is not None:
        campos.append("max_nsu = %s")
        args.append(nsu(max_nsu))
    args.append(cnpj)
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute("UPDATE dfe_caixa SET " + ", ".join(campos)
                    + " WHERE cnpj = %s", tuple(args))
        conn.commit()


# ------------------------------------------------------------- documentos

def gravar(cnpj: str, doc: dict) -> str:
    """Grava um documento do lote. Devolve 'novo', 'completado' ou 'repetido'.

    DUAS REGRAS, E AS DUAS JÁ CUSTARIAM CARO SEM TESTE:

    1. **Idempotente por (cnpj, nsu).** Reler um trecho da sequência é normal —
       recomeço depois de perder o controle, varredura manual de um NSU
       específico. Sem a chave, a segunda leitura duplicaria a nota inteira e o
       total de compras do mês dobraria de um jeito PLAUSÍVEL.

    2. **Resumo NUNCA sobrescreve documento completo.** O mesmo NSU chega como
       `resNFe` (chave, emitente, valor) antes da manifestação e como `procNFe`
       (a nota inteira) depois dela. Se uma releitura anterior à manifestação
       chegasse por cima da posterior, a casa perderia o XML — que é
       exatamente o que ela tem obrigação de guardar por cinco anos. O
       `WHERE NOT dfe_documento.completo OR EXCLUDED.completo` é essa regra.
    """
    d = dict(doc)
    d["nsu"] = nsu(d.get("nsu"))
    # ÚLTIMA TRINCHEIRA: documento sem XML não entra. `leitura.descomprimir()`
    # já recusa vazio, e esta linha existe porque a de lá já falhou uma vez —
    # 510 linhas com `xml = ''` em 07/09/2026, com contagem certa e tela cheia.
    # A guarda mais barata contra "ausência com aparência de presença" é a
    # que fica no lugar onde a ausência viraria permanente.
    if not (d.get("xml") or "").strip():
        raise ValueError(
            "documento sem XML (cnpj %s, NSU %s, esquema %r) — gravar isto "
            "criaria uma linha que PARECE guardada e não está"
            % (cnpj, d["nsu"], d.get("esquema")))
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute("SELECT completo FROM dfe_documento WHERE cnpj=%s AND nsu=%s",
                    (cnpj, d["nsu"]))
        antes = cur.fetchone()
        cur.execute(
            """INSERT INTO dfe_documento
                 (cnpj, nsu, esquema, tipo, chave, emitente, emitente_nome,
                  destinatario, valor, emitido_em, situacao, completo, xml,
                  descricao, evento_tipo)
               VALUES (%(cnpj)s, %(nsu)s, %(esquema)s, %(tipo)s, %(chave)s,
                       %(emitente)s, %(emitente_nome)s, %(destinatario)s,
                       %(valor)s, %(emitido_em)s, %(situacao)s, %(completo)s,
                       %(xml)s, %(descricao)s, %(evento_tipo)s)
               ON CONFLICT (cnpj, nsu) DO UPDATE SET
                 esquema = EXCLUDED.esquema, tipo = EXCLUDED.tipo,
                 chave = coalesce(EXCLUDED.chave, dfe_documento.chave),
                 emitente = coalesce(EXCLUDED.emitente, dfe_documento.emitente),
                 emitente_nome = coalesce(EXCLUDED.emitente_nome,
                                          dfe_documento.emitente_nome),
                 destinatario = coalesce(EXCLUDED.destinatario,
                                         dfe_documento.destinatario),
                 valor = coalesce(EXCLUDED.valor, dfe_documento.valor),
                 emitido_em = coalesce(EXCLUDED.emitido_em,
                                       dfe_documento.emitido_em),
                 situacao = coalesce(EXCLUDED.situacao, dfe_documento.situacao),
                 descricao = coalesce(EXCLUDED.descricao, dfe_documento.descricao),
                 evento_tipo = coalesce(EXCLUDED.evento_tipo, dfe_documento.evento_tipo),
                 completo = dfe_documento.completo OR EXCLUDED.completo,
                 xml = EXCLUDED.xml,
                 recebido_em = now()
               WHERE NOT dfe_documento.completo OR EXCLUDED.completo""",
            {"cnpj": cnpj, "nsu": d["nsu"], "esquema": d.get("esquema"),
             "tipo": d.get("tipo") or "desconhecido", "chave": d.get("chave"),
             "emitente": d.get("emitente"),
             "emitente_nome": d.get("emitente_nome"),
             "destinatario": d.get("destinatario"), "valor": d.get("valor"),
             "emitido_em": d.get("emitido_em"), "situacao": d.get("situacao"),
             "completo": bool(d.get("completo")), "xml": d.get("xml") or "",
             "descricao": d.get("descricao"),
             "evento_tipo": d.get("evento_tipo")})
        conn.commit()
    if antes is None:
        return "novo"
    return "completado" if (not antes["completo"] and d.get("completo")) else "repetido"


#: Eventos que MUDAM a validade da nota. O `110111` é o cancelamento; o
#: `110112` é a carta de correção, que altera o documento mas não o derruba.
#:
#: SEM ISTO A TELA MOSTRA COMO VÁLIDA UMA NOTA CANCELADA. O cancelamento chega
#: como documento SEPARADO, com NSU próprio, e a nota original continua no
#: banco exatamente como estava — nada nela muda. Quem olhasse a linha da nota
#: veria "Autorizada" para sempre.
EVENTO_CANCELA = "110111"
EVENTO_CARTA = "110112"


def documentos(cnpj: str | None = None, *, limite: int = 200,
               so_incompletos: bool = False, tipo: str = "",
               de: str = "", ate: str = "", busca: str = "",
               so_completos: bool = False) -> list[dict]:
    """Os documentos, SEM o XML. O XML sai por `xml_de()`, um a um.

    Não é economia de bytes: é que uma lista de 200 notas com o XML dentro são
    ~2 MB numa resposta que a tela usa só para desenhar linhas — e a serialização
    disso é o tipo de custo que vira lentidão sem ninguém saber de onde veio.

    `busca` procura no NOME do emitente e na CHAVE. Chave se cola inteira do
    e-mail ou do romaneio; nome se digita pela metade. As duas entram no mesmo
    campo porque quem procura não separa as duas coisas na cabeça.
    """
    onde, args = [], []
    if cnpj:
        onde.append("cnpj = %s")
        args.append(cnpj)
    if so_incompletos:
        onde.append("NOT completo")
    if so_completos:
        onde.append("completo")
    if tipo:
        onde.append("tipo = %s")
        args.append(tipo)
    if de:
        onde.append("emitido_em >= %s::date")
        args.append(de)
    if ate:
        # `< ate + 1 dia`: com timestamp, `<= '2026-09-30'` para na meia-noite
        # e perde o dia 30 inteiro.
        onde.append("emitido_em < (%s::date + 1)")
        args.append(ate)
    if busca:
        alvo = re.sub(r"[^0-9]", "", busca)
        if len(alvo) == 44:
            # CHAVE COLADA INTEIRA: casa exato, e não por `LIKE`. Chave é
            # identidade, e `%chave%` num índice de 44 dígitos varre a tabela
            # para achar exatamente uma linha.
            onde.append("chave = %s")
            args.append(alvo)
        else:
            onde.append("(emitente_nome ILIKE %s OR chave ILIKE %s "
                        "OR descricao ILIKE %s)")
            args.extend(["%%%s%%" % busca] * 3)
    sql = ("SELECT cnpj, nsu, esquema, tipo, chave, emitente, emitente_nome, "
           "destinatario, valor::float8 AS valor, emitido_em, situacao, "
           "completo, recebido_em, descricao, evento_tipo FROM dfe_documento")
    if onde:
        sql += " WHERE " + " AND ".join(onde)
    sql += " ORDER BY emitido_em DESC NULLS LAST, nsu DESC LIMIT %s"
    args.append(max(1, min(int(limite), 2000)))
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        linhas = [dict(r) for r in cur.fetchall()]
        # OS EVENTOS DE CADA NOTA, numa consulta só. Um `SELECT` por linha
        # seriam 200 idas ao banco para desenhar uma tela.
        chaves = [l["chave"] for l in linhas if l.get("chave")]
        eventos: dict[str, list[dict]] = {}
        if chaves:
            cur.execute(
                "SELECT chave, evento_tipo, descricao, emitido_em "
                "FROM dfe_documento WHERE tipo = 'evento' AND chave = ANY(%s) "
                "ORDER BY emitido_em", (chaves,))
            for e in cur.fetchall():
                eventos.setdefault(e["chave"], []).append(dict(e))
        saida = []
        for x in linhas:
            evs = eventos.get(x.get("chave") or "", [])
            # A SITUAÇÃO EFETIVA vem do EVENTO, e não do campo da nota. O
            # cancelamento chega como documento separado e não muda nada na
            # linha original — sem isto a tela mostra "Autorizada" para sempre
            # numa nota cancelada.
            x["cancelada"] = any(e["evento_tipo"] == EVENTO_CANCELA for e in evs)
            x["tem_carta"] = any(e["evento_tipo"] == EVENTO_CARTA for e in evs)
            x["eventos"] = [{"tipo": e["evento_tipo"], "descricao": e["descricao"],
                             "em": e["emitido_em"].isoformat()
                                   if isinstance(e["emitido_em"], datetime) else None}
                            for e in evs]
            # Serialização converte no LIMITE do módulo: `datetime` estoura no
            # `render()` do JSONResponse, DEPOIS do try/except da rota.
            for c in ("emitido_em", "recebido_em"):
                if isinstance(x.get(c), datetime):
                    x[c] = x[c].isoformat()
            saida.append(x)
        return saida


def xml_de(cnpj: str, nsu_: str) -> str | None:
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute("SELECT xml FROM dfe_documento WHERE cnpj=%s AND nsu=%s",
                    (cnpj, nsu(nsu_)))
        r = cur.fetchone()
        return r["xml"] if r else None


#: Teto do pacote. Nao e limite de banda: e que um ZIP de 50 mil XML leva
#: minutos para montar, e a rota e sincrona -- quem pediu fica olhando a tela
#: parada sem saber se travou. Um mes de operacao cabe folgado aqui.
MAX_PACOTE = 5000


def para_pacote(cnpj: str | None = None, de: str = "", ate: str = "",
                so_completos: bool = True) -> list[dict]:
    """Os documentos de um periodo COM o XML, para virar pacote .zip.

    `so_completos=True` por padrao, e e a decisao que importa: um pacote com
    resumo dentro seria um arquivo que PARECE a nota e nao e. Quem abre um zip
    de XML espera documento fiscal, nao ficha de tres linhas -- e o contador
    que receber isso vai descobrir na hora de escriturar.

    A data de corte e a de EMISSAO, nao a de recebimento: e por competencia que
    a contabilidade pede, e nota emitida dia 30 que chegou dia 2 pertence ao
    mes 30.
    """
    onde, args = ["coalesce(xml,'') <> ''"], []
    if cnpj:
        onde.append("cnpj = %s")
        args.append(cnpj)
    if so_completos:
        onde.append("completo")
    if de:
        onde.append("emitido_em >= %s::date")
        args.append(de)
    if ate:
        # `< ate + 1 dia` e nao `<= ate`: com timestamp, `<= '2026-09-30'`
        # significa ate a MEIA-NOITE do dia 30 e perde o dia inteiro.
        onde.append("emitido_em < (%s::date + 1)")
        args.append(ate)
    sql = ("SELECT cnpj, nsu, tipo, chave, emitido_em, xml FROM dfe_documento "
           "WHERE " + " AND ".join(onde)
           + " ORDER BY emitido_em, nsu LIMIT %s")
    args.append(MAX_PACOTE)
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        return [dict(r) for r in cur.fetchall()]


def resumo(cnpj: str | None = None) -> dict:
    """Os escalares da tela e do Copiloto — sem chave, sem CNPJ de fornecedor.

    `pendentes` é o número que decide alguma coisa: documento que ainda está só
    no resumo é XML que a casa NÃO tem e tem obrigação de guardar.
    """
    # `FILTER (WHERE ...)` aqui É PERMITIDO: este é o banco da CASA
    # (PostgreSQL 16). A proibição do `FILTER` vale para o AVA, que é 9.3 —
    # confundir os dois bancos custa caro nos dois sentidos.
    onde, args = ("WHERE cnpj = %s", (cnpj,)) if cnpj else ("", ())
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*)::int AS total, "
            "  count(*) FILTER (WHERE NOT completo)::int AS pendentes, "
            "  count(*) FILTER (WHERE tipo = 'nfe')::int AS nfe, "
            "  count(*) FILTER (WHERE tipo = 'cte')::int AS cte, "
            "  count(*) FILTER (WHERE tipo = 'evento')::int AS eventos, "
            "  max(recebido_em) AS ultimo_recebido "
            "FROM dfe_documento " + onde, args)
        d = dict(cur.fetchone() or {})
    if isinstance(d.get("ultimo_recebido"), datetime):
        d["ultimo_recebido"] = d["ultimo_recebido"].isoformat()
    return d
