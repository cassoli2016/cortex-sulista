"""Frequência (ponto eletrônico) do GLOBUS — banco de horas e saúde das batidas.

O QUE ESTE MÓDULO ENXERGA, E O QUE NÃO
======================================
O módulo de frequência do Globus é **do administrativo**. Medido em 09/09/2026:
dos 195 ativos, **92 têm `TEMFREQUENFUNC='S'`** — e os 81 motoristas
(63 carreteiro + 17 truck + 1 bitrem) têm ZERO digitação, porque jornada de
motorista é a Lei 13.103 e mora na frente de jornada (`jor_*`/RasterJOR).

Por isso **todo denominador daqui é o público com frequência, nunca o quadro**.
Um percentual sobre 195 mente por um fator de dois. `publico()` é a fonte única
dessa contagem, e a tela é obrigada a dizê-la.

O REGIME É BANCO DE HORAS, E ELE SE ACERTA NO MÊS
=================================================
12 meses fechados (set/2025 a ago/2026), só o público com frequência: 11.042,4 h
de hora extra PAGA em dinheiro contra 8.147,9 h creditadas no banco — 58% da hora
extra do administrativo sai em dinheiro num regime que deveria compensar em
folga. (A folha grava hora DECIMAL; o banco grava HH.MM e só se soma depois de
convertido — ver `minutos()`.)

`FRQ_BANCOHORAS_PARAMETRO` tem `meses_compensar = 0` e `pgsaldomes = 'S'`: o
saldo credor se PAGA no mês, e não há prazo de compensação configurado.

O SALDO SE LÊ COMO O EXTRATO DO GLOBUS — VALIDADO LINHA A LINHA
===============================================================
Em 14/09/2026 quem opera mandou o "Extrato do Banco de Horas" oficial (08/2026,
97 pessoas), e ele foi reproduzido 97/97 nas três colunas: saldo anterior =
`saldoanterior`, saldo atual = `credito − debito`, total = `saldoanterior` do
mês seguinte. Até então esta tela lia `saldonacompet` — um acumulador que não
conversa com o extrato — e publicava 6.161 h credoras onde o ERP reporta 1.158
h; e somava HH.MM como se fosse decimal. A conclusão "o pagamento não baixa o
saldo", que estava escrita aqui, era verdade sobre o ACUMULADOR: o saldo que o
ERP reporta ZERA o credor quando a casa paga (em 2026, um para um entre pagar e
zerar, com os fechamentos grandes em fevereiro e agosto).

A lição é a de 09/09, um degrau abaixo. Naquela vez o número foi validado contra
si mesmo; desta, contra uma série do próprio ERP — que era a série errada.
Validar é reproduzir o RELATÓRIO que o dono do dado usa.

TRÊS ARMADILHAS QUE JÁ CUSTARAM NÚMERO ERRADO AQUI
===================================================
1. **`FRQ_DIGITACAOMOVIMENTO` é MOVIMENTO, não dia** — 1,3 a 2,7 linhas por
   pessoa-dia. Contar linha como dia inflou "faltas" de 1.179 para 2.981 em
   jul/2025 na primeira passada. Dia é `DISTINCT (codintfunc, dtdigit)`.
2. **O campo de absenteísmo do Globus está desligado**: `ABSENTEISMOCORR` é
   `'N'` nas 33 ocorrências, FALTAS inclusive. Relatório nativo de absenteísmo
   sai zerado. Quem separa falta de trabalho é o `CODOCORR` (4 = FALTAS,
   8 = ATESTADO, 1 e 13 = trabalhando), não o campo que tem esse nome.
3. **A competência corrente é PARCIAL e o mês corrente do ponto é pior que
   parcial**: a importação do AFD é manual (mediana de 3 dias entre execuções,
   máximo de 18), então o mês em curso não é "pouco preenchido", é
   INDETERMINADO. Por isso o padrão de `get_banco_horas` é a última competência
   FECHADA, e `frescor()` publica a defasagem para a tela carimbar.

"""
from __future__ import annotations

from datetime import date

from api import db_folha as db
from api.queries import cached

EMPRESA = 1

# Ocorrências que o Globus usa para dizer o que foi o dia. Os códigos são do
# cadastro da casa (`FRQ_OCORRENCIA`), conferidos em 09/09/2026 — e não há
# tabela de domínio publicada, então mudar um código aqui exige reconferir lá.
OCOR_FALTA = 4
OCOR_ATESTADO = 8
OCOR_TRABALHO = (1, 13)          # TRABALHANDO e HORAS TRAB

# Eventos de hora extra na ficha financeira, por CÓDIGO e não por nome: o
# `desceven` varia ("H.E 50%", "H.E NOT 50%") e casar por LIKE já trouxe
# evento de outra natureza noutra tela.
EV_HE = (15, 19, 268, 454)
EV_DEB_BH, EV_CRED_BH = 1016, 1017

# ============================================================================
# A hora do Globus: HH.MM
# ============================================================================
# O `frq_*` GRAVA HORA COMO HH.MM — os MINUTOS depois do ponto: `-17.36` é
# −17h36, e não −17,36 h. Validado em 14/09/2026 contra o "Extrato do Banco de
# Horas" oficial (97/97) e sobre os 3.051 valores de hora de 2026: nenhum tem
# "minutos" de 60 para cima. Somar ou subtrair o número cru erra calado — 15.22
# − 12.37 dá 2,85, e o certo é 2:45 —, então TODA conta passa por `minutos()`
# antes, e a tela mostra H:MM, como o extrato que o RH confere.
#
# A FOLHA NÃO É ASSIM: `flp_fichaeventos.referencia` (hora extra paga) é hora
# DECIMAL — 1.487 de 4.638 valores têm fração de 0,60 para cima. As duas se
# comparam em horas decimais, depois da conversão do banco.


