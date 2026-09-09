"""Engenharia de caixa — quanto antecipar, quando, de quem, e a que custo.

A casa já tinha DUAS respostas para "como está o caixa", e elas se
contradiziam sem que nenhuma estivesse errada:

  `projecao.py`     projeta 12 meses com o lançado MAIS o provisionado, e não
                    antecipa nada. Em 09/09/2026 ela desenhava o saldo indo a
                    -R$ 11,1 milhões em ago/27.
  `get_antecipacao` (tela `antec`) roda dia a dia, antecipa de verdade — e
                    enxerga só o LANÇADO, que o próprio `projecao` mediu ser
                    ficção a partir do segundo mês. Ela respondia "está tudo
                    coberto, nenhum dia descoberto em 180 dias".

As duas estavam certas dentro da própria premissa, e por isso a leitura ficava
impossível: a tela do Fluxo Consolidado chegava a mandar o usuário para OUTRA
tela para dimensionar a operação. Quem precisa decidir "quanto eu antecipo
este mês" não tinha onde ler o número.

Este módulo é a junção: roda o motor de antecipação POR CIMA do fluxo projetado
de 12 meses. As quatro decisões que o fazem ser engenharia e não aritmética:

**1. O PISO É MÓVEL, e sai do próprio fluxo.**
Piso fixo envelhece: a mesma R$ 1 milhão que é folgada num mês de R$ 9 mi de
saída é apertada num de R$ 13 mi. O piso são N dias da saída DAQUELE mês (5
por decisão de quem opera, 09/09/2026, com a saída média medida em R$ 12,2
mi/mês ≈ R$ 407 mil/dia). `projecao.montar()` usa piso ZERO de propósito, e
continua usando: lá a pergunta é "quanto falta para não furar"; aqui é "quanto
antecipar para operar". São perguntas diferentes e respostas diferentes.

**2. A PILHA TEM DUAS METADES COM NATUREZAS DE PROVA DIFERENTES**, e o plano
some se uma delas for esquecida. O recebível LANÇADO de cliente com convênio
acaba em dez/26 (R$ 5,69 mi medidos em 09/09/2026 pelo `ERP_SQL` de
`antecipacoes.elegiveis`, que é a fonte que este módulo usa) — só olhando para ele, o
plano diria "descoberto total a partir de jan/27", o que é falso: a empresa
continua faturando. A outra metade é a fatia elegível do que ainda vai ser
faturado, e ela é grande — 49,8% do faturamento (mediana de 6 meses; 43,4% na
média de 12 e SUBINDO: 54,7% em ago/26). O split vem pronto de
`projecao.projetar_entradas`, que já devolve `a_faturar` como o que EXCEDE o
lançado; é por isso que as duas metades não se sobrepõem.

**3. O DESÁGIO SE PAGA POR DENTRO, então o saque é BRUTO.**
Para o caixa receber R$ 100 mil a 1,17% a.m. em 60 dias é preciso sacar
100.000 / (1 − 0,0234) = R$ 102.394. Somar o custo por fora subestima o
consumo da pilha justamente no mês em que ela é escassa, que é o mês em que o
número importa.

**4. ANTECIPAR É SAQUE, e o saque tira do mês de origem.**
Antecipar recebível de novembro resolve setembro e ESVAZIA novembro. É esse
encadeamento que transforma "quanto antecipar" de um número numa sequência, e
é ele que separa, sem opinião, o descasamento de prazo (a antecipação resolve)
do rombo estrutural (não resolve, e insistir só adianta o problema com juros).

O que este módulo NÃO faz, de propósito: não enxerga buraco DENTRO do mês. A
granularidade é o mês, e um mês que fecha no piso pode furar no dia 20. Quem
responde isso é o motor diário da tela `antec`, e é por isso que ele continua
existindo — a janela curta é dele.
"""

from __future__ import annotations

import logging
import statistics
from datetime import date, timedelta

