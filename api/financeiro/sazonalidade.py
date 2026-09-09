"""Nível e sazonalidade de uma série mensal — PURO (sem banco).

POR QUE NÃO SERVE "MÉDIA DO MÊS ÷ MÉDIA GERAL"
==============================================

É o que `queries._previsao_sazonal` faz hoje, e ele confunde NÍVEL com
SAZONALIDADE. Se a empresa faturava R$ 15 mi/mês em 2024 e passa a faturar
R$ 12 mi em 2026, a média de cada mês-calendário carrega quantos anos "altos"
e quantos "baixos" caíram nele — e o índice vira uma medida de quando cada mês
foi observado, não de como ele se comporta.

Isso não é hipótese: a casa perdeu em 2026 um cliente que respondia por 15 a
17% do faturamento e saiu de vez em abril. (O repositório é público — o nome e
o CNPJ ficam de fora; a MEDIÇÃO é o que importa aqui.) Comparados os dois
métodos sobre a mesma série real de 43 meses, o antigo erra assim:

    out  1,206 contra 1,083 reais  (+10,3% de faturamento que não vem)
    nov  1,049 contra 0,959        (+8,6%)
    dez  0,898 contra 0,807        (+10,2%)

Dez por cento a mais de entrada esperada em três meses seguidos, num
horizonte em que a decisão é justamente "preciso antecipar recebível?".

O QUE ESTE MÓDULO FAZ NO LUGAR
------------------------------

**Razão sobre média móvel centrada de 12 meses.** Para cada mês, divide-se o
valor pela média dos 12 meses centrados nele. A média móvel acompanha o nível
— sobe quando a empresa cresce e DESCE quando um cliente sai —, então a razão
que sobra é só a estação. O índice de cada mês-calendário é a MEDIANA dessas
razões (não a média: um mês atípico não deve arrastar o índice, mesma régua do
resto da casa).

O preço é honesto e está declarado: a média móvel de 12 come 6 meses de cada
ponta, então 43 meses de história rendem só 2-3 observações por
mês-calendário. Poucas observações que discordam entre si não são índice — são
ruído com aparência de padrão.

**Por isso o índice é AMORTECIDO pela própria dispersão.** Quando as razões de
um mês-calendário divergem muito, o índice é puxado na direção de 1,0 na
proporção da discordância. Um mês medido três vezes como 1,45 / 1,00 / 1,17
não afirma "+17%" com a mesma força que um medido 0,76 / 0,94 / 0,81 afirma
"−19%". É a mesma decisão que `previsao/completude.py` tomou ao recusar dividir
por uma curva bimodal: a saída de uma medição ruim é dizer menos, não errar
com confiança.

O QUE A CASA MEDIU (ago/2026)
-----------------------------

Faturamento:  dez 0,81 · jan 0,86 · fev 0,89 — e ago 1,17, abr 1,14, jul 1,12.
Contas a pagar, por natureza (é aí que dezembro vira um problema de caixa):

    Pessoal    nov 1,25 · dez 1,41   <- o 13º, e ele NÃO aparece no total
    Tributos   jan 0,53 · fev 0,65 · out 1,39
    Operacional  quase plano (jan 0,87 a ago 1,12)

Dezembro é receita 19% abaixo com folha 41% acima. Uma projeção de médio prazo
que não separe as duas coisas mostra dezembro como um mês comum.
"""
from __future__ import annotations

import statistics

# Metade da janela da média móvel. 6 = janela de 12 meses (um ciclo anual
# inteiro), que é o que faz a razão isolar a estação em vez de o trimestre.
MEIA_JANELA = 6
# Mínimo de meses para tentar sazonalidade. Abaixo disso a média móvel não
# rende observação nenhuma e o índice seria inventado.
MINIMO_MESES = MEIA_JANELA * 2 + 6
# Acima desta dispersão (desvio-padrão das razões de um mês-calendário) o
# índice é considerado indistinguível de 1,0. 0,25 = as observações daquele mês
# variam um quarto entre si — mais que a própria amplitude sazonal medida.
DISPERSAO_NEUTRA = 0.25
# Teto e piso do índice depois do amortecimento. Não é estética: um índice de
# 2,3 vindo de duas observações projetaria um mês que nunca existiu.
INDICE_MIN, INDICE_MAX = 0.55, 1.65


