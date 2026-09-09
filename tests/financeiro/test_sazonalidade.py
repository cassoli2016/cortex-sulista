"""Nível e sazonalidade — e a razão de o método antigo não servir.

O TESTE QUE MANDA neste arquivo é `test_indice_sobrevive_a_perda_de_cliente`.
Ele reproduz o que aconteceu de verdade: a casa perdeu em 2026 um cliente que
respondia por 15 a 17% do faturamento, zerado a partir de abril. (Nome e CNPJ
ficam fora — o repositório é público, e o que o teste precisa é do DEGRAU.)

Com "média do mês ÷ média geral" — o método que `queries._previsao_sazonal`
usa — um degrau de nível vira sazonalidade falsa: cada mês-calendário carrega
quantos anos "altos" e quantos "baixos" caíram nele, e o índice passa a medir
QUANDO o mês foi observado. Medido na série real (fev/2023 a ago/2026):

    out  1,206 pelo método antigo contra 1,083 pelo novo  (+10,3%)
    nov  1,049 contra 0,959                               (+8,6%)
    dez  0,898 contra 0,807                               (+10,2%)

Dez por cento a mais de entrada esperada em três meses seguidos, no horizonte
em que a decisão é "preciso antecipar recebível?".
"""
from __future__ import annotations

import statistics

from api.financeiro import sazonalidade as saz


def _serie(meses: int, nivel_por_mes, sazonal=None, inicio=(2022, 1)):
    """Série sintética [(AAAA-MM, valor)]. `nivel_por_mes` é função do índice
    absoluto do mês; `sazonal` é dict {1..12: fator}."""
    sazonal = sazonal or {}
    ano, mes = inicio
    saida = []
    for i in range(meses):
        v = nivel_por_mes(i) * sazonal.get(mes, 1.0)
        saida.append((f"{ano:04d}-{mes:02d}", v))
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    return saida


# O padrão real medido no faturamento da casa: dezembro e janeiro fracos,
# agosto e abril fortes. Literal, e não derivado do código que vai lê-lo.
SAZONAL_REAL = {1: 0.86, 2: 0.89, 3: 1.04, 4: 1.14, 5: 1.01, 6: 0.99,
                7: 1.12, 8: 1.17, 9: 1.08, 10: 1.08, 11: 0.96, 12: 0.81}


def test_indice_recupera_o_padrao_conhecido():
    """Sem degrau nenhum, o índice tem de devolver o que foi plantado."""
    serie = _serie(48, lambda i: 10_000_000.0, SAZONAL_REAL)
    r = saz.indice_sazonal(serie)
    assert r["metodo"] == "razao_media_movel"
    # dezembro e janeiro continuam sendo os dois menores, e agosto o maior
    ordem = sorted(range(1, 13), key=lambda m: r["indice"][m])
    assert set(ordem[:2]) == {12, 1}, r["indice"]
    assert ordem[-1] == 8, r["indice"]


def test_indice_sobrevive_a_perda_de_cliente():
    """O degrau de nível NÃO pode virar sazonalidade.

    Série de 48 meses com o mesmo padrão sazonal o tempo todo, e um corte de
    16% no nível a partir do mês 39 (a saída do cliente). O índice depois do
    corte tem de continuar descrevendo a estação — e o método antigo, medido
    aqui lado a lado, não continua.
    """
    corte = 39
    serie = _serie(48, lambda i: 12_000_000.0 * (0.84 if i >= corte else 1.0),
                   SAZONAL_REAL)
    novo = saz.indice_sazonal(serie)["indice"]

    def antigo(serie):
        """`queries._previsao_sazonal`, reescrito aqui em três linhas: média do
        mês-calendário dividida pela média geral."""
        geral = sum(v for _, v in serie) / len(serie)
        por_mes: dict[int, list[float]] = {}
        for mes, v in serie:
            por_mes.setdefault(int(mes[5:7]), []).append(v)
        return {m: (sum(v) / len(v)) / geral for m, v in por_mes.items()}

    velho = antigo(serie)
    # O erro de cada método contra o padrão que foi plantado, normalizado (o
    # índice é relativo: o que importa é a FORMA, não a escala).
    def _erro(ix):
        med = sum(ix[m] for m in range(1, 13)) / 12
        alvo = sum(SAZONAL_REAL.values()) / 12
        return sum(abs(ix[m] / med - SAZONAL_REAL[m] / alvo) for m in range(1, 13))

    assert _erro(novo) < _erro(velho), (
        "o método novo deveria descrever melhor a estação depois de um degrau "
        f"de nível; erro novo={_erro(novo):.3f} velho={_erro(velho):.3f}")
    # E por uma margem GRANDE, não por arredondamento: é isso que justifica o
    # módulo existir. Medido neste cenário: 0,063 contra 0,175 — 2,8 vezes.
    # O limiar é 2× para o teste não quebrar com um ajuste fino do
    # amortecimento, e ainda assim reprovar se o método novo deixar de separar
    # nível de estação.
    assert _erro(velho) > 2 * _erro(novo), (
        f"erro novo={_erro(novo):.3f} velho={_erro(velho):.3f}")


