"""Projeção de caixa de 6 a 12 meses — o lançado MAIS o que ainda vai ser
lançado.

O PROBLEMA
==========

O Fluxo Consolidado projeta o saldo encadeando o que está LANÇADO no ERP. Isso
está certo para os próximos dias e vira ficção a partir do segundo mês, por um
motivo medido: **o ERP não conhece o mês antes de ele acontecer.**

Curva de lançamento das contas a pagar, mediana dos 12 meses de vencimento
fechados até ago/2026, por dia relativo ao dia 1º do mês de vencimento:

    natureza            D-90   D-60   D-30    D+0   D+10   D+20   D+30
    Dívida financeira     35%    51%    65%    92%    92%    95%   100%
    Tributos              35%    36%    39%    42%    69%    78%    90%
    Operacional            9%    10%    15%    52%    77%    91%    99%
    Pessoal                0%     0%     0%     2%    56%    89%    96%

E o efeito disso no saldo, em 09/09/2026 (R$ mil, contas a pagar por vencimento):

    mês              mar-ago (fechados)   out/26   nov/26   dez/26
    Operacional          8.490 a 10.059    1.485      259      216
    Pessoal                 833 a  1.098        1        0        0
    Tributos                888 a  1.357      479      479      479
    Dívida financeira       825 a  2.317    1.216    1.159    1.157
    TOTAL               11.659 a 13.109    3.181    1.897    1.851

Novembro parece custar R$ 1,9 mi. Ele vai custar por volta de R$ 12 mi. Um
painel que mostre o primeiro número não está sendo conservador — está
informando um superávit que não existe, justamente no horizonte em que ainda
daria tempo de contratar antecipação.

AS QUATRO DECISÕES DESTE MÓDULO
===============================

**1. A projeção é POR NATUREZA, nunca global.**
As quatro naturezas se comportam de formas opostas, e a média entre elas não
descreve nenhuma. Dívida financeira já está 92% lançada no dia 1º — projetar
por cima dela DUPLICA parcela de financiamento. Pessoal está 0% lançada até o
dia 1º — não projetar apaga a folha inteira. Fazer as duas coisas ao mesmo
tempo, com um único fator global, é errar nas duas pontas e parecer certo no
total.

**2. Dois estimadores, e a discordância entre eles é publicada.**
- `nível × índice sazonal` — o que um mês daquele mês-calendário costuma custar
  hoje (ver `sazonalidade.py`: razão sobre média móvel, imune à perda de
  cliente que contaminaria a média simples).
- `lançado ÷ completude` — o que ESTE mês vai custar, ancorado no que já se
  sabe dele.
O segundo é melhor quando existe: ele usa informação do próprio mês. Só que
dividir por uma completude pequena multiplica o ruído por dez, então ele só
vale acima de `PISO_COMPLETUDE`. Abaixo disso vale o nível — e a diferença
entre os dois vai no payload (`divergencia`) em vez de ser escolhida em
silêncio. É a regra que `previsao/completude.py` já tinha para a DRE.

**3. O DDA dá PISO ao modelo, e NOME ao que falta.**
Boleto registrado no banco é obrigação com nome e CNPJ, não estimativa. Quando
o que o banco tem e o ERP não tem supera o que o modelo estimou, o modelo está
baixo — e o número que vale é o medido. Em 09/09/2026 eram R$ 2,10 mi de
boletos sem título correspondente, R$ 887 mil deles vencendo em out/26.

O piso raramente ganha do modelo, e isso é o esperado: o modelo estima o mês
INTEIRO e o DDA só enxerga o que já virou boleto. O valor dele está em dar NOME
e CNPJ a uma parte do buraco — "faltam R$ 9,4 mi em outubro" é um número;
"R$ 887 mil deles já são boleto registrado destes fornecedores" é trabalho.

**4. O que é lançado e o que é estimado nunca viram um número só.**
Cada mês publica `lancado`, `a_lancar` e a `confianca` (a fração do total que
já existe no ERP). Um mês 90% estimado e um mês 90% lançado não são a mesma
qualidade de informação, e a tela é obrigada a mostrar a diferença — a mesma
razão pela qual a casa hachura mês parcial em vez de deixá-lo parecer fechado.

O QUE ESTE MÓDULO NÃO FAZ
-------------------------

Não decide antecipar nada e não escreve no ERP. E não projeta ENTRADA
otimista: o lado do recebimento usa o mesmo nível dessazonalizado do
faturamento, deslocado pelo prazo médio de recebimento medido (DSO), com o
recebível LANÇADO mandando sempre que for maior — porque no curto prazo ele é
fato e a previsão é palpite.

CUSTO, MEDIDO (09/09/2026, mediana de 3 leituras frias)
-------------------------------------------------------

    total                     6,0 s      quente: 0 ms (TTL de 5 min)
      as 5 consultas do ERP   3,8 s
      lastro (antecipação)    1,1 s
      confronto do DDA        0,1 s

Não há vilão único — são varreduras de histórico, e as duas maiores (48 meses
de `contaapagar`, 12 meses com `dtinc`) são o que dá a sazonalidade e a curva.
Fica SEQUENCIAL de propósito: o padrão de busca em paralelo da Visão Geral
cortaria isso pela metade, e seis segundos num clique de aba — com esqueleto na
tela e cache de 5 minutos — não paga a complexidade. Se algum dia a tela abrir
sozinha no carregamento do painel, esta conta muda e o paralelo entra.
"""
from __future__ import annotations

import logging
import statistics
from datetime import date, timedelta

