"""Confere o documento da Whirlpool contra o CT-e que a Sulista emitiu.

O CAMINHO NO ERP (decifrado em 16/09/2026, não documentado em lugar nenhum):

- A coleta (`public.coleta`, chave de 7 colunas) é o pedido da Whirlpool.
  Entram as coletas em que ela é remetente, pagadora ou tomadora — pela RAIZ
  do CNPJ, que cobre as quatro plantas (Joinville, Rio Claro, São Paulo e as
  duas razões de Manaus).
- O anexo mora em `arquivo.arquivobinario` com `tipodocumento = 27` e a
  chave da coleta (`numerosequencia` é o número da coleta). O arquivo NÃO
  aponta para a ocorrência: a 262 (PRÉ CÁLCULO) é lançada no mesmo minuto,
  e é ela que diz que o anexo chegou.
- O CT-e sai da coleta por `conhecimento_composicao` (`tipodocumento = 27` e
  a chave da coleta nas colunas `*documento`). **Uma coleta gera UM CT-e POR
  FORNECEDOR**, como as páginas do Pré-Cálculo — a coleta 19970 tem dois.
- Os componentes do frete estão em `conhecimento_valorfrete`: 1 frete peso,
  11 pedágio, 200 taxa de coleta (às vezes em DUAS linhas), 8 taxa de
  entrega, 100 ICMS.

O ESTADO DE CADA COLETA É CALCULADO NA LEITURA, nunca gravado: um CT-e
cancelado e reemitido amanhã muda a resposta sem ninguém precisar lembrar.
Só a LEITURA DO PDF fica em disco (`data/validacao_whirlpool/`), porque o
arquivo não muda e reler 300 PDFs a cada abertura de tela é custo sem motivo.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, timedelta
from pathlib import Path

from api import db
from api.queries import VELHA_ATE, cached
from api.validacao_whirlpool import leitor

log = logging.getLogger(__name__)

RAIZES = ["59105999", "63699839"]   # Whirlpool S.A. e Whirlpool Eletrodomésticos AM
OCORRENCIA_PRECALCULO = 262
TIPODOC_COLETA = 27

# Tolerâncias. Valor em centavos porque os dois lados arredondam componente a
# componente; peso relativo porque o documento traz o peso da NOTA e o CT-e
# pode ter o bruto.
TOL_VALOR = 0.05
# Até aqui é ARREDONDAMENTO, não divergência — medido em 16/09/2026 nos 90
# dias: das diferenças de total com o CT-e na mesma ordem de grandeza, 63 de 97
# ficam abaixo de R$ 0,50 e são sistemáticas (o frete de R$ 4.815,00 do CT-e
# contra R$ 4.814,72 do arquivo, repetido em coletas diferentes). A tela
# mostra em amarelo, separado da divergência — o limite é decisão de quem
# opera e está declarado na resposta.
TOL_ARREDONDAMENTO = 1.00
TOL_PESO_REL = 0.01
TOL_ICMS_PCT = 0.05   # pontos percentuais: a alíquota derivada carrega o arredondamento do centavo

DIR_CACHE = Path(__file__).resolve().parents[2] / "data" / "validacao_whirlpool"
_TRAVA_CACHE = threading.Lock()

ESTADOS = {
    "ok": "Conferido",
    "arredondamento": "Diferença de arredondamento",
    "divergente": "Divergente",
    "sem_valor": "Arquivo sem valor",
    "nao_lido": "Arquivo não lido",
    "sem_arquivo": "Sem arquivo",
    "sem_cte": "Aguardando CT-e",
}

_COLETAS = """
SELECT c.grupo, c.empresa, c.filial, c.unidade, c.diferenciadornumero, c.serie, c.numero,
       c.dtemissao, c.remetente, c.cnpjcpfcodigopagadorfrete AS pagador,
       c.cnpjcpfcodigotomadorservico AS tomador,
       -- a PAGADORA diz qual planta: o remetente vem vazio em boa parte das
       -- coletas (o fornecedor só aparece no CT-e)
       coalesce(nullif(trim(cp.nomefantasia), ''), cp.razaosocial) AS pagador_nome
  FROM coleta c
  LEFT JOIN cadastro cp ON cp.codigo = c.cnpjcpfcodigopagadorfrete
 WHERE c.dtemissao >= %(de)s AND c.dtemissao < %(ate_mais_1)s
   AND c.dtcancelamento IS NULL
   AND (left(c.remetente, 8) = ANY(%(raizes)s)
        OR left(c.cnpjcpfcodigopagadorfrete, 8) = ANY(%(raizes)s)
        OR left(c.cnpjcpfcodigotomadorservico, 8) = ANY(%(raizes)s))