from .. import db, pglocal
from ..queries import VELHA_ATE, cached
from ..antecipacoes import elegiveis as eleg_mod
from ..antecipacoes import registro as antec_reg
from . import projecao as proj

log = logging.getLogger(__name__)

# Piso de caixa em DIAS de saída do próprio mês. Decisão de quem opera,
# 09/09/2026.
PISO_DIAS = 5

# Quantos meses de história entram na mediana da fatia elegível. Seis, o mesmo
# `MESES_NIVEL` da projeção — duas janelas diferentes para medir a mesma
# empresa dariam dois retratos dela.
MESES_SHARE = 6

# Taxa de último recurso, em % ao mês, quando o portal não tem medição nenhuma
# na janela. É DELIBERADAMENTE pessimista: um plano barato demais por falta de
# dado é pior que um caro demais, porque o primeiro se executa e o segundo se
# questiona.
TAXA_FALLBACK = 2.0


# ============================================================================
# Parte PURA — recebe listas, devolve o plano. É o que o teste exercita.
# ============================================================================

def piso_por_mes(linhas: list[dict], dias: int = PISO_DIAS) -> dict[str, float]:
    """N dias da saída DAQUELE mês. Móvel de propósito — ver o cabeçalho.

    O divisor é 30 e não o número real de dias do mês: a saída projetada é
    mensal, e a diferença entre 28 e 31 dias fica muito abaixo do erro do
    próprio modelo. Fingir precisão de calendário aqui seria precisão
    inventada.
    """
    return {l["mes"]: round(float(l["saidas"]) / 30.0 * dias, 2) for l in linhas}


def pilha_por_mes(linhas: list[dict], eleg_lancado: dict[str, float],
                  share: float) -> dict[str, dict]:
    """O antecipável de cada mês, nas suas duas metades.

    `lancado` é FATO: fatura emitida, vencimento conhecido, cliente com
    convênio. `futuro` é MODELO: a fatia elegível do que ainda vai ser faturado
    para vencer naquele mês. Elas não se sobrepõem porque
    `projecao.projetar_entradas` já devolve `a_faturar` como o que EXCEDE o
    lançado.

    As duas voltam separadas até o fim da conta, e a tela mostra as duas: um
    plano que só fecha com faturamento futuro tem risco diferente de um que usa
    nota já emitida, e quem decide precisa saber qual dos dois está lendo.
    """
    out: dict[str, dict] = {}
    for l in linhas:
        lanc = round(float(eleg_lancado.get(l["mes"], 0.0)), 2)
        fut = round(max(0.0, float(l.get("a_faturar") or 0.0)) * float(share), 2)
        out[l["mes"]] = {"lancado": lanc, "futuro": fut,
                         "total": round(lanc + fut, 2)}
    return out


def _prazo_dias(mes_oper: str, mes_origem: str, hoje: date) -> int:
    """Dias entre a operação e o vencimento que ela consome.

    A operação acontece no MEIO do mês (dia 15) e o título vence no meio do mês
    de origem — exceto no mês corrente, em que a operação é HOJE: quem lê a
    tela hoje vai ao banco hoje, e cobrar 15 dias a mais de deságio de uma
    operação que já poderia estar feita encareceria o plano no papel.
    """
    ini = (hoje if mes_oper == f"{hoje.year:04d}-{hoje.month:02d}"
           else proj._primeiro_dia(mes_oper) + timedelta(days=14))
    fim = proj._primeiro_dia(mes_origem) + timedelta(days=14)
    return max(1, (fim - ini).days)