from .. import db
from ..queries import (DSO_SQL, VELHA_ATE, _natureza, cached)
from . import dda as dda_mod
from . import sazonalidade as saz

log = logging.getLogger("cortex.projecao")

# Abaixo desta completude não se divide: `lançado ÷ 0,10` transforma um título
# a mais numa projeção 10 vezes maior. Mesmo piso do `previsao/completude.py`,
# e pelo mesmo motivo.
PISO_COMPLETUDE = 0.30
# Teto do erro DEPOIS da amplificacao (dispersao / completude). Ver
# `pode_dividir`: 0,40 e o valor que separa as quatro naturezas reais da
# divida financeira em horizonte longo, que era o caso que inflava.
ERRO_AMPLIFICADO_MAX = 0.40
# Dispersao atribuida a quem nao tem medida (uma observacao so, ou natureza
# ausente da curva). Maxima incerteza: "nao sei" nunca autoriza dividir.
DISPERSAO_MAX = 1.0
# Quantos meses de vencimento fechados entram na curva de lançamento.
MESES_CURVA = 12
# Base do nível: 6 meses fechados. Curta de propósito — é ela que faz a perda
# de um cliente entrar na projeção sozinha (ver `sazonalidade.nivel`).
MESES_NIVEL = 6
# Horizonte máximo. Além de 12 meses, TUDO é estimativa e o índice sazonal
# passa a se repetir sobre si mesmo — a série ficaria mais bonita e não mais
# informativa.
HORIZONTE_MAX = 12

MESES_PT = ("jan", "fev", "mar", "abr", "mai", "jun",
            "jul", "ago", "set", "out", "nov", "dez")

# Ordem de exibição das naturezas: a que mais pesa primeiro, e Dívida
# financeira por último porque é a única que já vem lançada — quem lê a tabela
# procura o que FALTA.
ORDEM_NATUREZA = ("Operacional", "Pessoal", "Tributos", "Dívida financeira")


# ============================================================================
# SQL — tudo por VENCIMENTO, que é a data em que o dinheiro sai/entra.
# `dtinc` é quando a linha entrou no ERP: é ela que mede a curva de lançamento.
# ============================================================================

# Histórico de contas a pagar por vencimento × natureza × quando foi lançado.
# Uma consulta só para a curva E para o nível: são recortes do mesmo dado, e
# duas consultas divergiriam no dia em que alguém mexesse numa e não na outra.
HIST_PAGAR_SQL = """
SELECT to_char(a.dtvencimento,'YYYY-MM') AS mes,
       coalesce(nullif(trim(t.descricao),''), 'tipo '||a.tipotitulo::text) AS tipo,
       (a.dtvencimento::date - date_trunc('month', a.dtvencimento)::date) AS dia_venc,
       (a.dtinc::date - date_trunc('month', a.dtvencimento)::date) AS dia_rel,
       sum(a.valortitulo)::float8 AS valor
FROM contaapagar a
LEFT JOIN tipotitulo t ON t.codigo = a.tipotitulo
WHERE a.valortitulo > 0 AND a.dtinc IS NOT NULL
  AND a.dtvencimento >= date_trunc('month', current_date) - (%(meses)s || ' months')::interval
  AND a.dtvencimento <  date_trunc('month', current_date)
GROUP BY 1, 2, 3, 4
"""

# NÍVEL E SAZONALIDADE PEDEM OUTRA JANELA, e por isso são outra consulta.
#
# A curva de lançamento precisa de meses RECENTES: ela descreve como a
# contabilidade trabalha HOJE, e 12 meses já é o limite do que ainda descreve o
# presente. O índice sazonal precisa do contrário — sem 3 anos não há três
# dezembros para comparar, e a média móvel de 12 come 6 meses de cada ponta.
#
# Usar uma janela só era o defeito que a bancada pegou: com 12 meses o índice
# saía NEUTRO (1,00 em tudo, por falta de observação) e dezembro era projetado
# como um mês comum — R$ 400 mil de folha de 13º a menos, no pior mês do ano.
HIST_PAGAR_MES_SQL = """
SELECT to_char(a.dtvencimento,'YYYY-MM') AS mes,
       coalesce(nullif(trim(t.descricao),''), 'tipo '||a.tipotitulo::text) AS tipo,
       sum(a.valortitulo)::float8 AS valor
FROM contaapagar a
LEFT JOIN tipotitulo t ON t.codigo = a.tipotitulo
WHERE a.valortitulo > 0
  AND a.dtvencimento >= date_trunc('month', current_date) - interval '48 months'
  AND a.dtvencimento <  date_trunc('month', current_date)
GROUP BY 1, 2
"""

# O que JÁ ESTÁ lançado DE HOJE PARA A FRENTE. Duas escolhas, as duas iguais
# às do Fluxo Consolidado, para os dois painéis não discordarem:
#
# - `valorpendente`, não `valortitulo`: o que já foi pago não sai de novo.
# - `dtvencimento >= current_date`, não o início do mês: título vencido e não
#   pago é ESTOQUE, e a casa o trata num bloco separado. Somá-lo ao mês
#   corrente faria a operação do dia parecer inviável todo dia — é a decisão
#   que a planilha de tesouraria já tomava antes do sistema existir.
FUTURO_PAGAR_SQL = """
SELECT to_char(a.dtvencimento,'YYYY-MM') AS mes,
       coalesce(nullif(trim(t.descricao),''), 'tipo '||a.tipotitulo::text) AS tipo,
       sum(a.valorpendente)::float8 AS valor,
       count(*)::int AS titulos
FROM contaapagar a
LEFT JOIN tipotitulo t ON t.codigo = a.tipotitulo
WHERE a.valorpendente > 0 AND a.dtvencimento >= current_date
  AND a.dtvencimento < date_trunc('month', current_date) + (%(meses)s || ' months')::interval
GROUP BY 1, 2
"""