"""

COLETAS_SQL = """
SELECT col.*,
       (SELECT min(o.dtocorrencia) FROM coleta_ocorrencia o
         WHERE o.grupo = col.grupo AND o.empresa = col.empresa AND o.filial = col.filial
           AND o.unidade = col.unidade AND o.diferenciadornumero = col.diferenciadornumero
           AND o.serie = col.serie AND o.numero = col.numero
           AND o.ocorrencia = %(ocorrencia)s) AS precalculo_em
  FROM (""" + _COLETAS + """) col
 ORDER BY col.dtemissao DESC, col.filial, col.numero
"""

ANEXOS_SQL = """
SELECT col.filial, col.serie, col.numero, b.id, b.nomearquivo, lower(b.extensao) AS extensao,
       b.tamanho, b.dtinc
  FROM (""" + _COLETAS + """) col
  JOIN arquivo.arquivobinario b
    ON b.tipodocumento = %(tipodoc)s AND b.grupo = col.grupo AND b.empresa = col.empresa
   AND b.filial = col.filial AND b.unidade = col.unidade
   AND b.diferenciadornumero = col.diferenciadornumero AND b.serie = col.serie
   AND b.numerosequencia = col.numero
"""

# Os componentes por CASE WHEN (o ERP é 9.3: sem FILTER). O CT-e entra por
# DISTINCT na composição: a mesma coleta pode aparecer em mais de uma linha
# da composição do mesmo CT-e, e o join direto dobraria o valor.
CTES_SQL = """
SELECT DISTINCT ON (col.filial, col.serie, col.numero, k.filial, k.serie, k.numero)
       col.filial AS col_filial, col.serie AS col_serie, col.numero AS col_numero,
       k.filial, k.serie, k.numero, k.dtemissao, k.dtcancelamento, k.situacaocte,
       k.chaveacessocte AS chave, k.remetente, k.destinatario,
       k.cnpjcpfcodigotomadorservico AS tomador, k.cnpjcpfcodigopagadorfrete AS pagador,
       coalesce(nullif(trim(cre.nomefantasia), ''), cre.razaosocial) AS remetente_nome,
       coalesce(nullif(trim(cde.nomefantasia), ''), cde.razaosocial) AS destinatario_nome,
       k.peso, k.m3, k.valortotalprestacao AS total, k.valorbasecalculoicms AS base_icms,
       k.percaliquotaicms AS icms_pct, k.valoricms AS icms,
       f.cnpj AS filial_cnpj,
       v.frete, v.pedagio, v.taxa_coleta, v.icms_comp, v.outros
  FROM (""" + _COLETAS + """) col
  JOIN conhecimento_composicao cc
    ON cc.tipodocumento = %(tipodoc)s AND cc.grupo = col.grupo AND cc.empresa = col.empresa
   AND cc.filialdocumento = col.filial AND cc.unidadedocumento = col.unidade
   AND cc.diferenciadornumerodocumento = col.diferenciadornumero
   AND cc.seriedocumento = col.serie AND cc.numerodocumento = col.numero
  JOIN conhecimento k
    ON k.grupo = cc.grupo AND k.empresa = cc.empresa AND k.filial = cc.filial
   AND k.unidade = cc.unidade AND k.diferenciadornumero = cc.diferenciadornumero
   AND k.serie = cc.serie AND k.numero = cc.numero
  LEFT JOIN filial f ON f.grupo = k.grupo AND f.empresa = k.empresa AND f.codigo = k.filial
  LEFT JOIN cadastro cre ON cre.codigo = k.remetente
  LEFT JOIN cadastro cde ON cde.codigo = k.destinatario
  LEFT JOIN LATERAL (
        SELECT sum(CASE WHEN vf.tipocalculofrete = 1 THEN vf.valorliquido ELSE 0 END) AS frete,
               sum(CASE WHEN vf.tipocalculofrete = 11 THEN vf.valorliquido ELSE 0 END) AS pedagio,
               sum(CASE WHEN vf.tipocalculofrete IN (200, 8) THEN vf.valorliquido ELSE 0 END) AS taxa_coleta,
               sum(CASE WHEN vf.tipocalculofrete = 100 THEN vf.valorliquido ELSE 0 END) AS icms_comp,
               sum(CASE WHEN vf.tipocalculofrete NOT IN (1, 11, 200, 8, 100)
                        THEN vf.valorliquido ELSE 0 END) AS outros
          FROM conhecimento_valorfrete vf
         WHERE vf.grupo = k.grupo AND vf.empresa = k.empresa AND vf.filial = k.filial
           AND vf.unidade = k.unidade AND vf.diferenciadornumero = k.diferenciadornumero
           AND vf.serie = k.serie AND vf.numero = k.numero) v ON true
 ORDER BY col.filial, col.serie, col.numero, k.filial, k.serie, k.numero