def meses_de_cauda(linhas: list[dict], n: int = 3) -> list[str]:
    """Os meses logo DEPOIS do horizonte, que existem só como fonte de saque.

    Sem eles o plano mente na borda. O último mês da janela não tem nenhum mês
    seguinte de onde antecipar, então ele aparece descoberto por CONSTRUÇÃO —
    e o penúltimo, quase. Medido em 09/09/2026: sem a cauda, jul/27 e ago/27
    somavam R$ 21,7 milhões de "descoberto" que era só o corte da janela, com
    R$ 5,7 milhões de pilha intocada em cada um.

    A empresa não para de faturar em ago/27. Três meses porque o prazo médio do
    recebível elegível é de 86 dias — é até onde um saque feito no último mês
    da janela alcançaria de verdade.

    Eles NUNCA entram no resultado: não têm linha, não têm saldo, não aparecem
    na tela. São pilha, e só.
    """
    if not linhas:
        return []
    ultimo = linhas[-1]["mes"]
    ano, m = int(ultimo[:4]), int(ultimo[5:7])
    out = []
    for _ in range(n):
        m += 1
        if m > 12:
            m, ano = 1, ano + 1
        out.append(f"{ano:04d}-{m:02d}")
    return out


def simular(linhas: list[dict], pilha: dict[str, dict], piso: dict[str, float],
            taxa_am, saldo_inicial: float, hoje: date,
            meses_extra: list[str] | None = None) -> dict:
    """O coração. Encadeia os meses antecipando o mínimo para não furar o piso.

    Três regras de escolha, e cada uma custa dinheiro se invertida:

    - **Saca do mês mais PRÓXIMO primeiro.** Menos dias de deságio pelo mesmo
      dinheiro. Sacar do mais distante "para preservar o curto prazo" é o
      instinto errado: o curto prazo se preserva sozinho quando ele chega.
    - **Nunca saca do PRÓPRIO mês.** O recebível que vence em setembro já está
      dentro da entrada de setembro; antecipá-lo não muda o saldo do mês, só
      paga deságio. (O motor DIÁRIO faz isso e está certo — lá o buraco é do
      dia 20 e o título vence no 25. Aqui não há dia.)
    - **O saque é BRUTO** (`falta / (1 − deságio)`), porque o deságio sai de
      dentro da própria operação.

    `meses_extra` são os meses de cauda (ver `meses_de_cauda`): servem de fonte
    e não geram linha.
    """
    sacado: dict[str, float] = {}
    ops: list[dict] = []
    out: list[dict] = []
    saldo = float(saldo_inicial)
    meses = [l["mes"] for l in linhas] + list(meses_extra or ())

    for i, l in enumerate(linhas):
        mes = l["mes"]
        # O que sobrou de entrada depois de meses anteriores terem sacado daqui.
        sac_de_mim = round(sacado.get(mes, 0.0), 2)
        entradas = round(float(l["entradas"]) - sac_de_mim, 2)
        saidas = float(l["saidas"])
        ini = saldo
        fim = ini + entradas - saidas
        alvo = float(piso.get(mes, 0.0))

        antecipado = custo = 0.0
        usados: list[dict] = []
        falta = alvo - fim
        if falta > 0:
            for origem in meses[i + 1:]:
                if falta <= 0:
                    break
                p = pilha.get(origem) or {}
                ja = sacado.get(origem, 0.0)
                disp = round(float(p.get("total", 0.0)) - ja, 2)
                if disp <= 0:
                    continue
                prazo = _prazo_dias(mes, origem, hoje)
                tx = float(taxa_am(prazo))
                desc = min(0.9, (tx / 100.0) * (prazo / 30.0))
                usa = round(min(disp, falta / (1.0 - desc)), 2)
                if usa <= 0:
                    continue
                liq = round(usa * (1.0 - desc), 2)
                # De qual metade da pilha saiu. O lançado é consumido primeiro
                # porque é o que existe: um plano que gasta nota já emitida
                # antes de contar com faturamento futuro é o mais executável
                # dos dois, e a diferença aparece na tela.
                de_lanc = round(max(0.0, min(usa, float(p.get("lancado", 0.0)) - ja)), 2)
                sacado[origem] = round(ja + usa, 2)
                antecipado = round(antecipado + usa, 2)
                custo = round(custo + (usa - liq), 2)
                falta = round(falta - liq, 2)
                op = {"mes": mes, "rotulo": l["rotulo"], "origem": origem,
                      "origem_rotulo": proj._rotulo(origem),
                      "prazo_dias": prazo, "taxa_am": round(tx, 4),
                      "desagio_pct": round(desc * 100, 3),
                      "bruto": usa, "liquido": liq, "custo": round(usa - liq, 2),
                      "de_lancado": de_lanc, "de_futuro": round(usa - de_lanc, 2)}
                ops.append(op)
                usados.append(op)
            fim = round(fim + (antecipado - custo), 2)

        descoberto = round(max(0.0, alvo - fim), 2)
        saldo = fim
        pm = pilha.get(mes) or {}
        out.append({
            "mes": mes, "rotulo": l["rotulo"],
            "saldo_inicial": round(ini, 2),
            "entradas": entradas,
            "entradas_projetadas": round(float(l["entradas"]), 2),
            "sacado_de_mim": sac_de_mim,
            "saidas": round(saidas, 2),
            "piso": round(alvo, 2),
            "antecipar": antecipado,
            "custo": custo,
            "liquido": round(antecipado - custo, 2),
            "saldo_final": round(saldo, 2),
            "descoberto": descoberto,
            "pilha": float(pm.get("total", 0.0)),
            "pilha_lancado": float(pm.get("lancado", 0.0)),
            "pilha_futuro": float(pm.get("futuro", 0.0)),
            "pilha_consumida": round(sacado.get(mes, 0.0), 2),
            # QUANTO DA PILHA DAQUELE MÊS O PLANO PRECISOU. É o indicador que
            # substitui o "descoberto" como alarme: enquanto sobra pilha o
            # plano fecha e a tela fica verde, e o mês em que a saturação bate
            # 100% é o mês em que a antecipação deixou de ter folga — a partir
            # dali qualquer atraso de cliente vira furo, porque não há de onde
            # sacar. Descoberto só aparece DEPOIS disso, tarde demais.
            "saturacao": (round(sacado.get(mes, 0.0) / float(pm["total"]), 4)
                          if float(pm.get("total") or 0) > 0 else None),
            "confianca": l.get("confianca"),
            "operacoes": usados,
        })

    return {"linhas": out, "operacoes": ops, "sacado": sacado}