def test_dispersao_alta_amortece_o_indice():
    """Mês-calendário cujas observações discordam entre si não afirma estação.

    Dezembro alterna 0,55 e 1,45 de ano para ano — média 1,0 com dispersão
    enorme. O índice tem de ficar PERTO de 1,0, e não escolher um dos dois.
    """
    def nivel(i):
        return 10_000_000.0

    serie = []
    ano, mes = 2022, 1
    for i in range(48):
        f = 1.0
        if mes == 12:
            f = 0.55 if (ano % 2 == 0) else 1.45
        serie.append((f"{ano:04d}-{mes:02d}", nivel(i) * f))
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    r = saz.indice_sazonal(serie)
    assert r["dispersao"][12] > saz.DISPERSAO_NEUTRA * 0.5, r["dispersao"][12]
    assert abs(r["indice"][12] - 1.0) < 0.20, r["indice"][12]


def test_serie_curta_devolve_neutro_e_diz_que_e_neutro():
    """Menos que o mínimo NÃO inventa índice — e avisa, para a tela poder
    dizer 'não há história para afirmar estação' em vez de mostrar 1,00 com
    cara de medição."""
    r = saz.indice_sazonal(_serie(10, lambda i: 1_000_000.0, SAZONAL_REAL))
    assert r["metodo"] == "neutro"
    assert all(r["indice"][m] == 1.0 for m in range(1, 13))


def test_nivel_usa_a_mediana_dos_seis_ultimos_dessazonalizada():
    """Um mês atípico não pode mover o nível, e a estação dos 6 últimos não
    pode inflá-lo."""
    serie = _serie(48, lambda i: 10_000_000.0, SAZONAL_REAL)
    ix = saz.indice_sazonal(serie)["indice"]
    n = saz.nivel(serie, ix, 6)
    assert abs(n - 10_000_000.0) / 10_000_000.0 < 0.06, n
    # um outlier de 5x no último mês não move a mediana
    serie_out = serie[:-1] + [(serie[-1][0], serie[-1][1] * 5)]
    assert abs(saz.nivel(serie_out, ix, 6) - n) / n < 0.02


def test_nivel_acompanha_o_degrau_sem_ninguem_cadastrar_nada():
    """É a janela curta que faz a perda de cliente entrar sozinha."""
    serie = _serie(48, lambda i: 12_000_000.0 * (0.84 if i >= 40 else 1.0),
                   SAZONAL_REAL)
    ix = saz.indice_sazonal(serie)["indice"]
    n = saz.nivel(serie, ix, 6)
    assert abs(n - 12_000_000.0 * 0.84) / (12_000_000.0 * 0.84) < 0.08, n


def test_quebra_de_nivel_acusa_o_degrau_e_cala_no_ruido():
    serie = _serie(48, lambda i: 12_000_000.0 * (0.84 if i >= 42 else 1.0),
                   SAZONAL_REAL)
    ix = saz.indice_sazonal(serie)["indice"]
    q = saz.quebra_de_nivel(serie, ix, 6)
    assert q is not None and q["variacao"] < -0.08, q

    # série sem degrau: silêncio. Aviso que acende sempre não é aviso.
    plana = _serie(48, lambda i: 12_000_000.0, SAZONAL_REAL)
    assert saz.quebra_de_nivel(plana, saz.indice_sazonal(plana)["indice"], 6) is None


def test_indice_nao_multiplica_o_ano_inteiro():
    """A normalização existe para isto: numa série em QUEDA todo mês supera a
    média móvel (que já caiu), e sem normalizar os 12 índices ficariam acima de
    1,0 — multiplicando o nível e inflando o ano."""
    serie = _serie(48, lambda i: 20_000_000.0 * (0.985 ** i), SAZONAL_REAL)
    ix = saz.indice_sazonal(serie)["indice"]
    observados = [ix[m] for m in range(1, 13)]
    assert abs(statistics.mean(observados) - 1.0) < 0.02, observados