def minutos(v) -> int:
    """Hora do `frq_*` (HH.MM) em minutos inteiros. `None` vale zero.

    RECUSA o que não é HH.MM em vez de adivinhar: "minutos" de 60 para cima
    querem dizer que o formato mudou, e converter assim mesmo publicaria um
    saldo errado com cara de certo."""
    if v is None:
        return 0
    x = float(v)
    a = abs(x)
    h = int(a)
    m = int(round((a - h) * 100))
    if m == 100:            # 0,9999... do ponto flutuante
        h, m = h + 1, 0
    if m >= 60:
        raise ValueError("hora fora do formato HH.MM do Globus: %r" % (v,))
    t = h * 60 + m
    return -t if x < 0 else t


def horas(mi: int | None) -> float | None:
    """Minutos em horas decimais — só para somar, ordenar e estimar custo."""
    return None if mi is None else round(mi / 60.0, 2)


def hhmm(mi: int | None) -> str | None:
    """Minutos em "H:MM", com sinal — o formato do extrato do Globus."""
    if mi is None:
        return None
    a = abs(int(mi))
    return "%s%d:%02d" % ("-" if mi < 0 else "", a // 60, a % 60)


def _mes_seguinte(comp: str) -> str:
    a, m = int(comp[:4]), int(comp[5:7])
    return "%04d-%02d" % (a + m // 12, m % 12 + 1)


def _q(sql: str, p: dict | None = None) -> list[dict]:
    return db.query(sql, p or {})


def _f(v) -> float:
    """Converte no LIMITE do módulo. Decimal/None chegando ao JSONResponse
    estoura DEPOIS do try/except da rota, em render(), e vira 500 em
    text/plain sem pista nenhuma."""
    return round(float(v), 2) if v is not None else 0.0


# ============================================================================
# O público: quem está sujeito a ponto
# ============================================================================
@cached(ttl=600, velha_ate=7200)
def publico() -> dict:
    """Quem tem frequência, contra o quadro inteiro — a tela DIZ os dois."""
    r = _q("""SELECT COUNT(*) ativos,
                     SUM(CASE WHEN temfrequenfunc='S' THEN 1 ELSE 0 END) com_freq,
                     SUM(CASE WHEN temfrequenfunc='S' AND codhora IS NOT NULL
                              THEN 1 ELSE 0 END) com_horario
                FROM vw_funcionarios
               WHERE codigoempresa=:emp AND situacaofunc='A'""",
           {"emp": EMPRESA})[0]
    return {
        "ativos": r["ativos"] or 0,
        "com_frequencia": r["com_freq"] or 0,
        # Só quem tem CODHORA permite comparar previsto × realizado. Eram 37 de
        # 92 em 09/09/2026: sem isso, atraso e cumprimento de horário nascem
        # com cobertura de 40% — a tela diz, em vez de calar.
        "com_horario": r["com_horario"] or 0,
    }


# ============================================================================
# Frescor: até quando a apuração enxerga
# ============================================================================
@cached(ttl=300, velha_ate=7200)
def frescor() -> dict:
    """Até que dia existe marcação, e há quanto tempo ninguém importa.

    NÃO É DEFASAGEM DE DIGITAÇÃO, É COLETA MANUAL. O AFD vem do Ponto
    Certificado por execução humana: mediana de 3 dias entre importações,
    máximo de 18, e caindo (14 dias com coleta em jul/2025 → 5 em jul/2026).
    Tela que não disser isso mostra "queda de horas" no mês corrente que é só
    ausência de importação.
    """
    r = _q("""SELECT TO_CHAR(MAX(dtdigit),'YYYY-MM-DD') ultimo_dia,
                     TO_CHAR(MAX(dtdigitdigit),'YYYY-MM-DD HH24:MI') ultima_digitacao,
                     ROUND(TRUNC(SYSDATE) - MAX(TRUNC(dtdigit))) dias_atraso
                FROM globus729.frq_digitacaomovimento""")[0]
    c = _q("""SELECT TO_CHAR(MAX(dataprocessamento),'YYYY-MM-DD HH24:MI') ultima_coleta,
                     ROUND((SYSDATE - MAX(dataprocessamento))*24) horas_desde
                FROM globus729.frq_pontocertificado_log""")[0]
    return {
        "ultimo_dia": r["ultimo_dia"],
        "ultima_digitacao": r["ultima_digitacao"],
        "dias_atraso": int(r["dias_atraso"] or 0),
        "ultima_coleta": c["ultima_coleta"],
        "horas_desde_coleta": int(c["horas_desde"] or 0),
        "coleta": "manual",
    }


def _ultima_competencia_fechada() -> str | None:
    r = _q("""SELECT TO_CHAR(MAX(competencia),'YYYY-MM') c
                FROM globus729.frq_bancohoras
               WHERE competencia < TRUNC(SYSDATE,'MM')""")
    return r[0]["c"] if r and r[0]["c"] else None


# ============================================================================
# Banco de horas — o saldo, como o Extrato do Banco de Horas do Globus
# ============================================================================
# AS TRÊS COLUNAS DO EXTRATO, e de onde cada uma sai (97/97, 14/09/2026):
#
#     Saldo anterior .... `saldoanterior` da competência
#     Saldo atual ....... `credito − debito` da competência (o MOVIMENTO)
#     Total ............. `saldoanterior` da competência SEGUINTE — o que foi
#                         levado depois do acerto do mês
#
# O saldo no fim do mês é anterior + movimento. O que é levado adiante NÃO se
# calcula: quando a casa paga (`valorpago`), o credor entra no mês seguinte
# zerado, e alguns devedores também são acertados. Por isso "levado" vem do
# próprio ERP, do `saldoanterior` do mês seguinte, e fica `None` enquanto esse
# mês não foi gerado — nunca uma conta nossa.
#
# `saldonacompet` NÃO ENTRA. Até a v1.80.0 a tela lia esse campo como saldo, e
# ele é um acumulador que não conversa com o extrato (bate com anterior +
# movimento em 27 de 97).
#
# SÓ QUEM ESTÁ ATIVO, como o extrato (as 97 são todas `situacaofunc = 'A'`).
# Desligado e afastado com saldo vão para `nao_ativos`, fora dos totais — nunca
# somem.

_BANCO_MES_SQL = """
    SELECT b.codintfunc cod, TO_CHAR(b.competencia,'YYYY-MM') comp,
           vf.chapafunc chapa, vf.nomefunc nome, vf.descsecao filial,
           vf.descfuncao funcao, vf.situacaofunc situacao, vf.salbase salbase,
           b.saldoanterior anterior, b.credito credito, b.debito debito,
           b.valorpago valorpago
      FROM globus729.frq_bancohoras b
      JOIN vw_funcionarios vf ON vf.codintfunc = b.codintfunc
                             AND vf.codigoempresa = :emp
     WHERE b.competencia IN (TO_DATE(:comp,'YYYY-MM'),
                             ADD_MONTHS(TO_DATE(:comp,'YYYY-MM'),1))"""


@cached(ttl=600, velha_ate=7200)
def _linhas_do_banco(meses: int) -> list[dict]:
    """Anterior, crédito, débito e saldo no fim do mês de quem está ATIVO, mês a
    mês — a matéria da série e do confronto, convertida UMA vez, em Python. A
    regra do HH.MM tem um lugar só: SQL e Python com a mesma conta discordariam
    calados."""
    linhas = _q("""
        SELECT TO_CHAR(b.competencia,'YYYY-MM') comp,
               b.saldoanterior anterior, b.credito credito, b.debito debito
          FROM globus729.frq_bancohoras b
          JOIN vw_funcionarios vf ON vf.codintfunc = b.codintfunc
                                 AND vf.codigoempresa = :emp
                                 AND vf.situacaofunc = 'A'
         WHERE b.competencia >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:m)""",
                {"emp": EMPRESA, "m": meses})
    saida = []
    for r in linhas:
        ant = minutos(r["anterior"])
        cred, deb = minutos(r["credito"]), minutos(r["debito"])
        saida.append({"comp": r["comp"], "anterior": ant, "credito": cred,
                      "debito": deb, "fim": ant + cred - deb})
    return saida


def _por_competencia(linhas: list[dict]) -> dict[str, dict]:
    """Credor e devedor no fim de cada mês, em MINUTOS."""
    por: dict[str, dict] = {}
    for x in linhas:
        c = por.setdefault(x["comp"], {"credor": 0, "devedor": 0, "pessoas": 0,
                                       "debito": 0})
        c["pessoas"] += 1
        c["debito"] += x["debito"]
        if x["fim"] > 0:
            c["credor"] += x["fim"]
        elif x["fim"] < 0:
            c["devedor"] += x["fim"]
    return por


@cached(ttl=600, velha_ate=7200)
def get_banco_horas(comp: str | None = None) -> dict:
    comps = [r["c"] for r in _q(
        """SELECT DISTINCT TO_CHAR(competencia,'YYYY-MM') c
             FROM globus729.frq_bancohoras
            WHERE competencia >= ADD_MONTHS(TRUNC(SYSDATE,'MM'),-24)
            ORDER BY 1 DESC""")]
    fechada = _ultima_competencia_fechada()
    if not comp or comp not in comps:
        comp = fechada
    if not comp:
        return {"competencia": None, "competencias": [], "kpis": {}, "pessoas": [],
                "nao_ativos": [], "faixas": [], "serie": [],
                "fonte": "GLOBUS · FRQ_BANCOHORAS (sem dado)"}
    seguinte = _mes_seguinte(comp)
    brutas = _q(_BANCO_MES_SQL, {"emp": EMPRESA, "comp": comp})
    prox = {r["cod"]: r for r in brutas if r["comp"] == seguinte}
    tem_seguinte = bool(prox)

    pessoas, nao_ativos = [], []
    for r in brutas:
        if r["comp"] != comp:
            continue
        ant = minutos(r["anterior"])
        cred, deb = minutos(r["credito"]), minutos(r["debito"])
        mov = cred - deb
        fim = ant + mov
        p = prox.get(r["cod"])
        lev = minutos(p["anterior"]) if p else None
        salbase = float(r["salbase"] or 0)
        item = {
            "chapa": str(r["chapa"] or "").strip(), "nome": r["nome"],
            "filial": r["filial"] or "—", "funcao": r["funcao"] or "—",
            "situacao": r["situacao"],
            # as colunas do extrato: em minutos para a conta, em H:MM para ler
            "anterior_min": ant, "credito_min": cred, "debito_min": deb,
            "movimento_min": mov, "fim_min": fim, "levado_min": lev,
            "anterior": hhmm(ant), "credito": hhmm(cred), "debito": hhmm(deb),
            "movimento": hhmm(mov), "fim": hhmm(fim), "levado": hhmm(lev),
            "horas": horas(fim),
            "pago_no_mes": float(r["valorpago"] or 0) > 0,
            # Custo só para o saldo CREDOR, e é ESTIMATIVA: 50% sobre
            # salbase/220 — a alíquota real depende do acordo, e a premissa
            # viaja no payload.
            "custo": _f(horas(fim) * (salbase / 220) * 1.5) if fim > 0 else 0.0,
        }
        if r["situacao"] == "A":
            pessoas.append(item)
        elif ant or mov or fim:
            nao_ativos.append(item)
    # na ordem do extrato — por nome —, para conferir lado a lado
    pessoas.sort(key=lambda x: x["nome"] or "")
    nao_ativos.sort(key=lambda x: x["nome"] or "")

    cred = [x for x in pessoas if x["fim_min"] > 0]
    dev = [x for x in pessoas if x["fim_min"] < 0]
    s_cred = sum(x["fim_min"] for x in cred)
    s_dev = sum(x["fim_min"] for x in dev)
    s_lev = sum(x["levado_min"] or 0 for x in pessoas) if tem_seguinte else None
    maior = max((x["fim_min"] for x in cred), default=0)

    faixas_def = [("1 · acima de 300 h", 300, 1e9), ("2 · 200 a 300 h", 200, 300),
                  ("3 · 100 a 200 h", 100, 200), ("4 · 40 a 100 h", 40, 100),
                  ("5 · até 40 h", 0, 40)]
    faixas = []
    for rot, lo, hi in faixas_def:
        g = [x for x in cred if lo <= x["horas"] < hi]
        if g:
            faixas.append({"faixa": rot, "pessoas": len(g),
                           "horas": round(sum(x["horas"] for x in g), 1),
                           "hhmm": hhmm(sum(x["fim_min"] for x in g)),
                           "custo": _f(sum(x["custo"] for x in g))})

    # ── a série: o saldo no fim de cada mês ─────────────────────────────
    # O mês corrente ENTRA, marcado `parcial`: escondê-lo faria a série parecer
    # terminada num mês que ainda não fechou.
    serie = [{"comp": c, "credor": horas(v["credor"]), "devedor": horas(v["devedor"]),
              "liquido": horas(v["credor"] + v["devedor"]), "pessoas": v["pessoas"],
              "parcial": bool(fechada and c > fechada)}
             for c, v in sorted(_por_competencia(_linhas_do_banco(14)).items())]

    return {
        "competencia": comp,
        "competencias": comps,
        "competencia_fechada": fechada,
        "competencia_seguinte": seguinte if tem_seguinte else None,
        "kpis": {
            "credor_h": horas(s_cred), "credor_hhmm": hhmm(s_cred),
            "credores": len(cred),
            "devedor_h": horas(s_dev), "devedor_hhmm": hhmm(s_dev),
            "devedores": len(dev),
            "liquido_h": horas(s_cred + s_dev), "liquido_hhmm": hhmm(s_cred + s_dev),
            "maior_h": horas(maior), "maior_hhmm": hhmm(maior),
            "custo_credor": _f(sum(x["custo"] for x in cred)),
            "pagos_no_mes": sum(1 for x in pessoas if x["pago_no_mes"]),
            "levado_h": horas(s_lev), "levado_hhmm": hhmm(s_lev),
            "credores_zerados": (sum(1 for x in cred if x["levado_min"] == 0)
                                 if tem_seguinte else None),
            "pessoas": len(pessoas),
            "nao_ativos": len(nao_ativos),
        },
        "pessoas": pessoas,
        "nao_ativos": nao_ativos,
        "faixas": faixas,
        "serie": serie,
        "destino_he": _destino_da_he(),
        "confronto": confronto(),
        "publico": publico(),
        "frescor": frescor(),
        "premissa_custo": "saldo credor no fim do mês × (salário base ÷ 220) × 1,5",
        "fonte": ("GLOBUS · FRQ_BANCOHORAS — saldo anterior + crédito − débito, "
                  "HH.MM convertido em minutos: as colunas do Extrato do Banco de "
                  "Horas · só ativos"),
    }


@cached(ttl=900, velha_ate=7200)
def confronto(meses: int = 24) -> dict:
    """A hora extra PAGA × o saldo do banco, na mesma linha do tempo.

    O saldo é o do EXTRATO — anterior + movimento, só ativos, pelo mesmo
    `_linhas_do_banco` da série —, e há teste que cobra que os dois caminhos dão
    o mesmo número. Até a v1.80.0 este cartão lia `saldonacompet` e concluía
    que "pagar não baixa o saldo"; pelo saldo certo, o mês em que a casa paga é
    o mês em que o credor zera.

    As horas pagas vêm da FOLHA, que grava hora DECIMAL: a comparação é em
    horas decimais, depois da conversão do banco. E o mês corrente fica fora
    dos dois lados — ele não fechou.
    """
    meses = max(12, min(int(meses or 24), 48))
    corrente = date.today().strftime("%Y-%m")
    pagos = {r["comp"]: r for r in _q("""
        SELECT TO_CHAR(ff.competficha,'YYYY-MM') comp,
               COUNT(DISTINCT ff.codintfunc) pessoas,
               ROUND(SUM(ff.referencia),1) horas,
               ROUND(SUM(ff.valorficha),2) reais
          FROM flp_fichaeventos ff
          JOIN vw_funcionarios vf ON vf.codintfunc = ff.codintfunc
                                 AND vf.codigoempresa = :emp
                                 AND vf.temfrequenfunc = 'S'
         WHERE ff.codevento IN (15,19,268,454)
           AND ff.competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:m)
           AND ff.competficha <  TRUNC(SYSDATE,'MM')
         GROUP BY TO_CHAR(ff.competficha,'YYYY-MM')""",
        {"emp": EMPRESA, "m": meses})}
    saldos = {c: v for c, v in _por_competencia(_linhas_do_banco(meses)).items()
              if c < corrente}

    #: O evento que DARIA a baixa pela folha. Pouco usado — o acerto que zera o
    #: credor é o do próprio banco (`valorpago`), não este evento.
    baixas = {r["comp"]: float(r["horas"] or 0) for r in _q("""
        SELECT TO_CHAR(competficha,'YYYY-MM') comp, ROUND(SUM(referencia),1) horas
          FROM flp_fichaeventos
         WHERE codevento = 1016
           AND competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:m)
         GROUP BY TO_CHAR(competficha,'YYYY-MM')""", {"m": meses})}

    serie, anterior = [], None
    for comp in sorted(set(pagos) | set(saldos)):
        pg, sd = pagos.get(comp, {}), saldos.get(comp)
        saldo = horas(sd["credor"]) if sd else None
        serie.append({
            "comp": comp,
            "pago_h": float(pg.get("horas") or 0),
            "pago_rs": _f(pg.get("reais")),
            "pessoas": int(pg.get("pessoas") or 0),
            "saldo": saldo,
            "variacao": round(saldo - anterior, 1)
                        if (saldo is not None and anterior is not None) else None,
            "debito_banco": horas(sd["debito"]) if sd else None,
            "baixa_pela_folha": baixas.get(comp, 0.0),
        })
        if saldo is not None:
            anterior = saldo

    com_saldo = [x for x in serie if x["saldo"] is not None]
    return {
        "serie": serie,
        "pago_h": round(sum(x["pago_h"] for x in serie), 1),
        "pago_rs": _f(sum(x["pago_rs"] for x in serie)),
        "baixa_pela_folha_h": round(sum(x["baixa_pela_folha"] for x in serie), 1),
        "saldo_no_inicio": com_saldo[0]["saldo"] if com_saldo else None,
        "saldo_no_fim": com_saldo[-1]["saldo"] if com_saldo else None,
        "meses": meses,
    }


@cached(ttl=900, velha_ate=7200)
def _destino_da_he() -> dict:
    """Hora extra do público com frequência: paga × creditada × compensada.

    12 meses FECHADOS. A pergunta que isto responde é a única que importa num
    regime de banco de horas: a folga está compensando, ou está virando
    dinheiro? Medido em 09/09/2026: 58% vira dinheiro.
    """
    pago = _q("""SELECT NVL(SUM(ff.referencia),0) h, NVL(SUM(ff.valorficha),0) rs
                   FROM flp_fichaeventos ff
                   JOIN vw_funcionarios vf ON vf.codintfunc = ff.codintfunc
                                          AND vf.codigoempresa = :emp
                                          AND vf.temfrequenfunc = 'S'
                  WHERE ff.codevento IN (15,19,268,454)
                    AND ff.competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'),-12)
                    AND ff.competficha <  TRUNC(SYSDATE,'MM')""",
                {"emp": EMPRESA})[0]
    # O banco em HH.MM, convertido linha a linha; a folha já é hora decimal.
    bh = _q("""SELECT credito, debito FROM globus729.frq_bancohoras
                WHERE competencia >= ADD_MONTHS(TRUNC(SYSDATE,'MM'),-12)
                  AND competencia <  TRUNC(SYSDATE,'MM')""")
    pago_h = round(float(pago["h"] or 0), 1)
    cred_h = round(sum(minutos(r["credito"]) for r in bh) / 60.0, 1)
    deb_h = round(sum(minutos(r["debito"]) for r in bh) / 60.0, 1)
    total = pago_h + cred_h
    return {
        "pago_horas": pago_h,
        "pago_reais": _f(pago["rs"]),
        "creditado_horas": cred_h,
        "compensado_horas": deb_h,
        "pct_em_dinheiro": round(100 * pago_h / total, 1) if total else 0.0,
        "janela": "12 meses fechados",
    }


# ============================================================================
# Batidas — a apuração está sã?
# ============================================================================
@cached(ttl=600, velha_ate=7200)
def get_batidas(meses: int = 12) -> dict:
    meses = max(3, min(int(meses or 12), 24))
    p = {"m": meses}

    # ── origem da marcação, mês a mês ───────────────────────────────────
    # RL = relógio (o REP-P, via AFD). DP = digitada pelo Departamento
    # Pessoal. A subida do DP é o alarme: 3,3% até jun/2026, 16,9% em ago —
    # cinco vezes, e em TODAS as filiais ao mesmo tempo, o que descarta
    # relógio quebrado numa unidade.
    corrente = _q("SELECT TO_CHAR(TRUNC(SYSDATE,'MM'),'YYYY-MM') m FROM dual")[0]["m"]
    origem = [{
        "mes": r["mes"],
        "relogio": int(r["relogio"] or 0),
        "digitada": int(r["digitada"] or 0),
        "outros": int(r["outros"] or 0),
        "pct_digitada": round(100 * (r["digitada"] or 0) / r["total"], 1) if r["total"] else 0.0,
        "parcial": r["mes"] >= corrente,
    } for r in _q("""
        SELECT TO_CHAR(dtdigit,'YYYY-MM') mes, COUNT(*) total,
               SUM(CASE WHEN geradordigit='RL' THEN 1 ELSE 0 END) relogio,
               SUM(CASE WHEN geradordigit='DP' THEN 1 ELSE 0 END) digitada,
               SUM(CASE WHEN geradordigit NOT IN ('RL','DP')
                         OR geradordigit IS NULL THEN 1 ELSE 0 END) outros
          FROM globus729.frq_digitacaomovimento
         WHERE dtdigit >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:m)
         GROUP BY TO_CHAR(dtdigit,'YYYY-MM') ORDER BY 1""", p)]

    # ── marcação alterada à mão ─────────────────────────────────────────
    # DIA-PESSOA, não linha: `frq_movtomotdigit` grava uma linha por CAMPO
    # alterado, e contar linha dá o triplo. 1 em cada 4 dias tem ajuste, e
    # 99,5% deles usam o motivo "ESQUECIMENTO" — com 11 motivos disponíveis.
    ajustes = [{
        "mes": r["mes"],
        "dias_ajustados": int(r["ajustados"] or 0),
        "dias_total": int(r["total"] or 0),
        "pct": round(100 * (r["ajustados"] or 0) / r["total"], 1) if r["total"] else 0.0,
        "parcial": r["mes"] >= corrente,
    } for r in _q("""
        SELECT t.mes, t.total, NVL(a.ajustados,0) ajustados
          FROM (SELECT TO_CHAR(dtdigit,'YYYY-MM') mes,
                       COUNT(DISTINCT codintfunc || '|' || TO_CHAR(dtdigit,'YYYYMMDD')) total
                  FROM globus729.frq_digitacaomovimento
                 WHERE dtdigit >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:m)
                 GROUP BY TO_CHAR(dtdigit,'YYYY-MM')) t
          LEFT JOIN (SELECT TO_CHAR(dtdigit,'YYYY-MM') mes,
                            COUNT(DISTINCT codintfunc || '|' || TO_CHAR(dtdigit,'YYYYMMDD')) ajustados
                       FROM globus729.frq_movtomotdigit
                      WHERE dtdigit >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:m)
                      GROUP BY TO_CHAR(dtdigit,'YYYY-MM')) a ON a.mes = t.mes
         ORDER BY t.mes""", p)]

    motivos = [{"motivo": (r["motivo"] or "(sem motivo)").strip(), "n": int(r["n"] or 0)}
               for r in _q("""
        SELECT NVL(mo.descmotivo, TO_CHAR(m.codigomotivo)) motivo, COUNT(*) n
          FROM globus729.frq_movtomotdigit m
          LEFT JOIN globus729.frq_motivo_altera_frqfunc mo
                 ON mo.codigomotivo = m.codigomotivo
         WHERE m.dtdigit >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:m)
         GROUP BY NVL(mo.descmotivo, TO_CHAR(m.codigomotivo))
         ORDER BY 2 DESC""", p)]

    # ── absenteísmo, em DIA-PESSOA ──────────────────────────────────────
    absent = [{
        "mes": r["mes"],
        "faltas": int(r["faltas"] or 0),
        "atestados": int(r["atestados"] or 0),
        "trabalhados": int(r["trab"] or 0),
        "pct_falta": round(100 * (r["faltas"] or 0) / (r["trab"] + r["faltas"]), 1)
                     if (r["trab"] or 0) + (r["faltas"] or 0) else 0.0,
        # MARCA O MÊS EM CURSO. Sem isto o KPI de absenteísmo publicava
        # setembro — 311 dias trabalhados contra os 1.734 de agosto —, e a
        # tela dizia 8,5% onde o mês fechado deu 7,1%. Foi a renderização com
        # dado REAL que pegou: o dublê dos testes tinha o campo, o SQL não.
        "parcial": r["mes"] >= corrente,
    } for r in _q("""
        SELECT mes,
               SUM(CASE WHEN tipo='FALTA' THEN 1 ELSE 0 END) faltas,
               SUM(CASE WHEN tipo='ATESTADO' THEN 1 ELSE 0 END) atestados,
               SUM(CASE WHEN tipo='TRAB' THEN 1 ELSE 0 END) trab
          FROM (SELECT DISTINCT TO_CHAR(dtdigit,'YYYY-MM') mes, codintfunc, dtdigit,
                       CASE WHEN codocorr = 4 THEN 'FALTA'
                            WHEN codocorr = 8 THEN 'ATESTADO'
                            WHEN codocorr IN (1,13) THEN 'TRAB' ELSE 'X' END tipo
                  FROM globus729.frq_digitacaomovimento
                 WHERE dtdigit >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:m))
         GROUP BY mes ORDER BY mes""", p)]

    # ── defasagem entre o dia e a digitação ─────────────────────────────
    defas = _q("""SELECT ROUND(MEDIAN(TRUNC(dtdigitdigit)-TRUNC(dtdigit)),1) mediana,
                         ROUND(AVG(TRUNC(dtdigitdigit)-TRUNC(dtdigit)),1) media,
                         MAX(TRUNC(dtdigitdigit)-TRUNC(dtdigit)) maximo
                    FROM globus729.frq_digitacaomovimento
                   WHERE dtdigit >= ADD_MONTHS(TRUNC(SYSDATE,'MM'),-3)
                     AND dtdigitdigit IS NOT NULL""")[0]

    fr = frescor()
    # O ALARME MEDE MÊS FECHADO. O mês em curso não é "pouco preenchido": com a
    # importação manual do AFD, ele é INDETERMINADO — em 09/09/2026 tinha 423
    # movimentos contra os 2.897 de agosto. Um percentual sobre essa base vira
    # sorte, e alarme com base de sorte é ruído que ensina a ignorar o painel.
    fechados = [o for o in origem if not o["parcial"]]
    ult = fechados[-1] if fechados else {}
    base = [o["pct_digitada"] for o in fechados[:-3]] or [0.0]
    media_base = sum(base) / len(base)
    aj_fechados = [a for a in ajustes if not a["parcial"]]

    # ── os avisos ───────────────────────────────────────────────────────
    # Aviso tem TRÊS respostas: acusa, cala porque não há, ou diz que não sabe.
    # Nenhum deles conta tropeço acumulado — todos olham o estado AGORA.
    avisos = []
    if fr["dias_atraso"] > 2:
        avisos.append({
            "nivel": "alerta" if fr["dias_atraso"] > 5 else "atencao",
            "titulo": "A apuração não enxerga os últimos %d dias" % fr["dias_atraso"],
            "detalhe": ("Último dia com marcação: %s. A importação do AFD é manual e "
                        "a última rodou em %s." % (fr["ultimo_dia"], fr["ultima_coleta"] or "—")),
        })
    if ult and ult["pct_digitada"] > max(8.0, media_base * 2):
        avisos.append({
            "nivel": "atencao",
            "titulo": "Batida digitada pelo DP em %.1f%% em %s" % (ult["pct_digitada"], ult["mes"]),
            "detalhe": ("A média dos meses fechados anteriores é %.1f%%. Marcação que não "
                        "veio do relógio depende de alguém lembrar." % media_base),
        })
    if aj_fechados and aj_fechados[-1]["pct"] >= 20:
        a = aj_fechados[-1]
        avisos.append({
            "nivel": "atencao",
            "titulo": "%.0f%% dos dias tiveram marcação ajustada à mão em %s" % (a["pct"], a["mes"]),
            "detalhe": "Um em cada %.0f dias-pessoa. A Portaria 671 exige o registro do ajuste, "
                       "e ele existe — o que o número diz é sobre o processo, não sobre a norma."
                       % (100 / a["pct"] if a["pct"] else 0),
        })

    return {
        "origem": origem,
        "ajustes": ajustes,
        "motivos": motivos,
        "absenteismo": absent,
        "defasagem": {
            "mediana_dias": _f(defas["mediana"]),
            "media_dias": _f(defas["media"]),
            "maximo_dias": int(defas["maximo"] or 0),
        },
        "avisos": avisos,
        "publico": publico(),
        "frescor": fr,
        "meses": meses,
        "fonte": ("GLOBUS · FRQ_DIGITACAOMOVIMENTO + FRQ_MOVTOMOTDIGIT · "
                  "dia-pessoa · leitura"),
    }


# ============================================================================
# Snapshot do Copiloto — ESCALARES, sem PII
# ============================================================================
def _escalares_do_dia() -> dict:
    """Os numeros do dia de hoje, do Ponto Certificado — ou nada.

    Falha aqui NAO pode derrubar o snapshot: o modulo do fornecedor pode nem
    estar instalado (tabela ausente devolve lista vazia por desenho), e o
    Copiloto sem um bloco e melhor que um chat que nao abre.
    """
    try:
        from api.pontocertificado import painel
        d = painel.do_dia("hoje")
        k = d.get("kpis", {})
        return {
            "hoje_pessoas_que_bateram": k.get("pessoas"),
            "hoje_batidas": k.get("batidas"),
            "hoje_batidas_fora_de_cerca": k.get("fora"),
            "hoje_batidas_sem_gps": k.get("sem_coordenada"),
            "hoje_primeira_batida": k.get("primeira"),
            "hoje_ultima_batida": k.get("ultima"),
            **_escalares_de_ontem(),
        }
    except Exception:  # noqa: BLE001
        return {}



#: Janela para descobrir se a pessoa TRABALHA naquele dia da semana: 28 dias
#: dão 4 ocorrências do mesmo dia (às vezes 5), e a exigência de 3 tolera uma
#: falta ou folga isolada sem deixar de reconhecer o padrão.
AUSENTE_JANELA_DIAS = 28
AUSENTE_MIN_DIAS = 3

#: As ocorrências que significam "registrou presença". É de propósito que
#: HOME OFFICE (23) e VIAGEM A TRAB (25) fiquem FORA: quem está em casa ou na
#: estrada trabalha e não bate no relógio da unidade, e contá-los como
#: esperados produziria ausência todo dia para as mesmas pessoas — o alarme
#: que se aprende a ignorar. Medido em 10/09/2026: com ou sem eles a lista do
#: dia é a mesma, então o conjunto estreito não custa nada e não mente.
OCOR_PRESENCA = (1, 13)

#: A partir de que fração de ausentes o dia deixa de ser sobre pessoas. Meio
#: quadro fora no mesmo dia é feriado, parada ou coleta que não rodou — nunca
#: metade da casa faltando ao trabalho.
ATIPICO_FRACAO = 0.5


def ausentes_do_dia(dia: str) -> dict:
    """Quem tinha de aparecer no relógio naquele dia e NÃO apareceu.

    SÓ PARA DIA FECHADO, e a recusa é explícita: às 8h da manhã quem entra às
    13h ainda não bateu, e uma lista de "ausentes" montada com o dia em curso
    seria uma lista de gente no horário.

    O DENOMINADOR É O PROBLEMA INTEIRO
    ==================================
    "Não bateu" só vira informação depois de responder "quem tinha de bater?".
    Sobre os 90 ativos com ponto, a resposta muda com o dia: num sábado 61
    pessoas aparecem como COMPENSADO no próprio ERP — não trabalham, e listá-las
    como ausentes seria acusar a escala. Então o esperado vem de EVIDÊNCIA, em
    dois modos, e a tela DIZ qual deles respondeu:

    `erp` — o Globus já importou o dia (o AFD entra à mão, com mediana de 3
      dias de atraso). Aí o esperado é quem o PRÓPRIO ERP registra como
      presente naquele dia, e a lista vira outra coisa: divergência entre o que
      o ERP afirma e o que o relógio viu.

    `padrao` — o Globus ainda não importou. O esperado é quem trabalhou em pelo
      menos 3 das últimas 4 ocorrências do MESMO dia da semana. É inferência,
      e por isso cada linha carrega quantos dias ela viu.

    QUEM SAI DA LISTA, E POR QUE
    ============================
    Férias saem pelo gozo em `vw_ferias` (10 pessoas em 10/09), afastado e
    desligado saem por `situacaofunc`. O que SOBRA não é falta: pode ser
    atestado que ninguém lançou ainda, folga combinada ou esquecimento de bater.
    A tela nomeia isso como "sem batida", nunca como falta — quem diz que foi
    falta é o RH, com a lista na mão.

    Medido em 10/09/2026 (quinta): 79 esperados pelo padrão, 82 bateram,
    10 em férias, e a lista final tem QUATRO nomes. Uma lista de quatro se
    confere na mesma manhã; a mesma pergunta pelo ERP só teria resposta cinco
    dias depois.
    """
    import re
    from datetime import date as _date

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", dia or ""):
        raise ValueError("dia inválido")
    if dia >= _date.today().isoformat():
        return {"dia": dia, "em_curso": True, "modo": None, "ausentes": [],
                "motivo": "O dia ainda está em curso — quem entra à tarde "
                          "ainda não bateu. A lista só fecha amanhã."}

    p = {"d": dia, "emp": EMPRESA}
    codes = ",".join(str(c) for c in OCOR_PRESENCA)

    # O ERP conhece este dia? É a pergunta que escolhe o modo, e ela é barata.
    tem = _q("""SELECT COUNT(*) n FROM frq_digitacaomovimento
                 WHERE dtdigit = TO_DATE(:d,'YYYY-MM-DD')""", {"d": dia})
    erp_conhece = bool(tem and int(tem[0]["n"] or 0) > 0)

    if erp_conhece:
        modo = "erp"
        esperados = _q(f"""
            SELECT vf.chapafunc chapa, vf.nomefunc nome, vf.descsecao filial,
                   vf.descfuncao funcao, NULL vistos
              FROM frq_digitacaomovimento m
              JOIN vw_funcionarios vf ON vf.codintfunc = m.codintfunc
                                     AND vf.codigoempresa = :emp
                                     AND vf.temfrequenfunc = 'S'
             WHERE m.dtdigit = TO_DATE(:d,'YYYY-MM-DD')
               AND m.codocorr IN ({codes})""", p)
    else:
        modo = "padrao"
        esperados = _q(f"""
            SELECT vf.chapafunc chapa, MIN(vf.nomefunc) nome,
                   MIN(vf.descsecao) filial, MIN(vf.descfuncao) funcao,
                   COUNT(*) vistos
              FROM frq_digitacaomovimento m
              JOIN vw_funcionarios vf ON vf.codintfunc = m.codintfunc
                                     AND vf.codigoempresa = :emp
                                     AND vf.temfrequenfunc = 'S'
                                     AND vf.situacaofunc = 'A'
             WHERE m.codocorr IN ({codes})
               AND TO_CHAR(m.dtdigit,'D') = TO_CHAR(TO_DATE(:d,'YYYY-MM-DD'),'D')
               AND m.dtdigit >= TO_DATE(:d,'YYYY-MM-DD') - :janela
               AND m.dtdigit <  TO_DATE(:d,'YYYY-MM-DD')
             GROUP BY vf.chapafunc
            HAVING COUNT(*) >= :minimo""",
            {**p, "janela": AUSENTE_JANELA_DIAS, "minimo": AUSENTE_MIN_DIAS})

    # Férias pelo GOZO, não pelo período aquisitivo: o aquisitivo diz que ela
    # tem direito, o gozo diz que ela está fora hoje.
    ferias = {str(r["chapa"] or "").strip() for r in _q("""
        SELECT vf.chapafunc chapa FROM vw_ferias fe
          JOIN vw_funcionarios vf ON vf.codintfunc = fe.codintfunc
                                 AND vf.codigoempresa = :emp
         WHERE TO_DATE(:d,'YYYY-MM-DD') BETWEEN fe.gozoinifer AND fe.gozofinfer""", p)}

    # O que o ERP registra para CADA um no dia — é o que transforma "sem
    # batida" em resposta quando ele já importou.
    registro = {}
    if erp_conhece:
        registro = {str(r["chapa"] or "").strip(): r["ocorrencia"] for r in _q("""
            SELECT vf.chapafunc chapa, o.descocorr ocorrencia
              FROM frq_digitacaomovimento m
              JOIN frq_ocorrencia o ON o.codocorr = m.codocorr
              JOIN vw_funcionarios vf ON vf.codintfunc = m.codintfunc
                                     AND vf.codigoempresa = :emp
             WHERE m.dtdigit = TO_DATE(:d,'YYYY-MM-DD')""", p)}

    from api.pontocertificado import painel as _pc
    bateram = _pc.matriculas_do_dia(dia)

    ausentes = []
    for r in esperados:
        chapa = str(r["chapa"] or "").strip()
        if chapa in bateram or chapa in ferias:
            continue
        ausentes.append({
            "chapa": chapa, "nome": r["nome"],
            "filial": r["filial"] or "—", "funcao": r["funcao"] or "—",
            "vistos": int(r["vistos"]) if r["vistos"] is not None else None,
            "registro_erp": registro.get(chapa),
        })
    ausentes.sort(key=lambda x: (x["filial"], x["nome"] or ""))

    ult = _q("SELECT MAX(dtdigit) d FROM frq_digitacaomovimento")
    erp_ate = ult[0]["d"].date().isoformat() if ult and ult[0]["d"] else None

    # QUANDO QUASE TODO MUNDO FALTA, QUEM ERROU FOI A PREMISSA.
    # Metade do quadro ausente no mesmo dia não é ausência: é feriado, parada
    # coletiva ou a própria coleta que não rodou. Nomear 79 pessoas nesse dia
    # seria acusar a casa inteira de faltar — e a lista longa é justamente a
    # que ninguém confere. O corte é declarado (não é heurística escondida) e
    # a tela DIZ o que aconteceu em vez de listar.
    atipico = bool(esperados) and len(ausentes) >= len(esperados) * ATIPICO_FRACAO

    return {
        "dia": dia, "em_curso": False, "modo": modo,
        "atipico": atipico,
        "esperados": len(esperados), "bateram": len(bateram),
        "ferias": len(ferias), "ausentes": ausentes,
        "erp_ate": erp_ate,
        "janela_dias": AUSENTE_JANELA_DIAS, "minimo_dias": AUSENTE_MIN_DIAS,
        "fonte": ("GLOBUS · FRQ_DIGITACAOMOVIMENTO + VW_FERIAS (quem tinha de "
                  "aparecer) × CÓRTEX · pc_marcacao (quem apareceu)"),
    }

def _escalares_de_ontem() -> dict:
    """Quantos não bateram ONTEM — o dia fechado, que é o que tem resposta.

    Escalar puro: quantos, nunca quem. O snapshot vai para modelo externo
    quando o Ollama local não responde, e é isso — não um filtro esperto — que
    permite o chat cair para fora sem levar ninguém junto.
    """
    from datetime import date as _d, timedelta as _td
    try:
        a = ausentes_do_dia((_d.today() - _td(days=1)).isoformat())
        return {
            "ontem_sem_batida": len(a.get("ausentes") or []),
            "ontem_esperados": a.get("esperados"),
            "ontem_dia_atipico": bool(a.get("atipico")),
        }
    except Exception:  # noqa: BLE001
        return {}


def resumo_escalares() -> dict:
    """O que o Copiloto pode saber sobre frequência.

    Só escalar: nenhum nome, nenhuma chapa, nenhuma filial. É isso — e não um
    filtro esperto — que deixa o chat cair no modelo externo sem vazar quem é
    quem. Não dispara coleta: tudo aqui vem do mesmo cache das telas.
    """
    try:
        bh = get_banco_horas()
        b = get_batidas(meses=6)
        k = bh.get("kpis", {})
        d = bh.get("destino_he", {})
        return {
            "competencia": bh.get("competencia"),
            "pessoas_com_ponto": bh.get("publico", {}).get("com_frequencia"),
            # o saldo do EXTRATO no fim da competência (anterior + movimento)
            "banco_horas_credor_h": k.get("credor_h"),
            "banco_horas_credor_rs_estimado": k.get("custo_credor"),
            "banco_horas_pessoas_credoras": k.get("credores"),
            "banco_horas_saldo_liquido_h": k.get("liquido_h"),
            "banco_horas_levado_mes_seguinte_h": k.get("levado_h"),
            "he_pct_paga_em_dinheiro": d.get("pct_em_dinheiro"),
            "batidas_dias_de_atraso": b.get("frescor", {}).get("dias_atraso"),
            "batidas_pct_digitada_ultimo_mes": (b.get("origem") or [{}])[-1].get("pct_digitada"),
            "avisos_abertos": len(b.get("avisos") or []),
            # O DIA, que o ERP nao sabe: o AFD dele entra por importacao
            # manual e atrasa dias. Sai do banco da casa (`pc_marcacao`), sem
            # tocar o fornecedor — snapshot nao dispara coleta. Escalar puro:
            # quantos, nunca quem.
            **_escalares_do_dia(),
        }
    except Exception:  # noqa: BLE001
        # Snapshot NUNCA derruba o Copiloto: a ausência de um bloco é melhor
        # que um chat que não abre.
        return {}