def resumir(plano: list[dict], linhas_sem: list[dict],
            ops: list[dict] | None = None) -> dict:
    """Os números que decidem — e a conta que a antecipação NÃO resolve.

    `estrutural_mes` é a MEDIANA do resultado mensal do próprio fluxo (entrada
    menos saída, sem antecipação nenhuma). É ele que responde "e depois?":
    enquanto houver pilha o plano fecha todo mês e a tela fica verde; quando
    ela acaba, o déficit aparece inteiro de uma vez. Mostrar só o mês que fecha
    seria a mesma mentira da projeção sem antecipação, invertida.

    `capital_medio` existe porque **somar o nominal antecipado de doze meses e
    chamar aquilo de dívida erra por um fator de cinco** — o mesmo dinheiro
    gira várias vezes no ano. R$ 58,6 milhões de saque bruto com prazo médio de
    um mês e meio não são R$ 58,6 milhões de crédito tomado: são por volta de
    R$ 7 milhões de capital mantido empregado. É esse o número comparável com
    qualquer outra linha da empresa, e é a mesma definição que
    `antecipacoes.estrategia` já usa (Σ valor×prazo ÷ 365) — duas definições
    do mesmo conceito em dois módulos divergem no primeiro dia em que alguém
    mexe num só.
    """
    if not plano:
        return {}
    prim = plano[0]
    desc = [l for l in plano if l["descoberto"] > 0]
    bruto = round(sum(l["antecipar"] for l in plano), 2)
    custo = round(sum(l["custo"] for l in plano), 2)
    pilha_total = round(sum(l["pilha"] for l in plano), 2)
    resultados = [round(l["entradas_projetadas"] - l["saidas"], 2) for l in plano]
    return {
        # O número de AÇÃO: o que levar ao banco neste mês.
        "antecipar_agora": prim["antecipar"],
        "custo_agora": prim["custo"],
        "mes_agora": prim["rotulo"],
        "piso_agora": prim["piso"],
        "de_lancado_agora": round(sum(o["de_lancado"] for o in prim["operacoes"]), 2),
        # O COMPROMISSO: o que o plano inteiro consome de recebível futuro.
        "antecipar_12m": bruto,
        "custo_12m": custo,
        "custo_pct": round(custo / bruto * 100, 2) if bruto > 0 else None,
        "meses_com_operacao": sum(1 for l in plano if l["antecipar"] > 0),
        # O LIMITE: onde a antecipação para de resolver.
        "descoberto_total": round(sum(l["descoberto"] for l in desc), 2),
        "primeiro_descoberto": desc[0]["rotulo"] if desc else None,
        "meses_descobertos": len(desc),
        "estrutural_mes": round(statistics.median(resultados), 2) if resultados else 0.0,
        # A SATURAÇÃO é o alarme REAL, e ele acende bem antes do descoberto.
        # Enquanto sobra pilha o plano fecha todos os meses e a tela fica
        # verde; o mês em que o plano passa a precisar de 100% do recebível
        # elegível é o mês em que a antecipação perdeu a folga — dali em
        # diante, atraso de um cliente grande vira furo no mesmo dia, porque
        # não há de onde sacar. Esperar o descoberto para avisar é avisar
        # depois que já não há remédio.
        "primeiro_saturado": next((l["rotulo"] for l in plano
                                   if (l.get("saturacao") or 0) >= 0.99), None),
        "meses_saturados": sum(1 for l in plano
                               if (l.get("saturacao") or 0) >= 0.99),
        "saturacao_media": round(statistics.median(
            [l["saturacao"] for l in plano if l.get("saturacao") is not None]), 4)
            if any(l.get("saturacao") is not None for l in plano) else None,
        # O buraco que o plano cobre — o pior saldo do cenário SEM antecipar.
        # Ele fica no resumo porque é a medida do esforço: sem ele, "o plano
        # fecha todos os meses" se lê como se não houvesse problema nenhum.
        "pior_saldo_sem": (round(min(float(l["saldo_final"]) for l in linhas_sem), 2)
                           if linhas_sem else None),
        "pilha_total": pilha_total,
        "pilha_usada": bruto,
        **_capital(ops or [], custo),
    }


