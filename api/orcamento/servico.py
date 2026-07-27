"""Orquestração do módulo orçamentário: deriva, grava e compara.

A parte pura (montar_comparativo) fica separada do acesso a dados para poder ser
testada sem banco.
"""
from __future__ import annotations

from datetime import date

from api import db
from api.orcamento import armazenamento as arm
from api.orcamento.derivacao import derivar
from api.orcamento.rollup import contas_sem_linha, mapa_conta_linha
from api.orcamento.sql import (AGRUP_CONTA_SQL, HIST_CONTA_SQL, REAL_CONTA_SQL,
                               meses_fechados)
from api.queries import DRE_MODELO, ler_ajustes


def montar_comparativo(linhas_orc: list[dict], realizado: dict,
                       mapa_linha: dict, ate_mes: int) -> dict:
    """Agrega orçado e realizado por linha da DRE até `ate_mes` (inclusive).

    linhas_orc: saída de armazenamento.ler_linhas()
    realizado:  {(conta, mes): valor}
    mapa_linha: {conta: rótulo da linha DRE | None}
    """
    por_linha: dict[str, dict] = {}
    por_conta: dict[str, dict] = {}
    mensal: dict[int, dict] = {m: {"mes": m, "orcado": 0.0, "realizado": None,
                                   "fechado": m <= ate_mes} for m in range(1, 13)}
    sem_linha: set[str] = set()

    for l in linhas_orc:
        conta, mes = l["conta"], l["mes"]
        orc = l["valor_efetivo"] or 0.0
        mensal[mes]["orcado"] += orc
        if mes <= ate_mes:
            real = realizado.get((conta, mes))
            if real is not None:
                if mensal[mes]["realizado"] is None:
                    mensal[mes]["realizado"] = 0.0
                mensal[mes]["realizado"] += real

        rot = mapa_linha.get(conta)
        if rot is None:
            sem_linha.add(conta)
            continue
        if mes > ate_mes:
            continue

        alvo = por_linha.setdefault(rot, {"linha": rot, "orcado": 0.0, "realizado": 0.0})
        alvo["orcado"] += orc
        alvo["realizado"] += realizado.get((conta, mes), 0.0)

        c = por_conta.setdefault(conta, {"conta": conta, "linha": rot,
                                         "orcado": 0.0, "realizado": 0.0,
                                         "origem": l["origem"]})
        c["orcado"] += orc
        c["realizado"] += realizado.get((conta, mes), 0.0)

    def _fecha(d: dict) -> dict:
        d["desvio"] = d["realizado"] - d["orcado"]
        base = abs(d["orcado"])
        d["desvio_pct"] = (100.0 * d["desvio"] / base) if base else None
        # o sinal de desvio já captura o efeito no resultado: custo é lançado
        # negativo, então gastar menos deixa o valor menos negativo (desvio>=0);
        # receita é lançada positiva, então faturar menos dá desvio negativo.
        # Não é preciso olhar QUAL linha é custo ou receita — o sinal do valor
        # já resolve os dois casos.
        d["favoravel"] = d["desvio"] >= 0
        return d

    linhas = [_fecha(v) for v in por_linha.values()]
    contas = [_fecha(v) for v in por_conta.values()]
    ordem = {rot: i for i, (rot, _n, _t, _s) in enumerate(DRE_MODELO)}
    linhas.sort(key=lambda x: ordem.get(x["linha"], 999))
    contas.sort(key=lambda x: abs(x["desvio"]), reverse=True)

    # A grade da aba Montagem precisa das 12 células de TODA conta da versão,
    # independentemente de ate_mes: com o ano ainda não iniciado (ate_mes=0) uma
    # grade derivada de `contas` viria vazia e não haveria o que ajustar.
    grade: dict[str, dict] = {}
    for l in linhas_orc:
        g = grade.setdefault(l["conta"], {
            "conta": l["conta"], "linha": mapa_linha.get(l["conta"]),
            "origem": l["origem"], "meses_com_dado": l["meses_com_dado"],
            "valores": {}, "ajustados": {}})
        g["valores"][l["mes"]] = l["valor_efetivo"]
        g["ajustados"][l["mes"]] = l["valor_ajustado"] is not None

    return {
        "linhas": linhas,
        "contas": contas,
        "grade": sorted(grade.values(), key=lambda g: (g["linha"] or "~", g["conta"])),
        "mensal": [mensal[m] for m in range(1, 13)],
        "sem_linha": sorted(sem_linha),
        "ate_mes": ate_mes,
    }


def meses_faltando(historico: dict[str, dict[str, float]],
                   meses: list[str]) -> list[str]:
    """Meses da base sem nenhum lançamento em conta alguma. Função pura."""
    presentes = {m for serie in historico.values() for m in serie}
    return [m for m in meses if m not in presentes]