def indice_sazonal(serie: list[tuple[str, float]]) -> dict:
    """Série [(AAAA-MM, valor)] ordenada -> índice por mês-calendário.

    Devolve `{"indice": {1..12: float}, "n": {1..12: int},
              "dispersao": {1..12: float}, "metodo": str, "meses": int}`.

    `metodo="neutro"` com índice 1,0 em todos os meses é resposta legítima e
    NÃO é falha: significa "não há história para afirmar estação", e é
    infinitamente melhor que um índice de uma observação. Quem consome mostra
    isso na tela em vez de esconder atrás de um número redondo.
    """
    vazio = {"indice": {m: 1.0 for m in range(1, 13)},
             "n": {m: 0 for m in range(1, 13)},
             "dispersao": {m: 0.0 for m in range(1, 13)},
             "metodo": "neutro", "meses": len(serie)}
    if len(serie) < MINIMO_MESES:
        return vazio

    razoes: dict[int, list[float]] = {m: [] for m in range(1, 13)}
    for i in range(MEIA_JANELA, len(serie) - MEIA_JANELA):
        janela = serie[i - MEIA_JANELA:i + MEIA_JANELA]
        media = sum(v for _, v in janela) / len(janela)
        if media <= 0:
            continue
        razoes[int(serie[i][0][5:7])].append(serie[i][1] / media)

    if not any(razoes.values()):
        return vazio

    indice: dict[int, float] = {}
    dispersao: dict[int, float] = {}
    for m in range(1, 13):
        obs = razoes[m]
        if not obs:
            indice[m], dispersao[m] = 1.0, 0.0
            continue
        bruto = statistics.median(obs)
        # 1 observação não mede dispersão. Trata-se como MÁXIMA incerteza, não
        # como zero: uma única razão é exatamente o caso em que não se sabe se
        # aquilo é estação ou foi um mês esquisito.
        disp = statistics.pstdev(obs) if len(obs) >= 2 else DISPERSAO_NEUTRA
        dispersao[m] = round(disp, 4)
        # amortecimento: peso 1 com dispersão zero, 0 na dispersão neutra
        peso = max(0.0, 1.0 - disp / DISPERSAO_NEUTRA)
        indice[m] = round(min(INDICE_MAX, max(INDICE_MIN, 1.0 + (bruto - 1.0) * peso)), 4)

    # Normaliza para média 1,0 entre os meses OBSERVADOS: sem isso, um conjunto
    # de índices todos acima de 1 (série em queda, em que todo mês supera a
    # média móvel que já caiu) multiplicaria o nível e inflaria o ano inteiro.
    obs = [indice[m] for m in range(1, 13) if razoes[m]]
    if obs:
        media = sum(obs) / len(obs)
        if media > 0:
            for m in range(1, 13):
                indice[m] = round(indice[m] / media, 4)

    return {"indice": indice, "n": {m: len(razoes[m]) for m in range(1, 13)},
            "dispersao": dispersao, "metodo": "razao_media_movel",
            "meses": len(serie)}


def nivel(serie: list[tuple[str, float]], indice: dict[int, float],
          meses: int = 6) -> float:
    """Quanto vale um mês MÉDIO hoje, em valor dessazonalizado.

    MEDIANA dos últimos `meses` fechados, cada um dividido pelo índice do seu
    mês-calendário. Duas decisões, nas duas ordens possíveis de errar:

    - **Dessazonalizar ANTES de tirar o nível.** Seis meses que caem numa
      estação forte (mar-ago, cujo índice médio é ~1,07) dariam um nível 7%
      alto, e esse erro entraria em TODOS os meses projetados.
    - **Mediana, não média.** Um mês com um evento não recorrente — venda de
      ativo, acordo, um lote de tributo — move a média o bastante para se
      inocentar. É a mesma régua que a casa usa para desvio de preço de peça.

    A janela curta é deliberada: ela é o que faz a perda de um cliente entrar
    na projeção sozinha, sem ninguém cadastrar nada. Passados 6 meses da saída,
    nenhum mês da base ainda carrega o faturamento que não existe mais.
    """
    if not serie:
        return 0.0
    ultimos = serie[-meses:]
    vals = []
    for mes, valor in ultimos:
        ix = indice.get(int(mes[5:7]), 1.0) or 1.0
        vals.append(valor / ix)
    return statistics.median(vals) if vals else 0.0


def quebra_de_nivel(serie: list[tuple[str, float]], indice: dict[int, float],
                    meses: int = 6) -> dict | None:
    """Compara o nível dos últimos `meses` com o dos `meses` anteriores.

    Existe para a tela poder DIZER que a base mudou, em vez de projetar em
    silêncio a partir de uma média que já não descreve a empresa. Quando o
    degrau é grande, a leitura correta não é "a projeção está errada" — é "a
    projeção mudou de patamar de propósito, e é este o motivo".

    Não nomeia a causa: o degrau diz que o nível caiu, não POR QUE caiu. Um
    módulo estatístico que apontasse um cliente estaria adivinhando.
    """
    if len(serie) < meses * 2:
        return None
    recente = nivel(serie, indice, meses)
    anterior = nivel(serie[:-meses], indice, meses)
    if anterior <= 0:
        return None
    var = (recente - anterior) / anterior
    # 8% é maior que a oscilação normal entre dois semestres dessazonalizados
    # e menor que qualquer perda de cliente que mude decisão de caixa.
    if abs(var) < 0.08:
        return None
    return {"recente": round(recente, 2), "anterior": round(anterior, 2),
            "variacao": round(var, 4),
            "de": serie[-meses * 2][0], "ate": serie[-1][0]}