def _capital(ops: list[dict], custo: float) -> dict:
    """A antecipação lida como LINHA DE CRÉDITO. Ver o docstring de `resumir`."""
    if not ops:
        return {"capital_medio": 0.0, "custo_efetivo_aa": None,
                "prazo_medio": None, "giros_ano": None}
    bruto = sum(o["bruto"] for o in ops)
    cap = sum(o["bruto"] * o["prazo_dias"] for o in ops) / 365.0
    return {
        "capital_medio": round(cap, 2),
        # A taxa que se compara com qualquer outra linha da empresa — e a
        # única leitura em que o deságio de 1,17% a.m. e o rotativo de 15,67%
        # a.m. ficam na mesma régua.
        "custo_efetivo_aa": round(custo / cap * 100, 2) if cap > 0 else None,
        "prazo_medio": round(sum(o["bruto"] * o["prazo_dias"] for o in ops) / bruto, 1)
                       if bruto > 0 else None,
        "giros_ano": round(bruto / cap, 1) if cap > 0 else None,
    }


# ============================================================================
# Serviço — a única parte que fala com banco.
# ============================================================================

# A fatia do faturamento que é de cliente com convênio de antecipação. A raiz
# do CNPJ e não o nome: o ERP fatura por filial ("IOCHPE MAXION - CRUZEIRO/SP"
# e "- RESENDE/RJ" são duas linhas) e o convênio é da matriz.
SHARE_SQL = """
SELECT to_char(date_trunc('month', f.dtemissao),'YYYY-MM') AS mes,
       sum(f.valortitulo)::float8 AS total,
       sum(CASE WHEN substr(ca.codigo,1,8) = ANY(%(raizes)s)
                THEN f.valortitulo ELSE 0 END)::float8 AS elegivel
FROM fatura f
JOIN cadastro ca ON ca.codigo = f.cliente
WHERE f.dtcancelamento IS NULL
  AND f.dtemissao >= date_trunc('month', current_date)
                     - ((%(meses)s)::text || ' months')::interval
  AND f.dtemissao <  date_trunc('month', current_date)
GROUP BY 1 ORDER BY 1
"""