# Distribuição do vencimento DENTRO do mês, dos dois lados. É o que torna o
# mês corrente uma conta honesta em vez de uma duplicidade.
#
# O SALDO DE PARTIDA JÁ CONTÉM o que entrou e saiu do dia 1º até hoje. Projetar
# o mês corrente inteiro soma de novo a metade que já aconteceu — e não erra
# igual dos dois lados, o que é pior que errar muito: medido em 09/09/2026, no
# dia 9 ainda restam 82% das saídas do mês e só 63% das entradas. Tratar
# setembro como mês cheio inflaria a entrada 1,6 vez mais que a saída e
# pintaria de superávit um mês que fecha negativo.
HIST_RECEBER_DIA_SQL = """
SELECT to_char(f.dtvencimento,'YYYY-MM') AS mes,
       extract(day from f.dtvencimento)::int AS dia,
       sum(f.valortitulo)::float8 AS valor
FROM fatura f
WHERE f.dtcancelamento IS NULL AND f.valortitulo > 0
  AND f.dtvencimento >= date_trunc('month', current_date) - (%(meses)s || ' months')::interval
  AND f.dtvencimento <  date_trunc('month', current_date)
GROUP BY 1, 2
"""

# Faturamento mensal — a base do nível das ENTRADAS. Emissão, não vencimento:
# a pergunta aqui é "quanto a empresa vende por mês", e o deslocamento até o
# caixa é o DSO, aplicado depois.
HIST_FATURAR_SQL = """
SELECT to_char(date_trunc('month', f.dtemissao),'YYYY-MM') AS mes,
       sum(f.valortitulo)::float8 AS valor
FROM fatura f
WHERE f.dtcancelamento IS NULL
  AND f.dtemissao >= date_trunc('month', current_date) - interval '48 months'
  AND f.dtemissao <  date_trunc('month', current_date)
GROUP BY 1 ORDER BY 1
"""


# ============================================================================
# Parte PURA — recebe listas, devolve a projeção. É o que o teste exercita sem
# banco, e é onde as decisões acima viram conta.
# ============================================================================

def curva_completude(hist: list[dict]) -> dict:
    """Fração do total de cada natureza já lançada em cada dia relativo.

    `dia_rel` é contado a partir do dia 1º do mês de VENCIMENTO: negativo é
    lançamento antecipado (a parcela de financiamento de 2027 já está lá),
    positivo é lançamento durante ou depois do mês.

    Devolve `{"frac": {natureza: {dia: fração}}, "disp": {natureza: {dia: dp}}}`,
    ambos com a série `global`. A fração é a MEDIANA entre meses (não a média):
    um mês em que a contabilidade lançou tudo de uma vez não deve deslocar a
    curva dos outros onze.

    A DISPERSÃO É METADE DA RESPOSTA, e é por isso que ela sai junto. Medida
    nos 12 meses fechados até ago/2026, no dia 1º do mês de vencimento:

        Operacional         52% lançado, dispersão 0,06
        Tributos            42%,                   0,15
        Dívida financeira   92%,                   0,22   <- e 35% / 0,17 em D-90

    A dívida financeira é a que estraga: são parcelas agendadas com anos de
    antecedência MISTURADAS com dívida lançada tarde, e a mediana entre as duas
    populações não descreve nenhuma. Dividir o lançado por ela (1,157 mi ÷ 0,35)
    projetava R$ 3,3 mi de dívida para dezembro — quase três vezes o que o ERP
    já sabia daquele mês. Mesma armadilha que `previsao/completude.py` já tinha
    documentado na DRE (curva bimodal), e a mesma saída: não dividir.
    """
    por_nat: dict[str, dict[str, dict[int, float]]] = {}
    for r in hist:
        nat = _natureza(r["tipo"])
        d = int(r["dia_rel"])
        for chave in (nat, "global"):
            mes_d = por_nat.setdefault(chave, {}).setdefault(r["mes"], {})
            mes_d[d] = mes_d.get(d, 0.0) + r["valor"]

    frac: dict[str, dict[int, float]] = {}
    disp: dict[str, dict[int, float]] = {}
    for chave, por_mes in por_nat.items():
        # acumula cada mês por dia e guarda a fração; depois, a mediana por dia
        fracs: dict[int, list[float]] = {}
        for _mes, dias in por_mes.items():
            total = sum(dias.values())
            if total <= 0:
                continue
            acum = 0.0
            for d in range(-365, 61):
                acum += dias.get(d, 0.0)
                fracs.setdefault(d, []).append(min(1.0, acum / total))
        if not fracs:
            continue
        frac[chave] = {d: round(statistics.median(v), 4)
                       for d, v in sorted(fracs.items())}
        # UM mês só não mede dispersão, e tratá-la como zero afirmaria
        # "curva confiável" sobre uma observação. Vale a máxima incerteza.
        disp[chave] = {d: (round(statistics.pstdev(v), 4) if len(v) >= 2
                           else DISPERSAO_MAX)
                       for d, v in sorted(fracs.items())}
    return {"frac": frac, "disp": disp}


