"""Painel de TV do RH (`tvrh`) — gente, segurança e qualidade à vista.

Pedido de quem opera (16/09/2026): trazer para o CÓRTEX as duas telas que
rodam hoje na TV do RH ("Gente Sulista" e "Segurança, Qualidade e Gente") e
somar o que mais servir de gestão à vista. Os números da TV antiga foram
REPRODUZIDOS antes de escrever a tela — 194 ativos, 14 afastados, 147/47 por
gênero, tempo de casa 18/87/29/60, 3 admitidos e 17 aniversariantes no mês, os
acidentes e as RNCs mês a mês —, e três regras escondidas saíram daí:

1. **A filial da TV não é a seção do GLOBUS.** "Matriz" soma todas as seções
   MATRIZ* e mais a FILIAL CURITIBA (83 = 25 + 43 + 15); "Joinville" é a
   FILIAL GARUVA. A regra mora em `filial_da_tv()`, e a seção que ela não
   conhece aparece com o próprio nome — nunca some.
2. **Acidentes e RNCs NÃO vêm do GLOBUS**: vêm de
   `sulista.indicadorescorporativos`, a tabela que a Qualidade preenche À MÃO
   no ERP (indicador 7 = acidentes, 16 = reclamações/RNC, `tipo = 2` =
   realizado). "Sem vítima" é leve (1), média (2) e GRAVE (3). "Com vítima"
   é acidente com MORTE (quem opera, 16/09/2026: "com morte, e não grave"), e
   a tabela da Qualidade NÃO TEM esse campo: o número vem do registro do
   próprio CÓRTEX (`api/rh/acidentes_fatais.py`, migration 0099), onde todo
   mês conta — zero ali é "nenhum registro", e a tela diz isso. As linhas
   `classificacao = 0` marcadas como ocupacionais ficam de fora, como na TV
   antiga.
3. **Mês depois do último lançamento é "sem lançamento", não zero.** Em
   16/09/2026 o último lançamento era de 30/06: a TV antiga mostrava zero
   acidentes de julho a setembro, e era ausência de lançamento. Zero que é
   ausência não é desempenho.

NOMES NA PAREDE: aniversariantes, admitidos, desligados e quem faz tempo de
casa aparecem com nome, como na TV antiga (decisão de quem opera). O que NÃO
sai: CPF, salário, motivo de desligamento, e nada disso vai para o Copiloto.

DINHEIRO NÃO VAI PARA A PAREDE: hora extra e banco de horas vão em HORAS.
"""
from __future__ import annotations

import logging
from datetime import date

from api import db, db_folha
from api.people import LIDERANCA, MODALIDADE
from api.queries import VELHA_ATE, cached
from api.queries_folha import EMPRESA

log = logging.getLogger(__name__)

# os marcos de tempo de casa que a parede celebra
MARCOS_ANOS = (1, 5, 10, 15, 20, 25, 30, 35, 40)
# contrato de experiência: 45 dias, prorrogável por mais 45 (CLT art. 445)
EXPERIENCIA_DIAS = (45, 90)
EXPERIENCIA_AVISO_DIAS = 15
ACIDENTE_CLASSE = {1: "leve", 2: "medio", 3: "grave"}
INDICADOR_ACIDENTES, INDICADOR_RNC = 7, 16

MODALIDADE_ROTULO = {"MOT": "Motorista", "OPER": "Operacional", "ADM": "Administrativo",
                     "SEM": "Sem departamento"}
_MINUSCULAS = {"da", "de", "do", "das", "dos", "e"}


def filial_da_tv(secao: str | None) -> str:
    """A filial como a TV do RH chama — ver a regra 1 do módulo."""
    s = (secao or "").strip().upper()
    if not s:
        return "Sem filial"
    if s.startswith("MATRIZ") or s == "FILIAL CURITIBA":
        return "Matriz"
    if s == "FILIAL GARUVA":
        return "Joinville"
    if s == "FILIAL SBC":
        return "SBC"
    if s.startswith("FILIAL "):
        return nome_proprio(s[7:])
    return nome_proprio(s)