def fatia_elegivel(linhas: list[dict], meses: int = MESES_SHARE) -> dict:
    """Mediana da fatia elegível. MEDIANA e não média, por dois motivos.

    Um mês fraco de um cliente grande move a média o bastante para o plano
    inteiro mudar de tamanho; e a série tem tendência de ALTA (43,4% na média
    de 12 meses contra 54,7% em ago/26), sobre a qual a média de doze meses
    responde com um número que já não descreve a empresa.
    """
    uteis = [l for l in linhas[-meses:] if (l.get("total") or 0) > 0]
    if not uteis:
        return {"share": 0.0, "n": 0, "meses": []}
    vals = [l["elegivel"] / l["total"] for l in uteis]
    return {"share": round(statistics.median(vals), 4), "n": len(vals),
            "min": round(min(vals), 4), "max": round(max(vals), 4),
            "meses": [{"mes": l["mes"],
                       "pct": round(l["elegivel"] / l["total"] * 100, 1)}
                      for l in uteis]}


def _curva_de_taxa():
    """(função de taxa, descrição). Sai da MEDIÇÃO do portal, nunca de constante.

    O `_lastro` da projeção usava 2,0% a.m. escrito no código enquanto o portal
    praticava 1,17% — 41% de custo a mais, num número que a tela publicava como
    se fosse medido. Aqui a taxa vem de `mky_recebiveis` pela mesma curva que a
    tela de elegíveis já usa; a constante só entra quando não há medição
    nenhuma, e a tela DIZ qual dos dois está valendo.
    """
    try:
        with pglocal.get_conn() as c, c.cursor() as cur:
            cur.execute(eleg_mod.CURVA_SQL)
            faixas, ref = eleg_mod.montar_curva([dict(r) for r in cur.fetchall()])
        if faixas:
            return (lambda p: eleg_mod.taxa_estimada(p, faixas, ref) or TAXA_FALLBACK,
                    {"origem": "medida",
                     "referencia": round(ref, 4) if ref else None,
                     "base": sum(f[2] for f in faixas),
                     "faixas": [{"ate": t, "taxa": round(x, 4), "base": b}
                                for t, x, b in faixas]})
    except Exception as exc:  # noqa: BLE001 - base local fora não derruba o plano
        log.warning("plano sem curva de taxa medida: %s", type(exc).__name__)
    return (lambda p: TAXA_FALLBACK,
            {"origem": "fallback", "referencia": TAXA_FALLBACK,
             "base": 0, "faixas": []})


def _eleg_lancado_por_mes(raizes: list[str]) -> dict[str, float]:
    """Recebível em aberto de cliente com convênio, por mês de vencimento.

    Reusa o `ERP_SQL` da tela de elegíveis em vez de reescrever a regra: "em
    aberto" medido por dois critérios diferentes em duas telas é como as duas
    passam a discordar, e aí ninguém confia em nenhuma.
    """
    if not raizes:
        return {}
    acc: dict[str, float] = {}
    for r in db.query(eleg_mod.ERP_SQL, {"raizes": list(raizes)}):
        v = r["vencimento"]
        k = f"{v.year:04d}-{v.month:02d}"
        acc[k] = acc.get(k, 0.0) + float(r["valor"] or 0.0)
    return {k: round(v, 2) for k, v in acc.items()}


