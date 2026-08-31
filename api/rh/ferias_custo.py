"""Custo de férias — o que JÁ FOI PAGO e o que está PROVISIONADO.

A tela de Férias respondia "quem precisa gozar". Não respondia "quanto isso
custa", que é a pergunta de quem aprova a escala. Este módulo entrega os dois
lados, e eles vêm de fontes de qualidade diferente — por isso não se somam num
número só:

  REALIZADO  — eventos da ficha financeira (`flp_fichaeventos`). É o que a
               folha pagou, sem estimativa nenhuma.
  PROVISÃO   — o passivo de quem ainda não gozou. É ESTIMATIVA sobre o salário
               base, e o módulo MEDE o quanto ela subestima em vez de afirmar
               que está certa (ver `fator`, no fim).

O EVENTO QUE PROVA QUE A DOBRA NÃO É HIPÓTESE
=============================================
`FERIAS EM DOBRO`, `1/3 FERIAS EM DOBRO` e as diferenças delas somam
R$ 12.154 em 12 meses, em 23 lançamentos. O KPI de dobra da tela de risco lê ZERO hoje — e está certo: ele
mede o estado AGORA, e a dobra que houve já foi paga e quitada. Os dois números
não se contradizem, medem tempos diferentes, e é por isso que este cartão
existe: sem ele, "nenhuma em dobra" se leria como "isto nunca acontece aqui".

O EVENTO TRUNCADO QUE NÃO ENTRA NO TOTAL
========================================
O GLOBUS trunca `desceven` em 22 caracteres. `MEDIAS S/ VARIAVEIS -` (códigos
109 e 110, mais as quatro diferenças dele: R$ 190.822 em 12 meses)
provavelmente termina em "FERIAS": 679 dos 768 lançamentos caem numa
competência em que a MESMA pessoa recebeu férias.
89% não é evidência, é indício — então ele fica FORA do total afirmado e
aparece como linha própria, com o percentual à mostra. É a mesma regra da
coluna "Tipo (cód.)" da Manutenção: código sem domínio não vira rótulo
inventado.

O QUE A PROVISÃO NÃO INCLUI, E POR QUE NÃO SE INVENTA
=====================================================
- **FGTS entra**: 8% fixados em lei, iguais para todo regime, e a alíquota é
  dita na tela.
- **INSS patronal NÃO entra**: a alíquota depende do enquadramento e há
  eventos de SIMPLES na ficha desta empresa. Estimar 20% somaria milhões
  inventados. Mesma decisão do Custo de Folha.
- **As médias de variáveis não entram na estimativa**, porque a base é o
  salário BASE. A folha real paga média de hora extra e adicional noturno
  sobre as férias — então o passivo real é MAIOR que o estimado. O módulo não
  se cala sobre isso: mede o fator no realizado e o entrega em `fator`.

CUIDADO COM A FICHA CANCELADA
=============================
`flp_ferias.statusferias='S'` é ficha EXCLUÍDA (230 de 233 têm `dtexclferias`),
não "sim". Contar dias por ela inflaria o denominador do custo por dia em 42%.
O filtro é `dtexclferias IS NULL`.
"""
from __future__ import annotations

from api import db_folha as db

EMPRESA = 1

# Um terço constitucional (art. 7º, XVII): o custo de um dia de férias é 4/3 do
# dia de salário.
UM_TERCO = 4.0 / 3.0
FGTS = 0.08
DIAS_MES = 30.0
DIAS_PERIODO = 30.0          # art. 130, I: 30 dias corridos sem falta relevante
AVO = DIAS_PERIODO / 12.0    # 2,5 dias por mês trabalhado


def _q(sql: str, params: dict | None = None) -> list[dict]:
    return db.query(sql, params or {})


def _f(v) -> float:
    """`numeric` do banco vira `Decimal`, e o `json` não o serializa — e o
    estouro acontece no `render()` da resposta, DEPOIS do `try/except` da
    rota. Converter no limite do módulo é onde o tipo do banco para de
    importar."""
    return round(float(v or 0), 2)