def nome_proprio(nome: str | None) -> str:
    """'MILLENE MORAES DA SILVA' -> 'Millene Moraes da Silva'."""
    partes = (nome or "").strip().split()
    return " ".join(p.lower() if (i and p.lower() in _MINUSCULAS) else p.capitalize()
                    for i, p in enumerate(partes))


# quem tem rescisão E não está mais no quadro (ver `mes`)
SAIU = ("NOT EXISTS (SELECT 1 FROM vw_funcionarios va WHERE va.codintfunc = q.codintfunc"
        " AND va.codigoempresa = :emp AND va.situacaofunc IN ('A', 'F'))")


def _qf(sql: str, p: dict | None = None) -> list[dict]:
    return db_folha.query(sql, {"emp": EMPRESA, **(p or {})})


# ----------------------------------------------------------------------------
# Lâmina 1 — Gente Sulista
# ----------------------------------------------------------------------------
@cached(ttl=600, velha_ate=VELHA_ATE)
def gente() -> dict:
    tot = _qf("""
        SELECT SUM(CASE WHEN vf.situacaofunc = 'A' THEN 1 ELSE 0 END) ativos,
               SUM(CASE WHEN vf.situacaofunc = 'F' THEN 1 ELSE 0 END) afastados,
               SUM(CASE WHEN vf.situacaofunc = 'A' AND vf.sexofunc = 'M' THEN 1 ELSE 0 END) homens,
               SUM(CASE WHEN vf.situacaofunc = 'A' AND vf.sexofunc = 'F' THEN 1 ELSE 0 END) mulheres,
               SUM(CASE WHEN vf.situacaofunc = 'A' AND """ + LIDERANCA + """ THEN 1 ELSE 0 END) lideres,
               SUM(CASE WHEN vf.situacaofunc = 'A' AND MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc) < 12 THEN 1 ELSE 0 END) t1,
               SUM(CASE WHEN vf.situacaofunc = 'A' AND MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc) >= 12
                         AND MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc) < 36 THEN 1 ELSE 0 END) t3,
               SUM(CASE WHEN vf.situacaofunc = 'A' AND MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc) >= 36
                         AND MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc) < 60 THEN 1 ELSE 0 END) t5,
               SUM(CASE WHEN vf.situacaofunc = 'A' AND MONTHS_BETWEEN(SYSDATE, vf.dtadmfunc) >= 60 THEN 1 ELSE 0 END) t9
          FROM vw_funcionarios vf WHERE vf.codigoempresa = :emp""")[0]
    secoes = _qf("""SELECT vf.descsecao secao, COUNT(*) n FROM vw_funcionarios vf
                     WHERE vf.codigoempresa = :emp AND vf.situacaofunc = 'A' GROUP BY vf.descsecao""")
    filiais: dict[str, int] = {}
    for r in secoes:
        k = filial_da_tv(r["secao"])
        filiais[k] = filiais.get(k, 0) + int(r["n"] or 0)
    deptos = _qf("SELECT " + MODALIDADE + """ modalidade, COUNT(*) n FROM vw_funcionarios vf
                  WHERE vf.codigoempresa = :emp AND vf.situacaofunc = 'A' GROUP BY """ + MODALIDADE)
    n = lambda k: int(tot[k] or 0)   # noqa: E731
    return {
        "ativos": n("ativos"), "afastados": n("afastados"),
        "genero": {"masculino": n("homens"), "feminino": n("mulheres")},
        "lideranca": {"lideres": n("lideres"), "colaboradores": n("ativos") - n("lideres")},
        "tempo_casa": [{"faixa": "Até 1 ano", "n": n("t1")}, {"faixa": "1 a 3 anos", "n": n("t3")},
                       {"faixa": "3 a 5 anos", "n": n("t5")}, {"faixa": "Mais de 5 anos", "n": n("t9")}],
        "por_filial": sorted(({"filial": k, "n": v} for k, v in filiais.items()),
                             key=lambda x: (-x["n"], x["filial"])),
        "por_departamento": sorted(({"departamento": MODALIDADE_ROTULO.get(r["modalidade"], r["modalidade"]),
                                     "n": int(r["n"] or 0)} for r in deptos),
                                   key=lambda x: -x["n"]),
        "regras": {"filial": "Matriz = seções MATRIZ e Filial Curitiba; Joinville = Filial Garuva",
                   "departamento": "pela lotação: área MOT é Motorista"},
    }