@cached(ttl=300, velha_ate=VELHA_ATE)
def get_plano(meses: int = 12, piso_dias: int = PISO_DIAS) -> dict:
    meses = max(3, min(proj.HORIZONTE_MAX, int(meses)))
    piso_dias = max(0, min(30, int(piso_dias)))

    base = proj.get_projecao(meses=meses)
    linhas = base["linhas"]
    hoje = date.fromisoformat(base["hoje"])

    try:
        raizes = sorted(antec_reg.raizes_elegiveis())
        sacados = [{"cnpj": s.get("cnpj"), "nome": s.get("nome"),
                    "portal": s.get("portal")}
                   for s in antec_reg.sacados(so_elegiveis=True)]
    except Exception as exc:  # noqa: BLE001
        log.warning("plano sem registro de convenios: %s", type(exc).__name__)
        raizes, sacados = [], []

    eleg_lanc = _eleg_lancado_por_mes(raizes)
    share_rows = (db.query(SHARE_SQL, {"raizes": raizes, "meses": 12})
                  if raizes else [])
    fatia = fatia_elegivel([dict(r) for r in share_rows])
    taxa_am, curva = _curva_de_taxa()

    piso = piso_por_mes(linhas, piso_dias)
    pilha = pilha_por_mes(linhas, eleg_lanc, fatia["share"])

    # A cauda: meses fora da janela que servem só de fonte de saque. A pilha
    # deles é a MEDIANA da pilha projetada — a capacidade recorrente da
    # empresa, sem o recebível já lançado, que a essa altura não existe mais.
    cauda = meses_de_cauda(linhas)
    if pilha:
        rec = statistics.median([p["futuro"] for p in pilha.values()]) if pilha else 0.0
        for m in cauda:
            pilha[m] = {"lancado": 0.0, "futuro": round(rec, 2),
                        "total": round(rec, 2), "cauda": True}

    sim = simular(linhas, pilha, piso, taxa_am,
                  saldo_inicial=float(base["kpis"]["saldo_inicial"]), hoje=hoje,
                  meses_extra=cauda)
    kpis = resumir(sim["linhas"], linhas, sim["operacoes"])

    try:
        from .credito import resumo as credito_resumo
        cred = credito_resumo(hoje)
        rot = {"limite": cred.get("total") or 0.0,
               "taxa_efetiva": cred.get("taxa_efetiva"),
               "bancos": len(cred.get("linhas") or ())}
    except Exception as exc:  # noqa: BLE001
        log.warning("plano sem credito: %s", type(exc).__name__)
        rot = None

    return {
        "hoje": base["hoje"], "meses": meses,
        "kpis": kpis,
        "linhas": sim["linhas"],
        "operacoes": sim["operacoes"],
        "piso": {"dias": piso_dias, "por_mes": piso,
                 "metodo": f"{piso_dias} dias da saída projetada de cada mês"},
        "pilha": {"por_mes": pilha, "fatia_elegivel": fatia,
                  "convenios": sacados, "raizes": raizes,
                  "lancado_total": round(sum(eleg_lanc.values()), 2)},
        "curva": curva,
        "rotativo": rot,
        # A projeção crua fica junto: é ela que mostra o buraco. A linha do
        # plano encosta no piso por construção e, sozinha, não diz nada.
        "sem_plano": [{"mes": l["mes"], "rotulo": l["rotulo"],
                       "saldo_final": l["saldo_final"]} for l in linhas],
        "quebra_de_nivel": base.get("quebra_de_nivel"),
        "atualizado_em": base.get("atualizado_em"),
        "fonte": ("Projeção de 12 meses (lançado + provisionado) + pilha "
                  "antecipável por convênio (ERP) + curva de taxa medida no "
                  "portal (mky_recebiveis) · leitura"),
    }
