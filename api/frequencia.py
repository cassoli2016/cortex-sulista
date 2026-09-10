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

O REGIME É BANCO DE HORAS — E A MEDIÇÃO DIZ QUE ELE VAZA
=========================================================
12 meses fechados (set/2025 a ago/2026), só o público com frequência:

    hora extra PAGA em dinheiro ....... 11.042,4 h   R$ 222.341,95
    hora extra creditada no banco .....  8.147,9 h
    compensada (débito do banco) ......  5.450,5 h

58% da hora extra do administrativo sai em dinheiro num regime que deveria
compensar em folga; e do que entra no banco, só dois terços voltam como folga.
A diferença é o que empilha o saldo — **6.065 h credoras em 57 pessoas**, que
cresceram 2,6× em 14 meses. É esse o número que esta tela existe para mostrar,
e ele não aparecia em lugar nenhum do CÓRTEX.

`FRQ_BANCOHORAS_PARAMETRO` tem `meses_compensar = 0` e `pgsaldomes = 'S'`: não
há prazo de compensação configurado. A regra vive fora do sistema.

O SALDO REGISTRADO NÃO É O PASSIVO — E ISSO CUSTOU UM NÚMERO ERRADO EM TELA
===========================================================================
A casa FECHA o semestre e paga: há pico de `H.E 50%` em ago/2025 (2.233 h),
fev/2026 (1.003 h) e ago/2026 (1.352 h) — de seis em seis meses, contra ~400 h
dos meses comuns. **R$ 105.533 em 5.256,7 h nos três fechamentos.**

Só que o pagamento **não baixa o saldo** do `FRQ_BANCOHORAS`. Medido nos três:

    jul/2025 5.177,6 h -> ago/2025 5.219,6 h   pagou 2.233 h e o saldo SUBIU
    jan/2026 5.417,8 h -> fev/2026 5.273,3 h   pagou 1.003 h e caiu 144 h
    jul/2026 5.915,2 h -> ago/2026 6.160,9 h   pagou 1.352 h e o saldo SUBIU

O evento que daria a baixa (`DEBITO BANCO DE HORAS`, 1016) movimentou 86,4 h
para 7 pessoas em agosto. O resto saiu como hora extra comum. E 6 das 44
pessoas que receberam no fechamento levaram MAIS horas do que o próprio saldo
registrado — não há relação entre os dois números.

**Então `saldonacompet` é um ACUMULADOR que ninguém zera, não um saldo devedor.**
Publicá-lo como "passivo" foi erro meu em 09/09/2026: a tela subiu dizendo
R$ 123 mil de dívida sobre horas que em boa parte já tinham sido pagas. O
módulo agora chama o número pelo que ele é e mostra o outro lado ao lado,
porque duas contabilidades que não conversam só se leem juntas.

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