"""

BYTES_SQL = """
SELECT id, lower(extensao) AS extensao, tamanho, conteudoarquivo
  FROM arquivo.arquivobinario WHERE id = ANY(%s)
"""


def _params(de: date, ate: date) -> dict:
    return {"de": de, "ate_mais_1": ate + timedelta(days=1), "raizes": RAIZES,
            "ocorrencia": OCORRENCIA_PRECALCULO, "tipodoc": TIPODOC_COLETA}


def _f(v) -> float | None:
    return None if v is None else float(v)


def _iso(v) -> str | None:
    return v.isoformat(sep=" ", timespec="minutes") if hasattr(v, "isoformat") else v


# ----------------------------------------------------------------------------
# Cache da LEITURA do PDF (o arquivo do ERP não muda depois de anexado)
# ----------------------------------------------------------------------------
def _cache_ler(anexo_id: int, tamanho) -> dict | None:
    p = DIR_CACHE / f"{anexo_id}.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if doc.get("versao") != leitor.VERSAO or doc.get("_tamanho") != tamanho:
        return None
    return doc


def _cache_gravar(anexo_id: int, tamanho, doc: dict) -> None:
    try:
        DIR_CACHE.mkdir(parents=True, exist_ok=True)
        tmp = DIR_CACHE / f"{anexo_id}.json.tmp"
        tmp.write_text(json.dumps({**doc, "_tamanho": tamanho}, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(DIR_CACHE / f"{anexo_id}.json")
    except OSError as exc:      # disco cheio não derruba a tela: só relê da próxima vez
        log.warning("validacao_whirlpool: cache nao gravado (%s)", type(exc).__name__)


def ler_anexos(anexos: list[dict], baixar: bool = True) -> dict[int, dict]:
    """id do anexo → documento lido. Baixa do ERP só o que não está no cache.

    `baixar=False` é o modo do Copiloto: só o que já foi lido em disco. O que
    falta volta como `ainda_nao_lido` — e é CONTADO, não confundido com
    arquivo em formato desconhecido."""
    lidos: dict[int, dict] = {}
    faltam = []
    for a in anexos:
        doc = _cache_ler(a["id"], a["tamanho"])
        if doc is None:
            faltam.append(a["id"])
        else:
            lidos[a["id"]] = doc
    if faltam and not baixar:
        for i in faltam:
            lidos[i] = {"formato": "desconhecido", "motivo": "ainda não lido",
                        "ainda_nao_lido": True}
        return lidos
    if faltam:
        with _TRAVA_CACHE:
            for i in range(0, len(faltam), 20):     # lotes: bytea de 30 KB × 300 de uma vez pesa
                for r in db.query(BYTES_SQL, (faltam[i:i + 20],)):
                    doc = leitor.ler(bytes(r["conteudoarquivo"] or b""), r["extensao"])
                    _cache_gravar(r["id"], r["tamanho"], doc)
                    lidos[r["id"]] = doc
    return lidos


# ----------------------------------------------------------------------------
# A conferência
# ----------------------------------------------------------------------------
def _item(grupo: str, rotulo: str, arquivo, cte, ok: bool, dif=None,
          arredondamento: bool = False) -> dict:
    """`nivel`: ok | arredondamento | divergente. `ok` fica True só no ok."""
    nivel = "ok" if ok else ("arredondamento" if arredondamento else "divergente")
    return {"grupo": grupo, "rotulo": rotulo, "arquivo": arquivo, "cte": cte,
            "ok": ok, "nivel": nivel, "dif": dif}


def _valor(grupo: str, rotulo: str, arq, cte, tol: float = TOL_VALOR) -> dict:
    a, c = (arq or 0.0), (_f(cte) or 0.0)
    d = round(c - a, 2)
    arred = tol == TOL_VALOR and abs(d) <= TOL_ARREDONDAMENTO
    return _item(grupo, rotulo, arq, _f(cte), abs(d) <= tol, d, arredondamento=arred)


def _cte_publico(k: dict) -> dict:
    return {"filial": k["filial"], "serie": k["serie"], "numero": k["numero"],
            "emissao": _iso(k["dtemissao"]), "chave": k["chave"],
            "cancelado": bool(k["dtcancelamento"]) or k["situacaocte"] not in (3, None),
            "remetente": k["remetente"], "remetente_nome": k["remetente_nome"],
            "destinatario": k["destinatario"], "destinatario_nome": k["destinatario_nome"],
            "total": _f(k["total"]), "peso": _f(k["peso"])}


def _par(f: dict, ctes: list[dict]) -> dict | None:
    """O CT-e da página: o fornecedor é remetente OU destinatário (troca de
    papel conforme o sentido); havendo mais de um, o de total mais próximo."""
    cand = [k for k in ctes if f["cnpj"] in (k["remetente"], k["destinatario"])]
    if not cand:
        return None
    alvo = f.get("total_pagar") or 0
    return min(cand, key=lambda k: abs((_f(k["total"]) or 0) - alvo))


def conferir_precalculo(doc: dict, ctes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Devolve (pares, itens). Cada página vira um par com o seu CT-e."""
    itens: list[dict] = []
    pares: list[dict] = []
    usados: set = set()
    sem_valor = doc.get("sem_valor")
    for f in doc.get("fornecedores") or []:
        k = _par(f, [c for c in ctes if id(c) not in usados])
        par = {"fornecedor": f["fornecedor"], "cnpj": f["cnpj"], "cte": None, "itens": []}
        if k is None:
            itens.append(_item("ctes", f"CT-e de {f['fornecedor']}", "página no arquivo",
                               None, False))
            pares.append(par)
            continue
        usados.add(id(k))
        par["cte"] = _cte_publico(k)
        pi = par["itens"]
        if not sem_valor:
            pi.append(_valor("valores", "Total a pagar", f.get("total_pagar"), k["total"]))
            pi.append(_valor("valores", "Frete", f.get("frete"), k["frete"]))
            pi.append(_valor("valores", "Pedágio", f.get("pedagio"), k["pedagio"]))
            pi.append(_valor("valores", "Taxa de coleta/entrega", f.get("taxa_coleta"),
                             k["taxa_coleta"]))
            # o ICMS do CT-e mora no COMPONENTE 100: `valoricms` e
            # `percaliquotaicms` do cabeçalho vêm zerados nestes CT-es. A
            # alíquota se deriva — ICMS por dentro, sobre o total da prestação
            pi.append(_valor("valores", "ICMS", f.get("icms"), k["icms_comp"]))
            tot, icms = _f(k["total"]) or 0, _f(k["icms_comp"]) or 0
            pct = round(icms / tot * 100, 2) if tot else None
            pi.append(_valor("valores", "% ICMS", doc.get("icms_pct"), pct, tol=TOL_ICMS_PCT))
        pa, pc = f.get("peso"), _f(k["peso"])
        tol = max(1.0, (pa or 0) * TOL_PESO_REL)
        pi.append(_item("peso", "Peso (kg)", pa, pc,
                        pa is not None and pc is not None and abs(pc - pa) <= tol,
                        None if pa is None or pc is None else round(pc - pa, 3)))
        contr = (f.get("contratante") or {}).get("cnpj")
        pi.append(_item("partes", "Contratante = tomador", contr, k["tomador"],
                        bool(contr) and contr in (k["tomador"], k["pagador"])))
        tr = doc.get("transportadora_cnpj")
        pi.append(_item("partes", "Filial da Sulista = emissora", tr, k["filial_cnpj"],
                        bool(tr) and tr == (k["filial_cnpj"] or "")))
        itens.extend(pi)
        pares.append(par)
    for k in ctes:
        if id(k) not in usados:
            itens.append(_item("ctes", f"CT-e {k['numero']} sem página no arquivo", None,
                               k["numero"], False))
            pares.append({"fornecedor": None, "cnpj": None, "cte": _cte_publico(k),
                          "itens": []})
    return pares, itens