def _degrau(serie: dict[int, float] | None, dia_rel: int, fora_antes: float,
            fora_depois: float) -> float | None:
    """Último valor medido que não passa de `dia_rel`, com as pontas."""
    if not serie:
        return None
    dias = sorted(serie)
    if dia_rel < dias[0]:
        return fora_antes
    if dia_rel >= dias[-1]:
        return serie[dias[-1]] if fora_depois is None else fora_depois
    anterior = fora_antes
    for d in dias:
        if d > dia_rel:
            break
        anterior = serie[d]
    return anterior


def completude_em(curva: dict, natureza: str, dia_rel: int) -> float:
    """Cascata natureza -> global -> 1,0, igual ao módulo da previsão da DRE.

    Fora da faixa medida a resposta é 0,0 antes e 1,0 depois: um mês que ainda
    nem começou não tem por que ter lançamento, e um mês vencido há dois meses
    já tem tudo. Nenhuma das duas pontas é extrapolação — são os limites da
    própria pergunta.
    """
    frac = curva.get("frac") or {}
    for chave in (natureza, "global"):
        v = _degrau(frac.get(chave), dia_rel, 0.0, 1.0)
        if v is not None:
            return v
    return 1.0


def dispersao_em(curva: dict, natureza: str, dia_rel: int) -> float:
    """Mesma cascata, para o desvio-padrão das frações mês a mês.

    Devolve a MÁXIMA incerteza quando não há série: sem medida, a resposta
    honesta é "não sei", e não sei nunca autoriza dividir.
    """
    disp = curva.get("disp") or {}
    for chave in (natureza, "global"):
        v = _degrau(disp.get(chave), dia_rel, DISPERSAO_MAX, None)
        if v is not None:
            return v
    return DISPERSAO_MAX


def pode_dividir(comp: float, disp: float) -> bool:
    """A curva do próprio mês é confiável o bastante para dividir por ela?

    Dividir por `comp` AMPLIFICA tudo por 1/comp — inclusive o erro. O que
    decide não é a completude sozinha nem a dispersão sozinha, é a razão entre
    elas: `disp/comp` é o tamanho do erro DEPOIS da amplificação.

    Medido nas quatro naturezas reais, no dia 1º do mês de vencimento:

        Operacional        0,06 / 0,52 = 0,12   divide
        Dívida financeira  0,22 / 0,92 = 0,24   divide
        Pessoal (D+10)     0,17 / 0,56 = 0,30   divide
        Tributos           0,15 / 0,42 = 0,36   divide
        Dívida (D-90)      0,17 / 0,35 = 0,49   NÃO divide  <- o caso do bug

    O piso de completude continua valendo por cima: abaixo dele um título a
    mais vira uma projeção dez vezes maior, por melhor que seja a dispersão.
    """
    return comp >= PISO_COMPLETUDE and (disp / comp) <= ERRO_AMPLIFICADO_MAX


def fracao_restante(por_mes_dia: dict[str, dict[int, float]], dia: int) -> float:
    """Quanto de um mês típico ainda está por vir a partir do dia `dia`.

    Mediana entre os meses fechados, e não a média: um mês com um pagamento
    grande no dia 30 não deve dizer que todo dia 9 tem 90% do mês pela frente.

    Devolve 1,0 sem história — o dia 1º, e a resposta neutra, que é assumir o
    mês inteiro. Errar para o mês cheio é o lado seguro: superestima a saída
    que falta, nunca a esconde.
    """
    if dia <= 1 or not por_mes_dia:
        return 1.0
    fracs = []
    for _mes, dias in por_mes_dia.items():
        total = sum(dias.values())
        if total <= 0:
            continue
        fracs.append(sum(v for d, v in dias.items() if d >= dia) / total)
    return statistics.median(fracs) if fracs else 1.0


def _serie_por_natureza(hist: list[dict]) -> dict[str, list[tuple[str, float]]]:
    acc: dict[str, dict[str, float]] = {}
    for r in hist:
        nat = _natureza(r["tipo"])
        for chave in (nat, "global"):
            acc.setdefault(chave, {})
            acc[chave][r["mes"]] = acc[chave].get(r["mes"], 0.0) + r["valor"]
    return {k: sorted(v.items()) for k, v in acc.items()}


def _meses_a_frente(hoje: date, n: int) -> list[str]:
    saida, ano, mes = [], hoje.year, hoje.month
    for _ in range(n):
        saida.append(f"{ano:04d}-{mes:02d}")
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    return saida


def _rotulo(mes: str) -> str:
    return f"{MESES_PT[int(mes[5:7]) - 1]}/{mes[2:4]}"


def _primeiro_dia(mes: str) -> date:
    return date(int(mes[:4]), int(mes[5:7]), 1)


