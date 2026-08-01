"""Orquestra a importação de extrato e monta o painel de validação.

Importação: parse -> grava (dedup) -> devolve resultado. Conta cujo vínculo com
o ERP ainda não existe grava os lançamentos e volta pedindo o mapeamento; não
perder o upload evita o usuário subir o arquivo duas vezes.

Painel: para cada conta mapeada, lê `contacorrente_saldo` (lado ERP) e cruza
com o extrato local pela função pura de `comparacao`.
"""
from __future__ import annotations

from datetime import date, datetime

from api import db
from api.extrato import armazenamento as arm
from api.extrato import comparacao as cmp
from api.extrato.parser_csv import parse_csv, preview_csv
from api.extrato.parser_ofx import parse_ofx

# Lado ERP da comparação. Uma linha por dia da conta; `valorsaldo` é a posição
# de fechamento do dia. Sem "-" especial na string (o banco é LATIN-1).
ERP_SALDO_SQL = """
SELECT dtmovimento::date AS dt,
       coalesce(valorcredito,0)::float8 AS credito,
       coalesce(valordebito,0)::float8  AS debito,
       coalesce(valorsaldo,0)::float8   AS saldo
FROM contacorrente_saldo
WHERE banco = %(banco)s AND agencia = %(agencia)s AND conta = %(conta)s
  AND dtmovimento BETWEEN %(dt_de)s AND %(dt_ate)s
ORDER BY dtmovimento
"""

# Contas que o ERP movimenta, para o select de mapeamento. Só as com movimento
# recente: a lista completa traz contas encerradas anos atrás.
ERP_CONTAS_SQL = """
SELECT banco, agencia, conta,
       max(dtmovimento)::date AS ultimo_movimento,
       count(*)::int AS dias
FROM contacorrente_saldo
WHERE dtmovimento >= current_date - 400
GROUP BY 1,2,3
ORDER BY max(dtmovimento) DESC, banco
"""


def _formato(nome: str) -> str:
    return "ofx" if nome.lower().endswith((".ofx", ".qfx")) else "csv"


def _erp_dias(conta: dict, dt_de: str, dt_ate: str) -> list[dict]:
    if conta.get("erp_banco") is None:
        return []
    rows = db.query(ERP_SALDO_SQL, {
        "banco": conta["erp_banco"], "agencia": conta["erp_agencia"],
        "conta": conta["erp_conta"], "dt_de": dt_de, "dt_ate": dt_ate})
    return [{"dt": r["dt"].isoformat() if hasattr(r["dt"], "isoformat") else str(r["dt"]),
             "credito": r["credito"], "debito": r["debito"], "saldo": r["saldo"]}
            for r in rows]


def contas_erp() -> list[dict]:
    rows = db.query(ERP_CONTAS_SQL)
    out = []
    for r in rows:
        ultimo = r["ultimo_movimento"]
        out.append({
            "banco": r["banco"], "agencia": r["agencia"], "conta": r["conta"],
            "ultimo_movimento": ultimo.isoformat() if hasattr(ultimo, "isoformat") else str(ultimo),
            "dias": r["dias"],
            "rotulo": f"{r['banco']} / ag {r['agencia']} / cc {r['conta']}",
        })
    return out


def importar(bruto: bytes, nome: str, path=arm.DB_PATH) -> dict:
    arm.init_db(path)
    formato = _formato(nome)

    if formato == "ofx":
        # parse_ofx devolve UM extrato por conta do arquivo (export consolidado
        # traz varias). Grava todas; o resultado reporta a primeira que ainda
        # precisa de mapeamento, para a tela pedir o vinculo.
        extratos = parse_ofx(bruto)
        resultados = []
        for d in extratos:
            rotulo = f"{d['banco'] or '?'} / cc {d['conta'] or '?'}"
            conta_id = arm.obter_ou_criar_conta(path, d["ident"], rotulo)
            conta = arm.conta_por_ident(path, d["ident"])
            res = arm.gravar_lancamentos(path, conta_id, d["itens"], nome, "ofx",
                                         d["ignoradas"])
            if d["saldo"]:
                arm.gravar_saldo_extrato(path, conta_id, d["saldo"]["dt"],
                                         d["saldo"]["saldo"])
            datas = sorted(i["dt"] for i in d["itens"]) or [None]
            resultados.append({"conta_id": conta_id, "conta": conta,
                               "novas": res["novas"], "duplicadas": res["duplicadas"],
                               "ignoradas": d["ignoradas"],
                               "dt_de": datas[0], "dt_ate": datas[-1]})
        # agrega os totais do arquivo; contas = uma linha por conta encontrada
        total = {"novas": sum(r["novas"] for r in resultados),
                 "duplicadas": sum(r["duplicadas"] for r in resultados),
                 "ignoradas": sum(r["ignoradas"] for r in resultados),
                 "contas": resultados}
        datas_todas = sorted(d for r in resultados for d in (r["dt_de"], r["dt_ate"]) if d)
        primeira = resultados[0]
        base = {"conta_id": primeira["conta_id"], "conta": primeira["conta"],
                "dt_de": (datas_todas[0] if datas_todas else None),
                "dt_ate": (datas_todas[-1] if datas_todas else None), **total}
        sem_mapa = [r for r in resultados if r["conta"].get("erp_banco") is None]
        if sem_mapa:
            return {"ok": False, "precisa": "mapa_erp", **base,
                    "conta_id": sem_mapa[0]["conta_id"], "conta": sem_mapa[0]["conta"]}
        return {"ok": True, **base}

    # CSV: a conta não vem no arquivo, então o ident sai do nome do arquivo
    ident = "csv:" + nome.rsplit(".", 1)[0].strip().lower()
    conta_id = arm.obter_ou_criar_conta(path, ident, nome.rsplit(".", 1)[0])
    conta = arm.conta_por_ident(path, ident)
    if not conta.get("mapa_csv"):
        return {"ok": False, "precisa": "mapa_csv", "conta_id": conta_id, "conta": conta,
                "preview": preview_csv(bruto), "novas": 0, "duplicadas": 0, "ignoradas": 0}
    d = parse_csv(bruto, conta["mapa_csv"])
    res = arm.gravar_lancamentos(path, conta_id, d["itens"], nome, "csv", d["ignoradas"])
    datas = sorted(i["dt"] for i in d["itens"]) or [None]
    base = {"conta_id": conta_id, "conta": conta, "novas": res["novas"],
            "duplicadas": res["duplicadas"], "ignoradas": d["ignoradas"],
            "dt_de": datas[0], "dt_ate": datas[-1]}
    if conta.get("erp_banco") is None:
        return {"ok": False, "precisa": "mapa_erp", **base}
    return {"ok": True, **base}