# ----------------------------------------------------------------------------
# O mês: aniversariantes, admitidos, desligados, tempo de casa
# ----------------------------------------------------------------------------
@cached(ttl=600, velha_ate=VELHA_ATE)
def mes(hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    aniv = _qf("""SELECT vf.nomecompletofunc nome, vf.descsecao secao, vf.descfuncaocompleta funcao,
                         EXTRACT(DAY FROM vf.dtnasctofunc) dia
                    FROM vw_funcionarios vf
                   WHERE vf.codigoempresa = :emp AND vf.situacaofunc = 'A'
                     AND EXTRACT(MONTH FROM vf.dtnasctofunc) = :mes""", {"mes": hoje.month})
    adm = _qf("""SELECT vf.nomecompletofunc nome, vf.descsecao secao, vf.descfuncaocompleta funcao,
                        vf.dtadmfunc dt
                   FROM vw_funcionarios vf
                  WHERE vf.codigoempresa = :emp
                    AND vf.dtadmfunc >= TRUNC(SYSDATE, 'MM') AND vf.dtadmfunc < TRUNC(SYSDATE) + 1""")
    # DESLIGAMENTO É A DATA DA RESCISÃO (`flp_quitacao`), e só até hoje: a
    # rescisão lançada com data futura ainda não é desligamento. E SÓ DE QUEM
    # NÃO ESTÁ MAIS AQUI: há rescisão lançada para gente que segue ativa
    # (medido em 16/09/2026: 20 das 35 "dispensas" de nov/2025) — simulação ou
    # rescisão cancelada que ficou no ERP. Contada, o turnover do mês ia a 12%.
    desl = _qf("""SELECT MAX(vf.nomecompletofunc) nome, MAX(vf.descsecao) secao,
                         MAX(vf.descfuncaocompleta) funcao, MAX(q.dtdesligquita) dt
                    FROM flp_quitacao q
                    JOIN vw_funcionarios vf ON vf.codintfunc = q.codintfunc AND vf.codigoempresa = :emp
                   WHERE q.dtdesligquita >= TRUNC(SYSDATE, 'MM') AND q.dtdesligquita < TRUNC(SYSDATE) + 1
                     AND """ + SAIU + """
                   GROUP BY q.codintfunc""")
    casa = _qf("""SELECT vf.nomecompletofunc nome, vf.descsecao secao, EXTRACT(DAY FROM vf.dtadmfunc) dia,
                         EXTRACT(YEAR FROM SYSDATE) - EXTRACT(YEAR FROM vf.dtadmfunc) anos
                    FROM vw_funcionarios vf
                   WHERE vf.codigoempresa = :emp AND vf.situacaofunc = 'A'
                     AND EXTRACT(MONTH FROM vf.dtadmfunc) = :mes
                     AND EXTRACT(YEAR FROM vf.dtadmfunc) < :ano""", {"mes": hoje.month, "ano": hoje.year})

    def pessoa(r, **extra):
        return {"nome": nome_proprio(r["nome"]), "filial": filial_da_tv(r["secao"]),
                "funcao": nome_proprio(r.get("funcao")), **extra}

    aniversariantes = sorted((pessoa(r, dia=int(r["dia"])) for r in aniv),
                             key=lambda x: (x["dia"], x["nome"]))
    return {
        "mes": hoje.strftime("%Y-%m"),
        "aniversariantes": {
            "total": len(aniversariantes),
            "hoje": [a for a in aniversariantes if a["dia"] == hoje.day],
            "proximos_7": [a for a in aniversariantes if hoje.day < a["dia"] <= hoje.day + 7],
        },
        "admitidos": sorted((pessoa(r, data=r["dt"].date().isoformat() if hasattr(r["dt"], "date") else str(r["dt"])[:10])
                             for r in adm), key=lambda x: x["data"]),
        "desligados": sorted((pessoa(r, data=r["dt"].date().isoformat() if hasattr(r["dt"], "date") else str(r["dt"])[:10])
                              for r in desl), key=lambda x: x["data"]),
        "tempo_de_casa": sorted(({"nome": nome_proprio(r["nome"]), "filial": filial_da_tv(r["secao"]),
                                  "dia": int(r["dia"]), "anos": int(r["anos"])}
                                 for r in casa if int(r["anos"]) in MARCOS_ANOS),
                                key=lambda x: (-x["anos"], x["dia"])),
    }


# ----------------------------------------------------------------------------
# Lâmina 2 — Segurança e Qualidade (a tabela da Qualidade, no ERP)
# ----------------------------------------------------------------------------
QUALIDADE_SQL = """
SELECT to_char(anomes, 'YYYY-MM') AS mes, indicador, acidentes, classificacao, reclamacoesclientes
  FROM sulista.indicadorescorporativos
 WHERE tipo = 2 AND indicador IN (%(acid)s, %(rnc)s) AND anomes >= %(de)s
"""
ULTIMO_SQL = """
SELECT indicador, to_char(max(anomes), 'YYYY-MM') AS ultimo, max(coalesce(dtalteracao, dtinclusao)) AS em
  FROM sulista.indicadorescorporativos
 WHERE tipo = 2 AND indicador IN (%(acid)s, %(rnc)s)
 GROUP BY indicador
"""


def _meses(hoje: date, n: int = 12) -> list[str]:
    """Os N meses até o atual, GERADOS — `GROUP BY` não devolve mês sem linha."""
    out = []
    for i in range(n - 1, -1, -1):
        y = hoje.year + (hoje.month - 1 - i) // 12
        m = (hoje.month - 1 - i) % 12 + 1
        out.append(f"{y}-{m:02d}")
    return out


def montar_seguranca(linhas: list[dict], ultimos: dict[int, str | None], hoje: date,
                     fatais: list[str] | None = None) -> dict:
    """Pura: as linhas da tabela da Qualidade (+ as datas dos acidentes fatais
    registrados no CÓRTEX) -> as séries da parede. `fatais=None` é o registro
    que não pôde ser lido: o com vítima fica ausente, nunca zero."""
    meses = _meses(hoje)
    acid = {m: {"leve": 0, "medio": 0, "grave": 0} for m in meses}
    mortes = {m: 0 for m in meses}
    for d in fatais or []:
        if d[:7] in mortes:
            mortes[d[:7]] += 1
    rnc = {m: 0 for m in meses}
    for r in linhas:
        m = r["mes"]
        if m not in acid:
            continue
        if int(r["indicador"]) == INDICADOR_ACIDENTES:
            classe = ACIDENTE_CLASSE.get(int(r["classificacao"] or 0))
            if classe:
                acid[m][classe] += int(r["acidentes"] or 0)
        elif int(r["indicador"]) == INDICADOR_RNC:
            rnc[m] += int(r["reclamacoesclientes"] or 0)

    def lancado(ind, m):
        u = ultimos.get(ind)
        return bool(u) and m <= u

    ano = f"{hoje.year}-"
    serie_acid, serie_rnc = [], []
    for m in meses:
        la = lancado(INDICADOR_ACIDENTES, m)
        serie_acid.append({"mes": m, "lancado": la,
                           "sem_vitima": (acid[m]["leve"] + acid[m]["medio"] + acid[m]["grave"]) if la else None,
                           "leve": acid[m]["leve"] if la else None,
                           "medio": acid[m]["medio"] if la else None,
                           "grave": acid[m]["grave"] if la else None,
                           # a morte vem do registro do CÓRTEX, que não tem "sem lançamento"
                           "com_vitima": mortes[m] if fatais is not None else None})
        lr = lancado(INDICADOR_RNC, m)
        serie_rnc.append({"mes": m, "lancado": lr, "rnc": rnc[m] if lr else None})

    def soma(serie, campo, so_ano=False):
        vals = [s[campo] for s in serie if s[campo] is not None and (not so_ano or s["mes"].startswith(ano))]
        return sum(vals)

    return {
        "acidentes": {"serie": serie_acid, "ultimo_lancamento": ultimos.get(INDICADOR_ACIDENTES),
                      "com_vitima_ano": soma(serie_acid, "com_vitima", True) if fatais is not None else None,
                      "com_vitima_12m": soma(serie_acid, "com_vitima") if fatais is not None else None,
                      "registro_fatal": "ok" if fatais is not None else "indisponivel",
                      "sem_vitima_ano": soma(serie_acid, "sem_vitima", True),
                      "sem_vitima_12m": soma(serie_acid, "sem_vitima")},
        "rnc": {"serie": serie_rnc, "ultimo_lancamento": ultimos.get(INDICADOR_RNC),
                "ano": soma(serie_rnc, "rnc", True), "ultimos_12m": soma(serie_rnc, "rnc")},
        "regras": {"com_vitima": "acidente com morte, do registro do CÓRTEX (a tabela da Qualidade não tem o campo)",
                   "sem_vitima": "classificação leve, média e grave",
                   "fonte": "tabela de indicadores da Qualidade, lançada à mão no ERP"},
    }


@cached(ttl=900, velha_ate=VELHA_ATE)
def _qualidade_erp(de: str) -> dict:
    """Só a leitura do ERP fica em cache; o registro de acidente fatal é da
    casa, barato, e é lido a cada carga — registrado agora, na parede agora."""
    prm = {"acid": INDICADOR_ACIDENTES, "rnc": INDICADOR_RNC, "de": date.fromisoformat(de)}
    return {"linhas": db.query(QUALIDADE_SQL, prm),
            "ultimos": {int(r["indicador"]): r["ultimo"] for r in db.query(ULTIMO_SQL, prm)}}


def seguranca(hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    de = date.fromisoformat(_meses(hoje)[0] + "-01")
    erp = _qualidade_erp(de.isoformat())
    linhas, ultimos = erp["linhas"], erp["ultimos"]
    try:
        from api.rh import acidentes_fatais
        fatais = acidentes_fatais.datas_validas(de)
    except Exception as exc:  # noqa: BLE001 — sem a base da casa, o com vítima fica ausente
        log.warning("tvrh: registro de acidente fatal indisponível (%s)", type(exc).__name__)
        fatais = None
    return montar_seguranca(linhas, ultimos, hoje, fatais)


# ----------------------------------------------------------------------------
# Lâmina 3 — os indicadores de gestão de gente
# ----------------------------------------------------------------------------
@cached(ttl=900, velha_ate=VELHA_ATE)
def turnover() -> dict:
    hoje = date.today()
    meses = _meses(hoje)
    adm = _qf("""SELECT TO_CHAR(dtadmfunc, 'YYYY-MM') m, COUNT(*) n FROM vw_funcionarios
                  WHERE codigoempresa = :emp AND dtadmfunc >= ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -11)
                    AND dtadmfunc < TRUNC(SYSDATE) + 1 GROUP BY TO_CHAR(dtadmfunc, 'YYYY-MM')""")
    dem = _qf("""SELECT TO_CHAR(q.dtdesligquita, 'YYYY-MM') m, COUNT(DISTINCT q.codintfunc) n
                   FROM flp_quitacao q JOIN flp_funcionarios f ON f.codintfunc = q.codintfunc AND f.codigoempresa = :emp
                  WHERE q.dtdesligquita >= ADD_MONTHS(TRUNC(SYSDATE, 'MM'), -11)
                    AND q.dtdesligquita < TRUNC(SYSDATE) + 1 AND """ + SAIU + """
                  GROUP BY TO_CHAR(q.dtdesligquita, 'YYYY-MM')""")
    ativos = int(_qf("""SELECT COUNT(*) n FROM vw_funcionarios
                         WHERE codigoempresa = :emp AND situacaofunc = 'A'""")[0]["n"] or 0)
    a = {r["m"]: int(r["n"]) for r in adm}
    d = {r["m"]: int(r["n"]) for r in dem}
    atual = hoje.strftime("%Y-%m")
    serie = [{"mes": m, "admissoes": a.get(m, 0), "desligamentos": d.get(m, 0),
              "pct": round(100 * (a.get(m, 0) + d.get(m, 0)) / 2 / ativos, 1) if ativos else None,
              "parcial": m == atual} for m in meses]
    return {"serie": serie, "ativos": ativos,
            "regra": "(admissões + desligamentos) ÷ 2 ÷ quadro ativo de hoje"}


def _experiencia(hoje: date) -> dict:
    r = _qf("""SELECT vf.dtadmfunc adm FROM vw_funcionarios vf
                WHERE vf.codigoempresa = :emp AND vf.situacaofunc = 'A'
                  AND vf.dtadmfunc >= TRUNC(SYSDATE) - 95""")
    vencendo = 0
    for x in r:
        adm = x["adm"].date() if hasattr(x["adm"], "date") else date.fromisoformat(str(x["adm"])[:10])
        for dias in EXPERIENCIA_DIAS:
            falta = (adm.toordinal() + dias - 1) - hoje.toordinal()
            if 0 <= falta <= EXPERIENCIA_AVISO_DIAS:
                vencendo += 1
                break
    return {"vencendo": vencendo, "em_experiencia": len(r), "aviso_dias": EXPERIENCIA_AVISO_DIAS}


def indicadores() -> dict:
    """Cada peça num `try` próprio: a parede segue com o que respondeu."""
    from api import frequencia as fr
    from api import queries_folha as qf
    out: dict = {}

    def pegar(chave, fn):
        try:
            out[chave] = fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("tvrh: %s indisponível (%s)", chave, type(exc).__name__)
            out[chave] = {"erro": "indisponivel"}

    pegar("turnover", turnover)

    def _abs():
        b = fr.get_batidas(12)
        return {"serie": [{"mes": m["mes"], "pct": m.get("pct_falta"), "parcial": bool(m.get("parcial"))}
                          for m in (b.get("absenteismo") or [])][-12:],
                "publico": "administrativo (quem bate ponto)"}
    pegar("absenteismo", _abs)

    def _banco():
        k = fr.get_banco_horas()["kpis"]
        return {k2: k.get(k2) for k2 in ("credor_h", "credores", "devedor_h", "devedores", "liquido_h", "pessoas")}
    pegar("banco_horas", _banco)

    def _he():
        r = qf.get_horas_extras()
        return {"competencia": r.get("competencia"), "horas": r["kpis"].get("horas_mes"),
                "pessoas": r["kpis"].get("funcs_mes")}
    pegar("hora_extra", _he)

    def _ferias():
        k = qf.get_ferias()["kpis"]
        return {"em_dobra": k.get("em_dobra"), "alerta": k.get("alerta"), "em_ferias": k.get("em_ferias_agora")}
    pegar("ferias", _ferias)

    def _cnh():
        k = qf.get_cnh(30)["kpis"]
        return {"vencidas": k.get("vencidas"), "vence_30": k.get("vence_30")}
    pegar("cnh", _cnh)
    pegar("experiencia", lambda: _experiencia(date.today()))
    return out


def painel() -> dict:
    """A resposta da TV: cada bloco responde sozinho — um ERP com dia ruim
    derruba o bloco dele, não a parede inteira."""
    out: dict = {"hoje": date.today().isoformat()}
    for chave, fn in (("gente", gente), ("mes", mes), ("seguranca", seguranca)):
        try:
            out[chave] = fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("tvrh: bloco %s falhou (%s)", chave, type(exc).__name__)
            out[chave] = {"erro": "indisponivel"}
    out["indicadores"] = indicadores()
    return out


def resumo_copiloto() -> dict:
    """SÓ escalares, sem nenhum nome: o snapshot pode ir a modelo externo."""
    g, s = gente(), seguranca()
    m = mes()
    return {"ativos": g["ativos"], "afastados": g["afastados"], "lideres": g["lideranca"]["lideres"],
            "aniversariantes_mes": m["aniversariantes"]["total"], "admitidos_mes": len(m["admitidos"]),
            "desligados_mes": len(m["desligados"]),
            "acidentes_sem_vitima_ano": s["acidentes"]["sem_vitima_ano"],
            "acidentes_com_vitima_ano": s["acidentes"]["com_vitima_ano"],
            "acidentes_ultimo_lancamento": s["acidentes"]["ultimo_lancamento"],
            "rnc_ano": s["rnc"]["ano"], "rnc_ultimo_lancamento": s["rnc"]["ultimo_lancamento"]}