def projetar_saidas(hist: list[dict], lancado: dict[str, dict[str, float]],
                    meses: list[str], hoje: date,
                    piso_dda: dict[str, float] | None = None,
                    hist_longo: list[dict] | None = None) -> list[dict]:
    """A conta central. Um item por mês, com a decomposição por natureza.

    `hist` são os meses recentes COM `dia_rel` e `dia_venc` (a curva de
    lançamento e a distribuição dentro do mês). `hist_longo` são até 4 anos de
    mês × tipo × valor, e serve só para nível e sazonalidade — as duas
    perguntas pedem janelas opostas (ver `HIST_PAGAR_MES_SQL`).

    `lancado` é `{mes: {natureza: valor pendente}}` — o que o ERP já tem.
    `piso_dda` é `{mes: valor}` de boleto registrado no banco sem título no ERP.
    """
    piso_dda = piso_dda or {}
    curva = curva_completude(hist)
    series = _serie_por_natureza(hist_longo if hist_longo is not None else hist)
    indices = {nat: saz.indice_sazonal(serie) for nat, serie in series.items()}
    niveis = {nat: saz.nivel(serie, indices[nat]["indice"], MESES_NIVEL)
              for nat, serie in series.items()}
    # NATUREZA RESIDUAL NÃO SE PROJETA. "Migração de saldo" apareceu em 1 dos
    # 12 meses da base, com R$ 21 mil — e projetada por nível virava R$ 12 mil
    # POR MÊS, para sempre, numa linha que descreve um evento de implantação
    # que não vai acontecer de novo. É o mesmo erro de tratar zero como
    # desempenho: presença rara não é média baixa, é ausência.
    #
    # Quem não passa do piso continua na tabela pelo que está LANÇADO (isso é
    # fato), só não ganha estimativa por cima.
    base_meses = {m for serie in series.values() for m, _ in serie}
    recorrente = {
        nat: sum(1 for _m, v in serie if v > 0) >= max(2, len(base_meses) // 2)
        for nat, serie in series.items()}
    naturezas = [n for n in series if n != "global"]

    # Fração do mês corrente que ainda está por vir, por natureza — folha e
    # tributo não vencem nos mesmos dias que fornecedor.
    dias_venc: dict[str, dict[str, dict[int, float]]] = {}
    for r in hist:
        nat = _natureza(r["tipo"])
        # `dia_venc` vem como dias desde o dia 1º; o dia do calendário é ele + 1
        d = int(r["dia_venc"]) + 1
        for chave in (nat, "global"):
            m = dias_venc.setdefault(chave, {}).setdefault(r["mes"], {})
            m[d] = m.get(d, 0.0) + r["valor"]

    mes_corrente = f"{hoje.year:04d}-{hoje.month:02d}"
    linhas = []
    for mes in meses:
        dia_rel = (hoje - _primeiro_dia(mes)).days
        corrente = mes == mes_corrente
        det, total_prev, total_lanc, total_est = [], 0.0, 0.0, 0.0
        for nat in naturezas:
            lanc = float(lancado.get(mes, {}).get(nat, 0.0))
            comp = completude_em(curva, nat, dia_rel)
            ix = indices[nat]["indice"].get(int(mes[5:7]), 1.0)
            # No mês corrente só o RESTO conta: o começo do mês já está dentro
            # do saldo de partida.
            resto = (fracao_restante(dias_venc.get(nat) or dias_venc.get("global") or {},
                                     hoje.day) if corrente else 1.0)
            por_nivel = (niveis[nat] * ix * resto) if recorrente.get(nat) else 0.0
            # Ancorado no próprio mês, quando há informação suficiente dele —
            # e NUNCA no mês corrente, onde `lanc` já é uma fatia do mês
            # (só o que vence de hoje em diante) e a completude descreve o mês
            # inteiro: dividir um pelo outro mistura dois recortes.
            disp = dispersao_em(curva, nat, dia_rel)
            por_curva = (lanc / comp if lanc > 0 and not corrente
                         and pode_dividir(comp, disp) else None)
            previsto = por_curva if por_curva is not None else por_nivel
            # O lançado é FATO: previsão abaixo dele seria negar o que já
            # existe. Acontece em Dívida financeira, cujo futuro já está todo
            # no ERP e às vezes supera o que a média histórica esperaria.
            previsto = max(previsto, lanc)
            det.append({
                "natureza": nat, "lancado": round(lanc, 2),
                "previsto": round(previsto, 2),
                "a_lancar": round(max(0.0, previsto - lanc), 2),
                "completude": round(comp, 4), "dispersao": round(disp, 4),
                "indice": round(ix, 4), "resto_do_mes": round(resto, 4),
                "metodo": ("parcial" if corrente else
                           "curva" if por_curva is not None else "nivel"),
                # A discordância entre os dois estimadores, quando os dois
                # existem. É o que permite à tela dizer "este mês tem duas
                # leituras e elas divergem 18%" em vez de escolher calada.
                "divergencia": (round((por_curva - por_nivel) / por_nivel, 4)
                                if por_curva is not None and por_nivel > 0 else None),
            })
            total_prev += previsto
            total_lanc += lanc
            total_est += por_nivel

        det.sort(key=lambda d: (ORDEM_NATUREZA.index(d["natureza"])
                                if d["natureza"] in ORDEM_NATUREZA else 99))
        a_lancar = max(0.0, total_prev - total_lanc)
        dda = float(piso_dda.get(mes, 0.0))
        # PISO MEDIDO: boleto registrado é obrigação, não palpite. Quando ele
        # supera a estimativa, quem está errado é a estimativa.
        piso_venceu = dda > a_lancar + 0.005
        if piso_venceu:
            a_lancar = dda
            total_prev = total_lanc + a_lancar
        linhas.append({
            "mes": mes, "rotulo": _rotulo(mes),
            "lancado": round(total_lanc, 2),
            "a_lancar": round(a_lancar, 2),
            "previsto": round(total_lanc + a_lancar, 2),
            "por_nivel": round(total_est, 2),
            "dda": round(dda, 2), "dda_manda": piso_venceu,
            # 1,0 = tudo o que vai vencer neste mês já está no ERP.
            "confianca": round(total_lanc / (total_lanc + a_lancar), 4)
                         if (total_lanc + a_lancar) > 0 else 0.0,
            "naturezas": det,
        })
    return linhas


def projetar_entradas(serie_fat: list[tuple[str, float]],
                      recebivel: dict[str, float], meses: list[str],
                      dso: float | None, hoje: date | None = None,
                      dias_venc: dict[str, dict[int, float]] | None = None,
                      ) -> tuple[list[dict], dict, float, int]:
    """Recebimento esperado por mês.

    O faturamento de um mês vira caixa `dso` dias depois — então o recebimento
    do mês M é o faturamento de M menos o deslocamento. Com DSO de ~30 dias,
    o caixa de novembro é o que se fatura em outubro.

    **O recebível LANÇADO manda sempre que for maior.** Nos primeiros meses ele
    é fato (fatura emitida, vencimento conhecido) e a previsão é modelo; usar o
    modelo por cima do fato jogaria fora a única informação firme do curto
    prazo. Nos meses distantes ele é ~zero e o modelo assume — que é
    exatamente o `balde_seco` que o Fluxo Consolidado já detecta e do qual esta
    projeção é a resposta.
    """
    ix = saz.indice_sazonal(serie_fat)
    nivel = saz.nivel(serie_fat, ix["indice"], MESES_NIVEL)
    # Deslocamento em MESES inteiros: a granularidade da projeção é o mês, e
    # fingir precisão de dias sobre um DSO que é média ponderada de um ano
    # seria precisão inventada. 45 dias -> 1 mês; 75 dias -> 2.
    desloc = 0 if dso is None else max(0, min(3, int(round(dso / 30.0))))
    hoje = hoje or date.today()
    mes_corrente = f"{hoje.year:04d}-{hoje.month:02d}"
    linhas = []
    for mes in meses:
        ano, m = int(mes[:4]), int(mes[5:7])
        m -= desloc
        while m <= 0:
            m += 12
            ano -= 1
        origem = f"{ano:04d}-{m:02d}"
        # Mesma correção do lado da saída: no mês corrente só entra o que ainda
        # não venceu — o resto já está no saldo de partida.
        resto = (fracao_restante(dias_venc or {}, hoje.day)
                 if mes == mes_corrente else 1.0)
        modelo = nivel * ix["indice"].get(m, 1.0) * resto
        lanc = float(recebivel.get(mes, 0.0))
        # O previsto e' o MAIOR dos dois, e a confianca mede contra ELE. Medir
        # contra o modelo dava confianca de 5,0 num mes em que o recebivel
        # lancado supera a previsao — e "500% lancado" e' um numero que a tela
        # mostraria sem piscar.
        previsto = max(modelo, lanc)
        linhas.append({
            "mes": mes, "rotulo": _rotulo(mes),
            "lancado": round(lanc, 2),
            "previsto": round(previsto, 2),
            "a_faturar": round(max(0.0, previsto - lanc), 2),
            "origem_faturamento": origem,
            "indice": round(ix["indice"].get(m, 1.0), 4),
            "resto_do_mes": round(resto, 4),
            "confianca": round(min(1.0, lanc / previsto), 4) if previsto > 0 else 0.0,
        })
    return linhas, ix, nivel, desloc


def montar(saidas: list[dict], entradas: list[dict], saldo_inicial: float
           ) -> tuple[list[dict], dict]:
    """Encadeia o saldo e mede a necessidade. PURO.

    A necessidade é `max(0, -saldo)` — o piso é zero, por decisão de quem
    opera: a projeção cobre o descoberto, não constrói reserva. Quem quiser
    reserva a soma por fora, e assim o número que a tela mostra continua sendo
    "quanto falta para não furar", não "quanto eu gostaria de ter".
    """
    linhas, saldo = [], saldo_inicial
    ent_por_mes = {e["mes"]: e for e in entradas}
    for s in saidas:
        e = ent_por_mes.get(s["mes"], {})
        entrada = float(e.get("previsto", 0.0))
        saida = float(s["previsto"])
        inicial, saldo = saldo, saldo + entrada - saida
        linhas.append({
            "mes": s["mes"], "rotulo": s["rotulo"],
            "saldo_inicial": round(inicial, 2),
            "entradas": round(entrada, 2), "saidas": round(saida, 2),
            "entradas_lancadas": float(e.get("lancado", 0.0)),
            "saidas_lancadas": s["lancado"],
            "a_lancar": s["a_lancar"], "a_faturar": float(e.get("a_faturar", 0.0)),
            "dda": s["dda"], "dda_manda": s["dda_manda"],
            "resultado": round(entrada - saida, 2),
            "saldo_final": round(saldo, 2),
            "necessidade": round(max(0.0, -saldo), 2),
            # A confiança do MÊS é a do lado pior: um mês com as saídas todas
            # lançadas e as entradas todas estimadas não é um mês conhecido.
            "confianca": round(min(s["confianca"], float(e.get("confianca", 0.0))), 4),
            "naturezas": s["naturezas"],
        })
    pior = min((l["saldo_final"] for l in linhas), default=saldo_inicial)
    primeiro_neg = next((l for l in linhas if l["saldo_final"] < 0), None)
    # DUAS NECESSIDADES, e confundi-las leva a decisão errada.
    #
    # A do MÊS (`necessidade_mensal`) é o pior resultado de um mês isolado: o
    # descasamento entre o que entra e o que sai naquele mês. Ela se resolve
    # antecipando recebível — o dinheiro existe, está no prazo errado.
    #
    # A ACUMULADA (`necessidade`) é o pior saldo da série: a soma dos déficits
    # que ainda não foram cobertos. Antecipação NÃO resolve essa: antecipar
    # traz para hoje o que entraria depois, e o depois fica sem. Buraco
    # acumulado pede resultado, prazo com fornecedor ou capital.
    pior_mes_res = min(linhas, key=lambda l: l["resultado"]) if linhas else None
    kpis = {
        "saldo_inicial": round(saldo_inicial, 2),
        "saldo_final": round(linhas[-1]["saldo_final"], 2) if linhas else saldo_inicial,
        "pior_saldo": round(pior, 2),
        "pior_mes": min(linhas, key=lambda l: l["saldo_final"])["rotulo"] if linhas else None,
        "necessidade": round(max(0.0, -pior), 2),
        "necessidade_mensal": round(max(0.0, -pior_mes_res["resultado"]), 2)
                              if pior_mes_res else 0.0,
        "pior_mes_resultado": pior_mes_res["rotulo"] if pior_mes_res else None,
        "meses_negativos": sum(1 for l in linhas if l["resultado"] < 0),
        "queima_media": round(
            sum(l["resultado"] for l in linhas) / len(linhas), 2) if linhas else 0.0,
        "primeiro_negativo": primeiro_neg["rotulo"] if primeiro_neg else None,
        "primeiro_negativo_mes": primeiro_neg["mes"] if primeiro_neg else None,
        "entradas": round(sum(l["entradas"] for l in linhas), 2),
        "saidas": round(sum(l["saidas"] for l in linhas), 2),
        "a_lancar": round(sum(l["a_lancar"] for l in linhas), 2),
        "a_faturar": round(sum(l["a_faturar"] for l in linhas), 2),
        "dda_no_horizonte": round(sum(l["dda"] for l in linhas), 2),
    }
    return linhas, kpis


# ============================================================================
# Serviço — busca os dois lados e monta. É a única parte que fala com o banco.
# ============================================================================

@cached(ttl=300, velha_ate=VELHA_ATE)
def get_projecao(meses: int = 12) -> dict:
    meses = max(3, min(HORIZONTE_MAX, int(meses)))
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(HIST_PAGAR_SQL, {"meses": MESES_CURVA})
        hist = cur.fetchall()
        cur.execute(HIST_PAGAR_MES_SQL)
        hist_longo = cur.fetchall()
        cur.execute(FUTURO_PAGAR_SQL, {"meses": meses})
        futuro = cur.fetchall()
        cur.execute(HIST_FATURAR_SQL)
        hist_fat = cur.fetchall()
        cur.execute(HIST_RECEBER_DIA_SQL, {"meses": MESES_CURVA})
        hist_rec_dia = cur.fetchall()
        cur.execute(DSO_SQL)
        dso_rows = cur.fetchall()
        cur.execute("SELECT current_date AS hoje, current_timestamp AS ts")
        meta = cur.fetchone()

    hoje: date = meta["hoje"]
    lista = _meses_a_frente(hoje, meses)

    lancado: dict[str, dict[str, float]] = {}
    titulos: dict[str, int] = {}
    for r in futuro:
        nat = _natureza(r["tipo"])
        lancado.setdefault(r["mes"], {})
        lancado[r["mes"]][nat] = lancado[r["mes"]].get(nat, 0.0) + r["valor"]
        titulos[r["mes"]] = titulos.get(r["mes"], 0) + r["titulos"]

    # DDA: falha aqui NÃO derruba a projeção — ela apenas perde o piso medido,
    # e a tela diz que perdeu. Base local fora do ar é problema de instalação,
    # não motivo para a tesouraria ficar sem projeção.
    try:
        conf = dda_mod.confronto()
        piso = dda_mod.faltantes_por_mes(conf)
        dda_estado = conf.get("estado")
        dda_resumo = conf.get("resumo")
    except Exception as exc:  # noqa: BLE001
        log.warning("projecao sem o DDA: %s", type(exc).__name__)
        piso, dda_estado, dda_resumo = {}, None, None

    saidas = projetar_saidas(
        [dict(r) for r in hist], lancado, lista, hoje, piso_dda=piso,
        hist_longo=[dict(r) for r in hist_longo])

    # Recebível lançado por mês, pela regra oficial do consolidado (mesma
    # fonte do `get_fluxo_consolidado`, para os dois números não divergirem).
    recebivel = _recebivel_por_mes(lista)
    serie_fat = [(r["mes"], r["valor"]) for r in hist_fat]
    ult3 = [r["dias"] for r in dso_rows if r["dias"] is not None][-3:]
    dso = (sum(ult3) / len(ult3)) if ult3 else None
    dias_rec: dict[str, dict[int, float]] = {}
    for r in hist_rec_dia:
        dias_rec.setdefault(r["mes"], {})[int(r["dia"])] = r["valor"]
    entradas, ix_fat, nivel_fat, desloc = projetar_entradas(
        serie_fat, recebivel, lista, dso, hoje=hoje, dias_venc=dias_rec)

    saldo_ini = _saldo_atual()
    linhas, kpis = montar(saidas, entradas, saldo_ini)
    for l in linhas:
        l["titulos_lancados"] = titulos.get(l["mes"], 0)

    quebra = saz.quebra_de_nivel(serie_fat, ix_fat["indice"], MESES_NIVEL)
    lastro = _lastro(kpis)

    return {
        "lastro": lastro,
        "hoje": hoje.isoformat(), "meses": meses,
        "kpis": {**kpis, "dso": round(dso, 1) if dso is not None else None,
                 "deslocamento_meses": desloc,
                 "nivel_faturamento": round(nivel_fat, 2)},
        "linhas": linhas,
        "entradas": entradas,
        "sazonalidade": {
            "faturamento": {"indice": ix_fat["indice"], "n": ix_fat["n"],
                            "dispersao": ix_fat["dispersao"],
                            "metodo": ix_fat["metodo"], "meses": ix_fat["meses"]},
        },
        # A tela DIZ que a base mudou de patamar, em vez de projetar em
        # silêncio a partir de uma média que já não descreve a empresa.
        "quebra_de_nivel": quebra,
        "dda": {"estado": dda_estado, "resumo": dda_resumo,
                "por_mes": piso, "disponivel": bool(piso or dda_estado)},
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": ("ERP AVA · contaapagar e fatura por vencimento (o LANÇADO) + "
                  "curva de lançamento e sazonalidade dos meses fechados (o "
                  "estimado) + DDA importado (o piso medido) · leitura"),
    }