# ── quais eventos são férias ────────────────────────────────────────────────
#
# Casados por NOME, um a um, contra a lista real de `flp_eventos` desta base —
# não por padrão adivinhado. A ORDEM importa: "1/3 FERIAS EM DOBRO" tem de
# cair em dobra antes de cair em terço, senão o cartão da dobra desapareceria
# dentro do total de férias gozadas, que é justamente onde ninguém o veria.
NATUREZAS = [
    ("Dobra (art. 137)",       ("FERIAS EM DOBRO", "1/3 FERIAS EM DOBRO",
                                "MEDIAS S/ FERIAS EM DO", "MEDIAS S/ ABONO EM DOB",
                                "DIFERENCA DE FERIAS EM")),
    ("Abono pecuniário",       ("ABONO PECUNIARIO", "1/3 S/ ABONO PECUNIARI",
                                "1/3 MEDIA ABONO PEC", "DIFERENCA ABONO DE FER",
                                "DIFERENCA 1/3 S/ ABONO")),
    ("Indenizadas (rescisão)", ("FERIAS INDENIZADAS", "1/3 FERIAS VENCIDAS",
                                "FERIAS 1/3 INDENIZADO", "FERIAS SOBRE AVISO",
                                "FERIAS (MEDIAS)")),
    ("Proporcionais",          ("FERIAS PROPORCIONAIS", "1/3 FERIAS PROPORCIONA",
                                "MEDIAS S/ FERIAS PROPO", "MEDIA HR FER PROPORCIO",
                                "MEDIA VL FER PROPORCIO")),
    ("Gozadas (normais)",      ("FERIAS NORMAIS", "1/3 S/ REMUNERACAO DE",
                                "1/3 MEDIA DE FERIAS", "MEDIAS S/ FERIAS VENCI",
                                "DIFERENCA DE FERIAS NO", "DIFERENCA 1/3 FERIAS N",
                                "DIFERENCA 1/3 S/ REMUN", "DIFEREN_A DE FERIAS")),
]

# O `_` É CURINGA DE UM CARACTERE, e ele existe por um defeito de dado que
# custou R$ 3.843 de custo inventado antes de aparecer.
#
# O evento 490 está gravado como `DIFEREN<Ç>A DE FERIAS`, com o cedilha em
# latin-1 (byte 199) dentro de uma coluna que o resto do ERP escreve sem
# acento. A primeira versão o alcançou pelo prefixo curto `DIFEREN` — que
# casa TAMBÉM `DIFERENCA DE SALARIO`, `DIFERENCA 13o`, `DIFERENCA PTS`,
# `DIFERENCA SALARIO CCT`, `DIFERENCA DE DIARIA` e `DIFERENCA ADIC NOTURNO`.
# Nenhuma delas é férias, e todas entravam no total.
#
# O que torna esse erro da família mais perigosa: R$ 3.843 sobre R$ 1,83
# milhão é 0,21%. Nenhum número muda de ordem de grandeza, nenhuma proporção
# se desloca, nenhum veredito da tela vira. Só apareceu porque a soma do
# módulo foi conferida contra a soma manual dos eventos — um segundo caminho
# para o mesmo número.
_CURINGA = "_"


def _casa(nome: str, padrao: str) -> bool:
    """`startswith` com `_` valendo um caractere qualquer, igual ao LIKE."""
    if len(nome) < len(padrao):
        return False
    return all(p == _CURINGA or p == c for p, c in zip(padrao, nome))


# Os eventos cujo nome o ERP cortou antes de dizer a que eles se referem: os
# dois de `MEDIAS S/ VARIAVEIS -` e as quatro diferenças deles, que herdam a
# mesma dúvida pela mesma razão. Ficam FORA do total — ver o cabeçalho.
CINZA_CODS = (109, 110, 365, 368, 412, 415)
CINZA_NOME = "MEDIAS S/ VARIAVEIS -"

# Só proventos: `tipoeven='B'` são BASES de cálculo (base de IRRF, de INSS) e
# somá-las contaria a mesma férias três vezes; `'D'` são descontos, que saem do
# líquido do empregado e não do custo do empregador.
_PROV = "fe.tipoeven = 'P'"