def conferir_ordem(doc: dict, ctes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Sem valor e sem CNPJ: o que a Ordem de Coleta permite conferir é o peso
    total da coleta contra a soma dos CT-es."""
    peso = doc.get("peso_coleta") or doc.get("peso_entrega")
    soma = round(sum(_f(k["peso"]) or 0 for k in ctes), 3)
    tol = max(1.0, (peso or 0) * TOL_PESO_REL)
    itens = [_item("peso", "Peso total (kg)", peso, soma,
                   peso is not None and abs(soma - peso) <= tol,
                   None if peso is None else round(soma - peso, 3))]
    pares = [{"fornecedor": None, "cnpj": None, "cte": _cte_publico(k), "itens": []}
             for k in ctes]
    return pares, itens


def conferir_coleta(coleta: dict, anexos: list[dict], lidos: dict[int, dict],
                    ctes: list[dict]) -> dict:
    ativos = [k for k in ctes if not k["dtcancelamento"] and k["situacaocte"] in (3, None)]
    cancelados = [k for k in ctes if k not in ativos]
    docs = sorted(((a, lidos.get(a["id"]) or {"formato": "desconhecido",
                                                 "motivo": "não lido"}) for a in anexos),
                  key=lambda x: str(x[0]["dtinc"]), reverse=True)
    # o documento que responde: o Pré-Cálculo mais recente; na falta, a Ordem
    escolha = (next((x for x in docs if x[1]["formato"] == "precalculo"), None)
               or next((x for x in docs if x[1]["formato"] == "ordem_coleta"), None))
    out = {
        "filial": coleta["filial"], "serie": coleta["serie"], "numero": coleta["numero"],
        "emissao": _iso(coleta["dtemissao"]), "precalculo_em": _iso(coleta["precalculo_em"]),
        "pagador_nome": coleta["pagador_nome"],
        "anexos": [{"id": a["id"], "nome": a["nomearquivo"], "extensao": a["extensao"],
                    "formato": d["formato"], "motivo": d.get("motivo"),
                    "incluido": _iso(a["dtinc"])} for a, d in docs],
        "ctes": len(ativos), "ctes_cancelados": len(cancelados),
        "documento": None, "pares": [], "itens": [], "falhas": {}, "arredondamentos": 0,
    }
    if escolha:
        a, d = escolha
        out["documento"] = {k: v for k, v in d.items()
                            if k not in ("fornecedores", "paradas", "versao", "_tamanho")}
        out["documento"]["anexo_id"] = a["id"]
        out["documento"]["paginas"] = len(d.get("fornecedores") or d.get("paradas") or [])
    if not anexos:
        out["estado"] = "sem_arquivo"
    elif not escolha:
        out["estado"] = "nao_lido"
    elif not ativos:
        out["estado"] = "sem_cte"
    else:
        a, d = escolha
        if d["formato"] == "precalculo":
            out["pares"], out["itens"] = conferir_precalculo(d, ativos)
        else:
            out["pares"], out["itens"] = conferir_ordem(d, ativos)
        falhas: dict[str, int] = {}
        arred = 0
        for it in out["itens"]:
            if it["nivel"] == "divergente":
                falhas[it["grupo"]] = falhas.get(it["grupo"], 0) + 1
            elif it["nivel"] == "arredondamento":
                arred += 1
        out["falhas"] = falhas
        out["arredondamentos"] = arred
        if falhas:
            out["estado"] = "divergente"
        elif arred:
            out["estado"] = "arredondamento"
        elif d["formato"] == "precalculo" and d.get("sem_valor"):
            out["estado"] = "sem_valor"
        else:
            out["estado"] = "ok"
    out["estado_rotulo"] = ESTADOS[out["estado"]]
    return out


def _chave(r: dict, pre: str = "") -> tuple:
    return (r[pre + "filial"], r[pre + "serie"], r[pre + "numero"])


@cached(ttl=300, velha_ate=VELHA_ATE)
def validar(de: str, ate: str) -> dict:
    """As coletas da Whirlpool emitidas na janela, cada uma com o seu estado."""
    return _validar(de, ate, baixar=True)


def resumo_copiloto(dias: int = 30) -> dict:
    """SÓ CONTAGENS para o snapshot do Copiloto (sem coleta, fornecedor ou
    valor). Leitura barata: não baixa PDF do ERP — o que ainda não foi lido
    por quem abriu a tela entra em `anexos_ainda_nao_lidos`."""
    hoje = date.today()
    r = _validar((hoje - timedelta(days=dias)).isoformat(), hoje.isoformat(), baixar=False)
    return {"periodo": r["periodo"], "coletas": len(r["coletas"]),
            "contagem": r["contagem"], "divergencias_por_grupo": r["divergencias_por_grupo"],
            "anexos_ainda_nao_lidos": r["anexos_ainda_nao_lidos"], "regras": r["regras"]}


def _validar(de: str, ate: str, baixar: bool) -> dict:
    d0, d1 = date.fromisoformat(de), date.fromisoformat(ate)
    prm = _params(d0, d1)
    coletas = db.query(COLETAS_SQL, prm)
    anexos = db.query(ANEXOS_SQL, prm)
    ctes = db.query(CTES_SQL, prm)
    lidos = ler_anexos(anexos, baixar=baixar)

    por_col_anexos: dict[tuple, list] = {}
    for a in anexos:
        por_col_anexos.setdefault(_chave(a), []).append(a)
    por_col_ctes: dict[tuple, list] = {}
    for k in ctes:
        por_col_ctes.setdefault(_chave(k, "col_"), []).append(k)

    linhas = [conferir_coleta(c, por_col_anexos.get(_chave(c), []), lidos,
                              por_col_ctes.get(_chave(c), [])) for c in coletas]
    contagem = {e: 0 for e in ESTADOS}
    for l in linhas:
        contagem[l["estado"]] += 1
    grupos: dict[str, int] = {}
    for l in linhas:
        for g, n in l["falhas"].items():
            grupos[g] = grupos.get(g, 0) + 1
    return {
        "periodo": {"de": de, "ate": ate},
        "coletas": linhas,
        "contagem": contagem,
        "divergencias_por_grupo": grupos,
        "anexos_ainda_nao_lidos": sum(1 for d in lidos.values() if d.get("ainda_nao_lido")),
        "estados": ESTADOS,
        "regras": {"tol_valor": TOL_VALOR, "tol_arredondamento": TOL_ARREDONDAMENTO, "tol_peso_rel": TOL_PESO_REL,
                   "tol_icms_pct": TOL_ICMS_PCT, "ocorrencia": OCORRENCIA_PRECALCULO},
    }


def baixar_anexo(anexo_id: int) -> dict | None:
    """O PDF original, para abrir na tela — só se o anexo for de coleta da
    Whirlpool (senão a rota viraria um leitor de qualquer arquivo do ERP)."""
    sql = """
SELECT b.nomearquivo, lower(b.extensao) AS extensao, b.conteudoarquivo
  FROM arquivo.arquivobinario b
  JOIN coleta c ON c.grupo = b.grupo AND c.empresa = b.empresa AND c.filial = b.filial
   AND c.unidade = b.unidade AND c.diferenciadornumero = b.diferenciadornumero
   AND c.serie = b.serie AND c.numero = b.numerosequencia
 WHERE b.id = %(id)s AND b.tipodocumento = %(tipodoc)s
   AND (left(c.remetente, 8) = ANY(%(raizes)s)
        OR left(c.cnpjcpfcodigopagadorfrete, 8) = ANY(%(raizes)s)
        OR left(c.cnpjcpfcodigotomadorservico, 8) = ANY(%(raizes)s))
"""
    r = db.query(sql, {"id": anexo_id, "tipodoc": TIPODOC_COLETA, "raizes": RAIZES})
    if not r:
        return None
    return {"nome": r[0]["nomearquivo"], "extensao": r[0]["extensao"],
            "conteudo": bytes(r[0]["conteudoarquivo"] or b"")}