def _lastro(kpis: dict) -> dict:
    """O que existe para cobrir a necessidade, e a que custo.

    Três fontes, e elas NÃO se somam num número só de propósito — cada uma
    responde a uma necessidade diferente:

    - **antecipação de recebível**: cobre descasamento de prazo (a necessidade
      MENSAL). Custa o deságio, e é dinheiro que a empresa já tem a receber.
    - **limite rotativo**: cobre o vale entre dois meses. É o mais caro da
      casa (12,9% a 16,2% a.m. hoje) e o menor.
    - **recebível em aberto**: o estoque total. Não é caixa disponível — é o
      teto do que a antecipação poderia alcançar se todos os sacados tivessem
      convênio, que não é o caso.

    Somar os três daria um "temos R$ X" que ninguém pode gastar. Cada bloco
    reusa o módulo que já existe (`get_antecipacao`, `financeiro.credito`) em
    vez de recalcular — dois cálculos do mesmo número divergem no primeiro dia
    em que alguém mexe num só.
    """
    from ..queries import get_antecipacao
    out: dict = {"antecipacao": None, "credito": None, "recebiveis": None}
    try:
        a = get_antecipacao(dias=180, reserva=0.0, taxa_mes=2.0)["kpis"]
        out["antecipacao"] = {
            "total": a["total_antecipar"], "custo": a["custo_total"],
            "custo_pct": a["custo_pct"], "operacoes": a["operacoes"]}
    except Exception as exc:  # noqa: BLE001 - bloco acessório
        log.warning("lastro sem antecipacao: %s", type(exc).__name__)
    try:
        from .credito import resumo as credito_resumo
        r = credito_resumo()
        out["credito"] = {"limite": r.get("total") or 0.0,
                          "taxa_efetiva": r.get("taxa_efetiva"),
                          "custo_mes": r.get("custo_mes_total"),
                          "bancos": len(r.get("linhas") or ())}
    except Exception as exc:  # noqa: BLE001
        log.warning("lastro sem credito: %s", type(exc).__name__)
    try:
        from ..queries import KPI_SQL, SEM_PARTES
        est = db.query(KPI_SQL, {"data_ref": None, "filial": None,
                                 "venc_de": None, "venc_ate": None,
                                 **SEM_PARTES})[0]
        out["recebiveis"] = {"aberto": est["receber_aberto"],
                             "titulos": est["receber_qtd"],
                             "vencido": est["receber_vencido"],
                             "prox30": est["receber_prox30"]}
    except Exception as exc:  # noqa: BLE001
        log.warning("lastro sem recebiveis: %s", type(exc).__name__)
    nec = float(kpis.get("necessidade") or 0.0)
    nec_mes = float(kpis.get("necessidade_mensal") or 0.0)
    antec = float((out["antecipacao"] or {}).get("total") or 0.0)
    lim = float((out["credito"] or {}).get("limite") or 0.0)
    out["cobertura_mensal"] = round((antec + lim) / nec_mes, 4) if nec_mes > 0 else None
    out["cobertura_acumulada"] = round((antec + lim) / nec, 4) if nec > 0 else None
    # A conclusão que o número sozinho não dá: quando o buraco ACUMULADO passa
    # do que antecipação e limite cobrem, o problema deixou de ser de prazo.
    out["estrutural"] = bool(nec > 0 and (antec + lim) < nec)
    return out