def _historico(meses: list[str]) -> dict[str, dict[str, float]]:
    de = f"{meses[0]}-01"
    ate_ano, ate_mes = int(meses[-1][:4]), int(meses[-1][5:7])
    ate_mes += 1
    if ate_mes == 13:
        ate_mes, ate_ano = 1, ate_ano + 1
    ate = f"{ate_ano:04d}-{ate_mes:02d}-01"
    rows = db.query(HIST_CONTA_SQL, {"de": de, "ate": ate})
    hist: dict[str, dict[str, float]] = {}
    for r in rows:
        hist.setdefault(r["conta"], {})[r["mes"]] = r["valor"]
    return hist


def _mapa() -> tuple[dict, dict]:
    rows = db.query(AGRUP_CONTA_SQL)
    agrup = {r["conta"]: r["agrupador"] for r in rows}
    return agrup, ler_ajustes()


def gerar(ano: int, rotulo: str, fator: float, quem: str,
          path=None, hoje: date | None = None,
          versao_id: int | None = None) -> dict:
    """Deriva o baseline do ano.

    Sem `versao_id`, grava numa versão nova. Com `versao_id`, REGERA aquela
    versão no lugar: só o `valor_baseline` é recalculado, e o `valor_ajustado`
    da controladoria sobrevive (spec §2). Sem esse caminho o `ON CONFLICT` do
    `gravar_baseline` nunca dispararia em produção.
    """
    path = path or arm.DB_PATH
    hoje = hoje or date.today()
    meses = meses_fechados(hoje, 12)
    hist = _historico(meses)
    if not hist:
        raise ValueError("Sem histórico fechado para derivar o baseline.")
    # a spec exige bloquear quando a base não tem os 12 meses fechados: derivar mês
    # espelho sobre uma base incompleta produziria zeros disfarçados de orçamento
    faltam = meses_faltando(hist, meses)
    if faltam:
        raise ValueError(
            f"A base precisa de {len(meses)} meses fechados e faltam {len(faltam)}: "
            + ", ".join(faltam))
    linhas = derivar(hist, meses, fator)

    agrup, ajustes = _mapa()
    pendentes = contas_sem_linha(sorted(hist), agrup, ajustes)
    # conta sem agrupador (ou com agrupador que o DRE_MODELO não reconhece) não
    # soma em linha nenhuma: fica fora do baseline e é reportada
    linhas = [l for l in linhas if l["conta"] not in set(pendentes)]

    arm.init_db(path)
    if versao_id is None:
        vid, regerada, zeradas = arm.criar_versao(path, ano, rotulo, fator, quem), False, 0
    else:
        vid, regerada = versao_id, True
        arm.atualizar_versao(path, vid, fator)   # KeyError se a versão não existe
    arm.gravar_baseline(path, vid, linhas)
    if regerada:
        zeradas = arm.zerar_fora_do_conjunto(
            path, vid, {(l["conta"], l["mes"]) for l in linhas})
    return {"versao_id": vid, "linhas": len(linhas), "meses_base": meses,
            "contas_sem_linha": pendentes, "regerada": regerada,
            "celulas_zeradas": zeradas}


def comparativo(versao_id: int, ate_mes: int | None = None,
                path=None, hoje: date | None = None) -> dict:
    """Orçado x realizado da versão, acumulado até o último mês fechado."""
    path = path or arm.DB_PATH
    hoje = hoje or date.today()
    versoes = {v["id"]: v for v in arm.listar_versoes(path)}
    if versao_id not in versoes:
        raise KeyError(f"versão inexistente: {versao_id}")
    v = versoes[versao_id]
    ano = v["ano"]

    if ate_mes is None:
        ate_mes = (hoje.month - 1) if hoje.year == ano else (12 if hoje.year > ano else 0)
    ate_mes = max(0, min(12, ate_mes))

    linhas_orc = arm.ler_linhas(path, versao_id)
    realizado: dict = {}
    if ate_mes > 0:
        fim_ano, fim_mes = (ano, ate_mes + 1) if ate_mes < 12 else (ano + 1, 1)
        rows = db.query(REAL_CONTA_SQL, {"de": f"{ano}-01-01",
                                         "ate": f"{fim_ano:04d}-{fim_mes:02d}-01"})
        for r in rows:
            realizado[(r["conta"], int(r["mes"][5:7]))] = r["valor"]

    agrup, ajustes = _mapa()
    mapa = mapa_conta_linha(agrup, ajustes)
    out = montar_comparativo(linhas_orc, realizado, mapa, ate_mes)
    out["versao"] = dict(v)
    out["fonte"] = ("Orçado: data/orcamento.db (baseline derivado + ajustes). "
                    "Realizado: ERP AVA, lancamento x planoconta, mesma base da DRE.")
    return out