# =========================================================================
# A TELA `fluxo` — `queries._previsao_sazonal` delega para este módulo desde
# 09/09/2026. Os testes abaixo guardam a troca pelo COMPORTAMENTO, não pela
# implementação: o que se afirma é o que o método antigo errava.
# =========================================================================

def _hist(serie):
    """No formato de `SAZONAL_SQL`: mes, mnum, valor."""
    return [{"mes": m, "mnum": int(m[5:7]), "valor": v} for m, v in serie]


def test_o_mes_de_IMPLANTACAO_nao_derruba_o_indice_do_mes_calendario():
    """O defeito mais caro que o método antigo tinha, e o mais invisível.

    Janeiro de 2023 — o primeiro mês do sistema — faturou R$ 5 mil, contra
    R$ 9,9 mi, R$ 12,4 mi e R$ 10,8 mi dos três janeiros seguintes. O método
    antigo tirava a MÉDIA dos quatro e derrubava o índice de janeiro de 0,906
    para 0,728: vinte por cento a menos, todo ano, no mês seguinte ao aperto de
    dezembro.

    Não foi preciso tratar esse mês como caso especial. Ele fica de fora
    sozinho, porque a razão sobre média móvel exige doze meses centrados e o
    quarto mês de uma série não tem janela — o método recusa opinar sobre o
    que não consegue medir.
    """
    from api import queries as q
    serie = []
    ano, mes = 2022, 10
    for i in range(47):
        if (ano, mes) == (2023, 1):
            v = 4_765.0                      # a implantação
        else:
            v = 11_000_000.0 * SAZONAL_REAL[mes]
        serie.append((f"{ano:04d}-{mes:02d}", v))
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1

    prever, metodo = q._previsao_sazonal(_hist(serie), fallback=1.0)
    assert metodo == "sazonal"
    # O índice de janeiro tem de descrever os janeiros NORMAIS. A banda é de
    # 8%: medido neste cenário, o método novo acerta a razão jan/ago em +0,0%
    # e o antigo erra −25,0%. A primeira versão deste teste usava ±25% e
    # passava com o método ANTIGO por dois décimos de milésimo — verde que
    # nunca ficaria vermelho, pego ao sabotar.
    razao = (prever(1) / prever(8)) / (SAZONAL_REAL[1] / SAZONAL_REAL[8])
    assert 0.92 < razao < 1.08, razao

    # e o método antigo, na mesma série, erra feio — é o que justifica a troca
    geral = sum(v for _, v in serie) / len(serie)
    por_mes: dict[int, list[float]] = {}
    for m, v in serie:
        por_mes.setdefault(int(m[5:7]), []).append(v)
    velho = {m: (sum(v) / len(v)) / geral for m, v in por_mes.items()}
    esperado = SAZONAL_REAL[1] / (sum(SAZONAL_REAL.values()) / 12)
    assert velho[1] < esperado * 0.85, (velho[1], esperado)


def test_serie_curta_cai_no_runrate_e_DIZ_que_caiu():
    """Rótulo "sazonal" sobre um índice neutro seria um run-rate se passando
    por outra coisa — e a tela mostra esse rótulo para quem lê o número."""
    from api import queries as q
    curta = [(f"2026-{m:02d}", 10_000_000.0) for m in range(1, 7)]
    prever, metodo = q._previsao_sazonal(_hist(curta), fallback=9_000_000.0)
    assert metodo == "runrate"
    assert prever(1) == 9_000_000.0


def test_a_previsao_da_tela_fluxo_usa_a_MEDIANA_do_nivel():
    """Um mês atípico não pode mover a previsão do ano inteiro. O método antigo
    usava média — e média com um mês fora da curva entra inteira."""
    from api import queries as q
    serie = []
    ano, mes = 2022, 10
    for _ in range(47):
        serie.append((f"{ano:04d}-{mes:02d}", 10_000_000.0 * SAZONAL_REAL[mes]))
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    normal, _ = q._previsao_sazonal(_hist(serie), 1.0)
    # o último mês fechado triplica (venda de ativo, acordo, lote de tributo)
    com_outlier = serie[:-1] + [(serie[-1][0], serie[-1][1] * 3)]
    outlier, _ = q._previsao_sazonal(_hist(com_outlier), 1.0)
    assert abs(outlier(5) - normal(5)) / normal(5) < 0.05, (outlier(5), normal(5))