SALDO PARADO NÃO É OPERAÇÃO, É CADASTRO
=======================================
Em ago/2026 uma pessoa afastada aparece com **−823,5 h** — 103 dias devedores —
e o saldo está CONGELADO desde ago/2025: crédito 0, débito 0, mês após mês.
Isso não é jornada, é registro que ninguém fechou. Pela regra da casa
(`|desvio| > 1 ciclo` do próprio indicador = cadastro furado), ele sai dos KPIs
e vai para a lista `cadastro`, com a evidência — nunca some, e nunca contamina
o passivo.
"""
from __future__ import annotations

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

# SALDO PARADO: o que separa registro esquecido de jornada de verdade não é o
# tamanho do saldo — é o quanto ele SE MOVE. Medido em ago/2026 sobre as 106
# pessoas com saldo, a razão `movimento de 6 meses ÷ |saldo|` tem degrau claro:
# mediana 0,67, p25 0,029, e 27 pessoas abaixo de 0,10. Quem trabalha move o
# saldo; quem está parado carrega um número que ninguém toca há meses.
#
# Os dois cortes juntos (razão < 0,10 E |saldo| >= 100 h) isolam 2 casos em
# ago/2026: um afastamento com −823,5 h congeladas desde ago/2025 e um crédito
# de 322,4 h com 9,2 h de movimento em seis meses. Sem isso, o primeiro sozinho
# desloca o saldo líquido da casa em 23% — para o lado errado, e calado.
CADASTRO_MESES_PARADO = 6
CADASTRO_HORAS_MIN = 100.0
CADASTRO_RAZAO_MAX = 0.10


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
# Banco de horas — o passivo
# ============================================================================
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
                "faixas": [], "serie": [], "cadastro": [],
                "fonte": "GLOBUS · FRQ_BANCOHORAS (sem dado)"}
    p = {"emp": EMPRESA, "comp": comp}

    # ── as pessoas com saldo ────────────────────────────────────────────
    # `b6` é o saldo de 6 meses antes, pela MESMA chave: é ele que separa
    # "acumulou este mês" de "vem crescendo desde sempre".
    linhas = _q("""
        SELECT vf.chapafunc chapa, vf.nomefunc nome,
               vf.descsecao filial, vf.descfuncao funcao, vf.situacaofunc situacao,
               b.saldonacompet saldo, b.credito credito, b.debito debito,
               vf.salbase salbase, b6.saldonacompet saldo_6m,
               (SELECT NVL(SUM(NVL(h.credito,0)) + SUM(ABS(NVL(h.debito,0))),0)
                  FROM globus729.frq_bancohoras h
                 WHERE h.codintfunc = b.codintfunc
                   AND h.competencia > ADD_MONTHS(TO_DATE(:comp,'YYYY-MM'), -:meses)
                   AND h.competencia <= TO_DATE(:comp,'YYYY-MM')) movimento
          FROM globus729.frq_bancohoras b
          JOIN vw_funcionarios vf ON vf.codintfunc = b.codintfunc
                                 AND vf.codigoempresa = :emp
          LEFT JOIN globus729.frq_bancohoras b6
                 ON b6.codintfunc = b.codintfunc
                AND b6.competencia = ADD_MONTHS(TO_DATE(:comp,'YYYY-MM'),-6)
         WHERE b.competencia = TO_DATE(:comp,'YYYY-MM')
           AND NVL(b.saldonacompet,0) <> 0
         ORDER BY b.saldonacompet DESC""",
        dict(p, meses=CADASTRO_MESES_PARADO))

    pessoas, cadastro = [], []
    for r in linhas:
        saldo = float(r["saldo"] or 0)
        s6 = r["saldo_6m"]
        mov = float(r["movimento"] or 0)
        razao = (mov / abs(saldo)) if saldo else 0.0
        item = {
            "chapa": str(r["chapa"] or "").strip(),
            "nome": r["nome"], "filial": r["filial"] or "—",
            "funcao": r["funcao"] or "—", "situacao": r["situacao"],
            "horas": round(saldo, 1),
            # Custo só faz sentido para o saldo CREDOR: é o que a empresa deve.
            # A 50% e sobre salbase/220 — a alíquota real depende do acordo, e
            # a tela diz a premissa em vez de esconder num número redondo.
            "custo": _f(saldo * (float(r["salbase"] or 0) / 220) * 1.5) if saldo > 0 else 0.0,
            "horas_6m": round(float(s6), 1) if s6 is not None else None,
            "variacao_6m": round(saldo - float(s6), 1) if s6 is not None else None,
            "movimento_6m": round(mov, 1),
        }
        # Saldo grande que quase não se move: registro parado, não jornada. Sai
        # dos KPIs — se ficasse, um único caso de −823 h deslocaria o saldo
        # líquido da casa em 23%, para o lado errado e calado.
        if abs(saldo) >= CADASTRO_HORAS_MIN and razao < CADASTRO_RAZAO_MAX:
            item["motivo"] = (
                "saldo de %.1f h com apenas %.1f h de movimento em %d meses — "
                "conferir o cadastro" % (saldo, mov, CADASTRO_MESES_PARADO))
            cadastro.append(item)
        else:
            pessoas.append(item)

    cred = [x for x in pessoas if x["horas"] > 0]
    dev = [x for x in pessoas if x["horas"] < 0]
    subindo = [x for x in cred if (x["variacao_6m"] or 0) > 0]

    faixas_def = [("1 · acima de 300 h", 300, 1e9), ("2 · 200 a 300 h", 200, 300),
                  ("3 · 100 a 200 h", 100, 200), ("4 · 40 a 100 h", 40, 100),
                  ("5 · até 40 h", 0, 40)]
    faixas = []
    for rot, lo, hi in faixas_def:
        g = [x for x in cred if lo <= x["horas"] < hi]
        if g:
            faixas.append({"faixa": rot, "pessoas": len(g),
                           "horas": round(sum(x["horas"] for x in g), 1),
                           "custo": _f(sum(x["custo"] for x in g))})

    # ── a série: o passivo ao longo do tempo ────────────────────────────
    # O mês corrente ENTRA, marcado `parcial`: escondê-lo faria a série parecer
    # terminada num mês que ainda não fechou.
    serie = [{
        "comp": r["comp"],
        "credor": round(float(r["credor"] or 0), 1),
        "devedor": round(float(r["devedor"] or 0), 1),
        "liquido": round(float(r["liquido"] or 0), 1),
        "pessoas": int(r["pessoas"] or 0),
        "parcial": bool(r["comp"] and fechada and r["comp"] > fechada),
    } for r in _q("""
        SELECT TO_CHAR(competencia,'YYYY-MM') comp,
               SUM(CASE WHEN saldonacompet > 0 THEN saldonacompet ELSE 0 END) credor,
               SUM(CASE WHEN saldonacompet < 0 THEN saldonacompet ELSE 0 END) devedor,
               SUM(NVL(saldonacompet,0)) liquido,
               COUNT(DISTINCT codintfunc) pessoas
          FROM globus729.frq_bancohoras
         WHERE competencia >= ADD_MONTHS(TRUNC(SYSDATE,'MM'),-14)
         GROUP BY TO_CHAR(competencia,'YYYY-MM')
         ORDER BY 1""")]

    # ── para onde vai a hora extra do administrativo ────────────────────
    destino = _destino_da_he()

    return {
        "competencia": comp,
        "competencias": comps,
        "competencia_fechada": fechada,
        "kpis": {
            "passivo_horas": round(sum(x["horas"] for x in cred), 1),
            "passivo_custo": _f(sum(x["custo"] for x in cred)),
            "pessoas_credoras": len(cred),
            "pessoas_devedoras": len(dev),
            "horas_devedoras": round(sum(x["horas"] for x in dev), 1),
            "saldo_liquido": round(sum(x["horas"] for x in pessoas), 1),
            "credoras_subindo": len(subindo),
            "maior_saldo": round(max([x["horas"] for x in cred], default=0.0), 1),
            "em_cadastro": len(cadastro),
        },
        "pessoas": pessoas,
        "cadastro": cadastro,
        "faixas": faixas,
        "serie": serie,
        "destino_he": destino,
        # AS DUAS CONTABILIDADES, sempre juntas. O saldo sozinho parece dívida;
        # ao lado do que foi pago, vira o que é.
        "confronto": confronto(),
        "publico": publico(),
        "frescor": frescor(),
        "premissa_custo": "saldo credor × (salário base ÷ 220) × 1,5",
        # A RESSALVA VIAJA COM O NÚMERO. Sem ela o valor se lê como dívida — e
        # ele não é: o pagamento de hora extra não baixa este saldo.
        "ressalva_custo": ("Valor do saldo REGISTRADO, não do que se deve: os "
                           "pagamentos de hora extra não baixam este saldo no ERP."),
        "fonte": ("GLOBUS · FRQ_BANCOHORAS × VW_FUNCIONARIOS · "
                  "competência fechada · leitura"),
    }


@cached(ttl=900, velha_ate=7200)
def confronto(meses: int = 24) -> dict:
    """As DUAS contabilidades na mesma linha do tempo: o que se paga × o saldo.

    NÃO CLASSIFICA MÊS COMO "FECHAMENTO", e a tentativa fica registrada porque
    quase virou rótulo: um corte por múltiplo da mediana separava ago/2025,
    fev/2026 e ago/2026 — mas levava out/2025 junto, que não é fechamento. A
    régua não separava os dois grupos, e heurística que não separa não vira
    etiqueta: vira número errado com cara de certo.

    O que a tela mostra é o FATO, que dispensa classificação: nos meses em que
    a casa paga várias vezes o normal de hora extra, o saldo do banco NÃO cai.
    Quem olha a série vê isso sem que ninguém precise rotular nada.
    """
    meses = max(12, min(int(meses or 24), 48))
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

    saldos = {r["comp"]: r for r in _q("""
        SELECT TO_CHAR(competencia,'YYYY-MM') comp,
               ROUND(SUM(CASE WHEN saldonacompet > 0 THEN saldonacompet ELSE 0 END),1) saldo,
               ROUND(SUM(NVL(debito,0)),1) debito
          FROM globus729.frq_bancohoras
         WHERE competencia >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:m)
           AND competencia <  TRUNC(SYSDATE,'MM')
         GROUP BY TO_CHAR(competencia,'YYYY-MM')""", {"m": meses})}

    #: O evento que DARIA a baixa no banco. Ele existe e quase não é usado —
    #: 86,4 h para 7 pessoas no maior mês de pagamento do ano.
    baixas = {r["comp"]: float(r["horas"] or 0) for r in _q("""
        SELECT TO_CHAR(competficha,'YYYY-MM') comp, ROUND(SUM(referencia),1) horas
          FROM flp_fichaeventos
         WHERE codevento = 1016
           AND competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -:m)
         GROUP BY TO_CHAR(competficha,'YYYY-MM')""", {"m": meses})}

    serie, anterior = [], None
    for comp in sorted(set(pagos) | set(saldos)):
        pg, sd = pagos.get(comp, {}), saldos.get(comp, {})
        saldo = float(sd.get("saldo") or 0) if sd else None
        serie.append({
            "comp": comp,
            "pago_h": float(pg.get("horas") or 0),
            "pago_rs": _f(pg.get("reais")),
            "pessoas": int(pg.get("pessoas") or 0),
            "saldo": saldo,
            "variacao": round(saldo - anterior, 1)
                        if (saldo is not None and anterior is not None) else None,
            "debito_banco": float(sd.get("debito") or 0) if sd else None,
            "baixa_pela_folha": baixas.get(comp, 0.0),
        })
        if saldo is not None:
            anterior = saldo

    pago_total = round(sum(x["pago_h"] for x in serie), 1)
    baixa_total = round(sum(x["baixa_pela_folha"] for x in serie), 1)
    com_saldo = [x for x in serie if x["saldo"] is not None]
    return {
        "serie": serie,
        "pago_h": pago_total,
        "pago_rs": _f(sum(x["pago_rs"] for x in serie)),
        "baixa_pela_folha_h": baixa_total,
        # A frase inteira em um número: pagou-se isso tudo e o saldo andou
        # para o outro lado.
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
    bh = _q("""SELECT NVL(SUM(credito),0) cred, NVL(SUM(debito),0) deb
                 FROM globus729.frq_bancohoras
                WHERE competencia >= ADD_MONTHS(TRUNC(SYSDATE,'MM'),-12)
                  AND competencia <  TRUNC(SYSDATE,'MM')""")[0]
    pago_h = round(float(pago["h"] or 0), 1)
    cred_h = round(float(bh["cred"] or 0), 1)
    total = pago_h + cred_h
    return {
        "pago_horas": pago_h,
        "pago_reais": _f(pago["rs"]),
        "creditado_horas": cred_h,
        "compensado_horas": round(float(bh["deb"] or 0), 1),
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
            "banco_horas_passivo_h": k.get("passivo_horas"),
            "banco_horas_passivo_rs": k.get("passivo_custo"),
            "banco_horas_pessoas_credoras": k.get("pessoas_credoras"),
            "banco_horas_saldo_liquido_h": k.get("saldo_liquido"),
            "he_pct_paga_em_dinheiro": d.get("pct_em_dinheiro"),
            "batidas_dias_de_atraso": b.get("frescor", {}).get("dias_atraso"),
            "batidas_pct_digitada_ultimo_mes": (b.get("origem") or [{}])[-1].get("pct_digitada"),
            "avisos_abertos": len(b.get("avisos") or []),
        }
    except Exception:  # noqa: BLE001
        # Snapshot NUNCA derruba o Copiloto: a ausência de um bloco é melhor
        # que um chat que não abre.
        return {}