_JOIN = ("FROM flp_fichaeventos ff "
         "JOIN flp_eventos fe ON ff.codevento = fe.codevento "
         "JOIN flp_funcionarios fu ON fu.codintfunc = ff.codintfunc "
         "AND fu.codigoempresa = :emp")

# Todo nome que este módulo reconhece como férias, para o WHERE.
_TODOS = tuple(sorted({n for _, nomes in NATUREZAS for n in nomes}))
_FILTRO_NOMES = " OR ".join(
    "UPPER(fe.desceven) LIKE '{}%'".format(n.replace("'", "''"))
    for n in _TODOS)


def natureza(desc: str) -> str:
    u = (desc or "").upper().strip()
    for rotulo, nomes in NATUREZAS:
        for n in nomes:
            if _casa(u, n):
                return rotulo
    return "Outras rubricas de férias"


def get_ferias_custo(meses: int = 12, filial: str = "") -> dict:
    """Custo de férias: realizado na ficha + provisão do que não foi gozado."""
    meses = max(3, min(24, int(meses or 12)))
    p = {"emp": EMPRESA, "meses": meses}
    filtro_ev = ""
    if filial:
        # A ficha financeira não carrega a unidade; ela vem do cadastro. Um
        # EXISTS mantém o filtro sem multiplicar linha de evento, que é o que
        # um JOIN a mais faria numa tabela com histórico por competência.
        filtro_ev = (" AND EXISTS (SELECT 1 FROM vw_funcionarios v2"
                     " WHERE v2.codintfunc = ff.codintfunc"
                     " AND v2.descsecao = :filial)")
        p["filial"] = filial
    filtro_fil = " AND vf.descsecao = :filial" if filial else ""
    pf = {"emp": EMPRESA, **({"filial": filial} if filial else {})}

    linhas = _q(f"""
        SELECT fe.desceven ev, TO_CHAR(ff.competficha,'YYYY-MM') comp,
               COUNT(*) n, SUM(ff.valorficha) tot
        {_JOIN}
        WHERE {_PROV} AND ({_FILTRO_NOMES})
          AND ff.competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:meses)
          {filtro_ev}
        GROUP BY fe.desceven, TO_CHAR(ff.competficha,'YYYY-MM')""", p)

    # ── realizado: por natureza, por evento e por competência ──────────────
    por_nat: dict[str, dict] = {}
    por_comp: dict[str, float] = {}
    por_ev: dict[str, dict] = {}
    total = 0.0
    for r in linhas:
        v = float(r["tot"] or 0)
        nat = natureza(r["ev"])
        d = por_nat.setdefault(nat, {"natureza": nat, "valor": 0.0, "n": 0})
        d["valor"] += v
        d["n"] += int(r["n"] or 0)
        por_comp[r["comp"]] = por_comp.get(r["comp"], 0.0) + v
        e = por_ev.setdefault(r["ev"], {"ev": r["ev"], "valor": 0.0, "n": 0,
                                        "natureza": nat})
        e["valor"] += v
        e["n"] += int(r["n"] or 0)
        total += v

    dobra_d = por_nat.get("Dobra (art. 137)", {})

    naturezas = sorted(
        ({"natureza": d["natureza"], "valor": _f(d["valor"]), "n": d["n"],
          "pct": round(d["valor"] / total * 100, 1) if total else 0.0}
         for d in por_nat.values()), key=lambda x: -x["valor"])

    eventos = sorted(({"ev": (d["ev"] or "").strip(), "valor": _f(d["valor"]),
                       "n": d["n"], "natureza": d["natureza"]}
                      for d in por_ev.values()), key=lambda x: -x["valor"])

    # A série é GERADA, não colhida. Mês em que ninguém saiu de férias não
    # volta do `GROUP BY`, e o gráfico emendaria o mês anterior no seguinte,
    # desenhando continuidade sobre um buraco — a mesma armadilha que fez a
    # série da jornada ligar abril em agosto. Aqui a ausência é legítima e
    # vale ZERO, então ela precisa aparecer como zero.
    comps = _q("""SELECT TO_CHAR(ADD_MONTHS(TRUNC(SYSDATE,'MM'), -LEVEL+1),
                         'YYYY-MM') c FROM dual CONNECT BY LEVEL <= :meses""",
               {"meses": meses})
    serie = [{"comp": c, "valor": _f(por_comp.get(c, 0.0))}
             for c in sorted(x["c"] for x in comps)]

    # ── a zona cinzenta: evento cujo nome o ERP cortou ─────────────────────
    cinza = _q("""
        SELECT COUNT(*) n, SUM(ff.valorficha) tot,
               SUM(CASE WHEN EXISTS (
                     SELECT 1 FROM flp_fichaeventos f2
                     JOIN flp_eventos e2 ON f2.codevento = e2.codevento
                     WHERE f2.codintfunc = ff.codintfunc
                       AND f2.competficha = ff.competficha
                       AND e2.tipoeven = 'P'
                       AND UPPER(e2.desceven) LIKE 'FERIAS%')
                   THEN 1 ELSE 0 END) com_ferias
        FROM flp_fichaeventos ff
        JOIN flp_funcionarios fu ON fu.codintfunc = ff.codintfunc
             AND fu.codigoempresa = :emp
        WHERE ff.codevento IN ({}) {}
          AND ff.competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:meses)"""
        .format(",".join(str(c) for c in CINZA_CODS), filtro_ev), p)[0]
    c_n, c_ok = int(cinza["n"] or 0), int(cinza["com_ferias"] or 0)

    # ── provisão: o passivo de quem ainda não gozou ────────────────────────
    #
    # Dois pedaços somados por pessoa:
    #   VENCIDO — período aquisitivo fechado e não gozado: 30 dias inteiros.
    #   AVOS    — o período EM CURSO, a 2,5 dias por mês completo (art. 130).
    #
    # QUAL período está em curso depende de já haver direito vencido: quem tem,
    # está acumulando o SEGUNDO (que começou no dia seguinte ao fim do
    # primeiro); quem não tem, ainda está no primeiro. Usar sempre a mesma data
    # contaria os avos do período errado — em quem acabou de fechar um período,
    # somaria doze avos dele ao vencido que ele já é, dobrando o passivo dessas
    # pessoas.
    prov = _q(f"""
        SELECT vf.descsecao filial, COUNT(*) pessoas,
               SUM(CASE WHEN fe.proxaquifinfer <= TRUNC(SYSDATE)
                        THEN 1 ELSE 0 END) com_vencido,
               SUM(CASE WHEN fe.proxaquifinfer <= TRUNC(SYSDATE)
                        THEN vf.salbase / :dm * :dp ELSE 0 END) base_vencido,
               SUM(vf.salbase / :dm * :avo * LEAST(12, GREATEST(0,
                   FLOOR(MONTHS_BETWEEN(TRUNC(SYSDATE),
                     CASE WHEN fe.proxaquifinfer <= TRUNC(SYSDATE)
                          THEN fe.proxaquifinfer
                          ELSE fe.proxaquiinifer END))))) base_avos,
               SUM(vf.salbase) massa
        FROM vw_ferias fe
        JOIN vw_funcionarios vf ON vf.codintfunc = fe.codintfunc
        WHERE vf.situacaofunc = 'A' AND vf.codigoempresa = :emp {filtro_fil}
        GROUP BY vf.descsecao ORDER BY 5 DESC""",
              {**pf, "dm": DIAS_MES, "dp": DIAS_PERIODO, "avo": AVO})

    def _prov_linha(r) -> dict:
        venc = float(r["base_vencido"] or 0) * UM_TERCO
        avos = float(r["base_avos"] or 0) * UM_TERCO
        return {"filial": r["filial"] or "(sem unidade)",
                "pessoas": int(r["pessoas"] or 0),
                "com_vencido": int(r["com_vencido"] or 0),
                "vencido": _f(venc), "avos": _f(avos),
                "fgts": _f((venc + avos) * FGTS),
                "total": _f((venc + avos) * (1 + FGTS))}

    prov_l = [_prov_linha(r) for r in prov]
    pr_venc = sum(x["vencido"] for x in prov_l)
    pr_avos = sum(x["avos"] for x in prov_l)
    pr_fgts = sum(x["fgts"] for x in prov_l)

    # ── exposição à dobra: o que vira dobro se ninguém agendar ─────────────
    #
    # A dobra paga o período DUAS vezes, então o custo EVITÁVEL é UMA vez o
    # período — é esse o número que a decisão usa, e não o dobro cheio, que
    # incluiria as férias que teriam de ser pagas de qualquer jeito.
    exp = _q(f"""
        SELECT COUNT(*) n, SUM(vf.salbase / :dm * :dp) base
        FROM vw_ferias fe
        JOIN vw_funcionarios vf ON vf.codintfunc = fe.codintfunc
        WHERE vf.situacaofunc = 'A' AND vf.codigoempresa = :emp {filtro_fil}
          AND fe.proxaquifinfer <= TRUNC(SYSDATE)
          AND TRUNC(ADD_MONTHS(fe.proxaquifinfer, 12))
              BETWEEN TRUNC(SYSDATE) - 365 AND TRUNC(SYSDATE) + 180""",
             {**pf, "dm": DIAS_MES, "dp": DIAS_PERIODO})[0]
    exp_v = float(exp["base"] or 0) * UM_TERCO * (1 + FGTS)

    # ── o FATOR: o quanto a estimativa sobre salário base subestima ────────
    #
    # Medido, não suposto. De um lado o que a folha PAGOU de férias gozadas; do
    # outro, o que o salário base das MESMAS pessoas daria pelos MESMOS dias.
    # Sem este número o passivo sairia com cara de valor exato, quando ele
    # ignora as médias de hora extra e adicional noturno que a folha paga por
    # cima — e ignorá-las erra sempre para o mesmo lado, o de menos.
    fat = _q("""
        SELECT SUM(fr.diasgozofer * vf.salbase) base_dia, SUM(fr.diasgozofer) dias
        FROM flp_ferias fr
        JOIN vw_funcionarios vf ON vf.codintfunc = fr.codintfunc
        WHERE vf.codigoempresa = :emp AND fr.dtexclferias IS NULL
          AND fr.gozoinifer >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:meses)
          AND fr.gozoinifer < TRUNC(SYSDATE,'MM')""",
             {"emp": EMPRESA, "meses": meses})[0]
    dias_gozo = float(fat["dias"] or 0)
    # O realizado comparável é SÓ o das férias efetivamente gozadas: rescisão,
    # proporcional e abono não têm dia de gozo e inflariam o numerador contra
    # um denominador que não os contém.
    real_gozo = por_nat.get("Gozadas (normais)", {}).get("valor", 0.0)
    est_gozo = float(fat["base_dia"] or 0) / DIAS_MES * UM_TERCO
    fator = round(real_gozo / est_gozo, 2) if est_gozo else None

    return {
        "meses": meses,
        "filtros": {"filial": filial},
        "kpis": {
            "realizado": _f(total),
            "dobra_paga": _f(dobra_d.get("valor", 0.0)),
            "dobra_lanc": int(dobra_d.get("n", 0)),
            "medio_mes": _f(total / meses) if meses else 0.0,
            "provisao": _f(pr_venc + pr_avos + pr_fgts),
            "prov_vencido": _f(pr_venc),
            "prov_avos": _f(pr_avos),
            "prov_fgts": _f(pr_fgts),
            "exposicao": _f(exp_v),
            "exposicao_n": int(exp["n"] or 0),
            "dias_gozados": int(dias_gozo),
            "fator": fator,
            "fgts_pct": FGTS * 100,
        },
        "naturezas": naturezas,
        "eventos": eventos[:20],
        "eventos_total": len(eventos),
        "serie": serie,
        "provisao_filial": prov_l,
        "cinza": {"nome": CINZA_NOME, "valor": _f(cinza["tot"]),
                  "n": c_n, "com_ferias": c_ok,
                  "pct": round(c_ok / c_n * 100, 1) if c_n else 0.0},
        "fonte": "ERP GLOBUS · flp_fichaeventos (realizado) × vw_ferias "
                 "(provisão, estimada sobre salário base)",
        "atualizado_em": _q("SELECT TO_CHAR(SYSDATE,'YYYY-MM-DD HH24:MI') agora "
                            "FROM dual")[0]["agora"],
    }