def _recebivel_por_mes(meses: list[str]) -> dict[str, float]:
    """A receber em aberto por mês de vencimento, pela regra oficial.

    Importa `queries` aqui dentro e não no topo porque `queries` importa este
    módulo pela rota — o ciclo só não estoura porque a chamada é tardia.
    """
    from ..queries import FLUXCON_REC_SQL
    if not meses:
        return {}
    ultimo = _primeiro_dia(meses[-1])
    fim = (ultimo.replace(day=28) + timedelta(days=4)).replace(day=1)
    dias = (fim - date.today()).days
    acc: dict[str, float] = {}
    for r in db.query(FLUXCON_REC_SQL, {"dias": max(1, dias)}):
        k = f"{r['dia'].year:04d}-{r['dia'].month:02d}"
        acc[k] = acc.get(k, 0.0) + r["valor"]
    return acc


def _saldo_atual() -> float:
    """Bancos + caixa, a mesma partida do Fluxo Consolidado."""
    from ..queries import ANTEC_SALDO_SQL
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(ANTEC_SALDO_SQL)
        bancos = (cur.fetchone() or {}).get("bancos") or 0.0
        cur.execute("SELECT coalesce(sum(valorsaldo),0)::float8 AS caixa FROM ("
                    "SELECT DISTINCT ON (grupo,empresa,filial,unidade,caixa) valorsaldo"
                    " FROM caixa_saldo WHERE dtmovimento <= current_date"
                    " ORDER BY grupo,empresa,filial,unidade,caixa, dtmovimento DESC) x")
        caixa = (cur.fetchone() or {}).get("caixa") or 0.0
    return float(bancos) + float(caixa)