def painel(dt_de: str, dt_ate: str, conta_id: int | None = None, path=arm.DB_PATH) -> dict:
    arm.init_db(path)
    hoje = date.today().isoformat()
    contas = arm.listar_contas(path)
    imps = arm.listar_importacoes(path)
    ult_por_conta: dict[int, str] = {}
    for i in imps:
        cid = i["conta_id"]
        if i.get("dt_ate") and (cid not in ult_por_conta or i["dt_ate"] > ult_por_conta[cid]):
            ult_por_conta[cid] = i["dt_ate"]

    resumo, dias_sel = [], []
    tot_div = tot_val = 0
    pior = None
    for c in contas:
        lancs = arm.lancamentos(path, c["id"], dt_de, dt_ate)
        saldos = arm.saldos_extrato(path, c["id"])
        dias = cmp.comparar(lancs, saldos, _erp_dias(c, dt_de, dt_ate))
        f = cmp.farol(dias, ult_por_conta.get(c["id"]), hoje,
                      mapeada=c.get("erp_banco") is not None)
        validos = [d for d in dias if d["estado"] in ("OK", "DIVERGE")]
        divergentes = [d for d in dias if d["estado"] == "DIVERGE"]
        tot_val += len(validos)
        tot_div += len(divergentes)
        for d in divergentes:
            delta = abs(d.get("d_saldo") or d.get("d_credito") or d.get("d_debito") or 0)
            if pior is None or delta > pior["delta"]:
                pior = {"delta": delta, "conta": c["rotulo"], "dt": d["dt"]}
        resumo.append({
            "conta_id": c["id"], "rotulo": c["rotulo"], "ident": c["ident"],
            "mapeada": c.get("erp_banco") is not None,
            "erp": (f"{c['erp_banco']} / ag {c['erp_agencia']} / cc {c['erp_conta']}"
                    if c.get("erp_banco") is not None else None),
            "formato_csv": bool(c.get("mapa_csv")),
            "farol": f, "dias_validados": len(validos), "dias_divergentes": len(divergentes),
            "ultimo_extrato": ult_por_conta.get(c["id"]),
        })
        if conta_id is not None and c["id"] == conta_id:
            dias_sel = dias
    # sem conta escolhida, a tabela dia a dia abre na primeira conta com dado
    if conta_id is None:
        for c in contas:
            lancs = arm.lancamentos(path, c["id"], dt_de, dt_ate)
            if lancs:
                dias_sel = cmp.comparar(lancs, arm.saldos_extrato(path, c["id"]),
                                        _erp_dias(c, dt_de, dt_ate))
                conta_id = c["id"]
                break

    return {
        "kpis": {
            "contas": len(contas),
            "contas_sem_mapa": sum(1 for r in resumo if not r["mapeada"]),
            "dias_validados": tot_val,
            "dias_divergentes": tot_div,
            "maior_diferenca": (pior or {}).get("delta"),
            "maior_diferenca_conta": (pior or {}).get("conta"),
            "maior_diferenca_dt": (pior or {}).get("dt"),
            "ultimo_upload": (imps[0]["quando"] if imps else None),
        },
        "conta_selecionada": conta_id,
        "contas": resumo,
        "dias": dias_sel,
        "importacoes": imps,
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": "extrato importado (OFX/CSV) x contacorrente_saldo do ERP AVA",
    }
