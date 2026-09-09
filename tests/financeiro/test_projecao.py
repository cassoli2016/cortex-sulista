"""Projeção de caixa — a parte PURA, sem banco.

As entradas aqui reproduzem o que foi MEDIDO no ERP em 09/09/2026, porque é
disso que as regras saíram:

curva de lançamento (mediana de 12 meses de vencimento fechados, por dia
relativo ao dia 1º do mês de vencimento):

    natureza            D-90   D-60   D-30    D+0   D+10   D+20   D+30
    Dívida financeira     35%    51%    65%    92%    92%    95%   100%
    Tributos              35%    36%    39%    42%    69%    78%    90%
    Operacional            9%    10%    15%    52%    77%    91%    99%
    Pessoal                0%     0%     0%     2%    56%    89%    96%

e o efeito disso no saldo (R$ mil, contas a pagar por vencimento):

    mês              mar-ago (fechados)   out/26   nov/26   dez/26
    TOTAL               11.659 a 13.109    3.181    1.897    1.851
"""
from __future__ import annotations

from datetime import date

from api.financeiro import projecao as pj


# ---------------------------------------------------------------- fixtures

def _hist(meses, natureza_tipo, valor_mes, dias_lanc, dia_venc=15):
    """Histórico no formato de `HIST_PAGAR_SQL`.

    `dias_lanc` é a lista de (dia_rel, fração) que descreve COMO aquela
    natureza escritura — é o que a curva de completude tem de recuperar.
    """
    linhas = []
    for mes in meses:
        for dia_rel, frac in dias_lanc:
            linhas.append({"mes": mes, "tipo": natureza_tipo,
                           "dia_venc": dia_venc - 1, "dia_rel": dia_rel,
                           "valor": valor_mes * frac})
    return linhas


MESES12 = [f"2025-{m:02d}" for m in range(9, 13)] + [f"2026-{m:02d}" for m in range(1, 9)]

# "FOLHA DE PAGAMENTO" cai em Pessoal; "FORNECEDOR" cai em Operacional;
# "ICMS" em Tributos. Os rótulos são os do ERP, e `_natureza` os classifica —
# usar os rótulos reais é o que faz o teste exercitar a classificação junto.
T_PESSOAL, T_OPER, T_TRIB = "FOLHA DE PAGAMENTO", "FORNECEDOR", "ICMS A RECOLHER"


def test_curva_recupera_a_escrituracao_de_cada_natureza():
    """Pessoal não é lançada antes do mês; Operacional entra durante ele."""
    hist = (_hist(MESES12, T_PESSOAL, 1_000_000, [(5, 0.56), (15, 0.33), (25, 0.11)])
            + _hist(MESES12, T_OPER, 9_000_000, [(-60, 0.10), (0, 0.42), (15, 0.40), (25, 0.08)]))
    curva = pj.curva_completude(hist)
    # no dia 1º do mês (dia_rel = 0) a folha ainda não existe
    assert pj.completude_em(curva, "Pessoal", 0) < 0.05
    # e o operacional já está por volta da metade
    assert 0.4 < pj.completude_em(curva, "Operacional", 0) < 0.65
    # cascata: natureza desconhecida cai no global, nunca em 1,0 calado
    assert pj.completude_em(curva, "Inexistente", 0) == pj.completude_em(curva, "global", 0)


def test_completude_fora_da_faixa_nao_extrapola():
    hist = _hist(MESES12, T_OPER, 1_000, [(0, 1.0)])
    curva = pj.curva_completude(hist)
    assert pj.completude_em(curva, "Operacional", -9999) == 0.0
    assert pj.completude_em(curva, "Operacional", 9999) == 1.0


def test_fracao_restante_mede_o_que_ainda_vence():
    """No dia 9, restam ~82% das saídas do mês (medido em 12 meses)."""
    por_mes = {m: {5: 20.0, 10: 30.0, 20: 30.0, 28: 20.0} for m in MESES12}
    assert pj.fracao_restante(por_mes, 1) == 1.0
    assert abs(pj.fracao_restante(por_mes, 9) - 0.80) < 0.01
    assert abs(pj.fracao_restante(por_mes, 25) - 0.20) < 0.01
    # sem história a resposta é o mês inteiro: errar para a saída MAIOR é o
    # lado seguro
    assert pj.fracao_restante({}, 15) == 1.0


# ------------------------------------------------------------- as decisões

def _cenario(hoje=date(2026, 9, 9)):
    """Base realista: folha nunca antecipada, operacional durante o mês."""
    hist = (_hist(MESES12, T_PESSOAL, 1_000_000, [(5, 0.56), (15, 0.33), (25, 0.11)], dia_venc=5)
            + _hist(MESES12, T_OPER, 9_000_000, [(-60, 0.10), (0, 0.42), (15, 0.40), (25, 0.08)])
            + _hist(MESES12, T_TRIB, 1_000_000, [(-90, 0.35), (0, 0.07), (15, 0.35), (25, 0.23)]))
    return hist, hoje


def test_pessoal_de_mes_futuro_e_projetada_por_inteiro():
    """Completude 0% até o dia 1º: não projetar apagaria a folha inteira do
    mês. É metade do defeito que esta tela existe para corrigir."""
    hist, hoje = _cenario()
    linhas = pj.projetar_saidas(hist, {}, ["2026-12"], hoje, hist_longo=hist)
    pes = next(n for n in linhas[0]["naturezas"] if n["natureza"] == "Pessoal")
    assert pes["lancado"] == 0.0
    assert pes["a_lancar"] > 700_000, pes
    assert pes["metodo"] == "nivel"


def _divida_bimodal(meses, valor_mes=1_200_000):
    """Dívida financeira com a forma REAL: bimodal.

    São duas populações no mesmo rótulo — parcela de financiamento agendada
    com anos de antecedência (quase tudo já lançado em D-180) e dívida lançada
    perto do vencimento. Meses diferentes têm misturas diferentes, e é isso que
    produz a dispersão de 0,17 a 0,24 medida no ERP.

    O dublê PRECISA ter essa forma: com uma distribuição idêntica em todos os
    meses a dispersão dá zero, `pode_dividir` autoriza, e o teste passaria sem
    exercitar a regra que ele existe para provar.
    """
    linhas = []
    for i, mes in enumerate(meses):
        cedo = 0.85 if i % 2 == 0 else 0.10       # mês "agendado" × mês "tardio"
        for dia_rel, frac in ((-180, cedo), (0, (1 - cedo) * 0.6),
                              (20, (1 - cedo) * 0.4)):
            linhas.append({"mes": mes, "tipo": "FINANCIAMENTO BANCO",
                           "dia_venc": 9, "dia_rel": dia_rel,
                           "valor": valor_mes * frac})
    return linhas


def test_divida_ja_lancada_no_futuro_nao_e_duplicada():
    """A outra metade do defeito: Dívida financeira já vem lançada com anos de
    antecedência, e a curva dela é BIMODAL.

    Dividir 1,157 mi pela completude mediana de 35% projetava R$ 3,3 mi de
    dívida para dezembro — quase três vezes o que o ERP já sabia daquele mês.
    O que barra isso é a dispersão: `disp/comp` = 0,49, acima do teto.
    """
    hist, hoje = _cenario()
    hist = hist + _divida_bimodal(MESES12)
    lancado = {"2026-12": {"Dívida financeira": 1_157_000.0}}
    linhas = pj.projetar_saidas(hist, lancado, ["2026-12"], hoje, hist_longo=hist)
    div = next(n for n in linhas[0]["naturezas"] if n["natureza"] == "Dívida financeira")
    assert div["metodo"] == "nivel", div       # NÃO dividiu pela curva
    assert div["previsto"] <= div["lancado"] * 1.15, div
    assert div["a_lancar"] < div["lancado"] * 0.15, div


def test_curva_confiavel_continua_dividindo():
    """O guard da dispersão não pode desligar o método da curva para todo
    mundo.

    Quem sobrevive a ele é a natureza PRÉ-LANÇADA e regular: Tributos já tem
    35% no ERP noventa dias antes do vencimento (é o parcelamento em curso),
    com dispersão de 0,11 — 0,11/0,35 = 0,31, abaixo do teto. Aí ancorar no
    próprio mês vale mais que a média histórica, porque o ERP já sabe alguma
    coisa DAQUELE mês.

    Operacional em mês futuro NÃO entra aqui, e é correto: a completude dele a
    30 dias do vencimento é 15%, abaixo do piso. Dividir por 0,15 faria um
    título a mais virar meio milhão de projeção.
    """
    hist, hoje = _cenario()
    # jitter entre meses, como o Tributos real (dispersão ~0,11)
    for i, r in enumerate(hist):
        if r["tipo"] == T_TRIB and r["dia_rel"] == -90:
            r["valor"] *= 1.0 + 0.10 * ((i % 3) - 1)
    lancado = {"2026-12": {"Tributos": 480_000.0}}
    linha = pj.projetar_saidas(hist, lancado, ["2026-12"], hoje, hist_longo=hist)[0]
    trib = next(n for n in linha["naturezas"] if n["natureza"] == "Tributos")
    assert trib["metodo"] == "curva", trib
    assert trib["previsto"] > trib["lancado"] * 2, trib
    # e a discordância entre os dois estimadores é PUBLICADA, não escolhida
    # em silêncio
    assert trib["divergencia"] is not None


def test_pode_dividir_e_a_razao_entre_dispersao_e_completude():
    """A regra em si, nos valores medidos no ERP."""
    assert pj.pode_dividir(0.52, 0.06)      # Operacional em D+0
    assert pj.pode_dividir(0.92, 0.22)      # Dívida financeira em D+0
    assert not pj.pode_dividir(0.35, 0.17)  # Dívida financeira em D-90
    assert not pj.pode_dividir(0.15, 0.01)  # completude abaixo do piso


def test_previsto_nunca_fica_abaixo_do_lancado():
    """O lançado é FATO. Previsão abaixo dele seria negar o que já existe."""
    hist, hoje = _cenario()
    lancado = {"2026-12": {"Operacional": 30_000_000.0}}
    linhas = pj.projetar_saidas(hist, lancado, ["2026-12"], hoje, hist_longo=hist)
    op = next(n for n in linhas[0]["naturezas"] if n["natureza"] == "Operacional")
    assert op["previsto"] >= 30_000_000.0
    assert op["a_lancar"] == 0.0


def test_mes_corrente_conta_so_o_que_ainda_nao_venceu():
    """O saldo de partida já contém o começo do mês. Projetar o mês inteiro
    somaria de novo a metade que já aconteceu."""
    hist, hoje = _cenario(date(2026, 9, 25))
    corrente = pj.projetar_saidas(hist, {}, ["2026-09"], hoje, hist_longo=hist)[0]
    futuro = pj.projetar_saidas(hist, {}, ["2026-12"], hoje, hist_longo=hist)[0]
    assert corrente["previsto"] < futuro["previsto"] * 0.5, (corrente, futuro)
    assert all(n["metodo"] == "parcial" for n in corrente["naturezas"])
    # e a folha, que vence no dia 5, já saiu por inteiro no dia 25
    pes = next(n for n in corrente["naturezas"] if n["natureza"] == "Pessoal")
    assert pes["resto_do_mes"] < 0.05, pes


def test_dda_vira_piso_quando_supera_o_modelo():
    """Boleto registrado é obrigação, não palpite: quando o medido supera o
    estimado, quem está errado é o modelo."""
    hist, hoje = _cenario()
    lancado = {"2026-10": {"Operacional": 8_000_000.0}}
    sem = pj.projetar_saidas(hist, lancado, ["2026-10"], hoje, hist_longo=hist)[0]
    com = pj.projetar_saidas(hist, lancado, ["2026-10"], hoje,
                             piso_dda={"2026-10": sem["a_lancar"] + 5_000_000.0},
                             hist_longo=hist)[0]
    assert com["dda_manda"] is True
    assert com["a_lancar"] == sem["a_lancar"] + 5_000_000.0
    assert com["previsto"] == com["lancado"] + com["a_lancar"]
    # e quando o DDA é MENOR que o estimado, o modelo continua mandando —
    # senão o piso viraria teto e a projeção encolheria com o dado novo
    menor = pj.projetar_saidas(hist, lancado, ["2026-10"], hoje,
                              piso_dda={"2026-10": 1.0}, hist_longo=hist)[0]
    assert menor["dda_manda"] is False
    assert menor["a_lancar"] == sem["a_lancar"]


def test_natureza_residual_nao_e_projetada():
    """'Migração de saldo' apareceu em 1 dos 12 meses da base, com R$ 21 mil.
    Projetada por nível virava despesa mensal para sempre — descrevendo um
    evento de implantação que não vai acontecer de novo."""
    hist, hoje = _cenario()
    hist = hist + [{"mes": "2026-03", "tipo": "IMPLANTACAO DE SALDO",
                    "dia_venc": 14, "dia_rel": 0, "valor": 21_000.0}]
    linhas = pj.projetar_saidas(hist, {}, ["2026-12"], hoje, hist_longo=hist)
    mig = next((n for n in linhas[0]["naturezas"]
                if n["natureza"] == "Migração de saldo"), None)
    assert mig is None or mig["previsto"] == 0.0, mig


def test_confianca_separa_o_lancado_do_estimado():
    hist, hoje = _cenario()
    linhas = pj.projetar_saidas(hist, {"2026-10": {"Operacional": 3_000_000.0}},
                                ["2026-10", "2026-12"], hoje, hist_longo=hist)
    assert 0.0 < linhas[0]["confianca"] < 1.0
    assert linhas[1]["confianca"] == 0.0   # nada lançado em dez
    assert linhas[0]["previsto"] == linhas[0]["lancado"] + linhas[0]["a_lancar"]


# ------------------------------------------------------- as duas necessidades

def _linhas(resultados, saldo0=0.0):
    saidas, entradas = [], []
    for i, r in enumerate(resultados):
        mes = f"2026-{i + 9:02d}" if i < 4 else f"2027-{i - 3:02d}"
        saidas.append({"mes": mes, "rotulo": mes, "lancado": 0.0, "a_lancar": 0.0,
                       "previsto": 1_000_000.0, "por_nivel": 0.0, "dda": 0.0,
                       "dda_manda": False, "confianca": 0.5, "naturezas": []})
        entradas.append({"mes": mes, "rotulo": mes, "lancado": 0.0,
                         "previsto": 1_000_000.0 + r, "a_faturar": 0.0,
                         "confianca": 0.5})
    return pj.montar(saidas, entradas, saldo0)


def test_necessidade_do_mes_e_a_acumulada_sao_numeros_diferentes():
    """Confundi-las leva a decisão errada: a do mês se resolve antecipando
    recebível, a acumulada não — antecipar traz o dinheiro de depois para hoje
    e deixa o depois vazio."""
    linhas, k = _linhas([-500_000, -500_000, -500_000, -500_000])
    assert k["necessidade_mensal"] == 500_000
    assert k["necessidade"] == 2_000_000        # o buraco SOMA
    assert k["meses_negativos"] == 4
    assert k["queima_media"] == -500_000


def test_mes_bom_no_meio_nao_apaga_a_necessidade_mensal():
    linhas, k = _linhas([+300_000, -900_000, +300_000, +300_000])
    assert k["necessidade_mensal"] == 900_000
    assert k["pior_mes_resultado"] == "2026-10"
    # e o ACUMULADO continua acusando o vale, mesmo com os meses bons depois:
    # saldo encadeado 300k -> -600k -> -300k -> 0. O pior ponto e' -600k, e e'
    # nele que o caixa precisa de dinheiro — o fato de o ano fechar em zero nao
    # paga a conta de outubro.
    assert k["necessidade"] == 600_000


def test_saldo_encadeia_e_a_necessidade_e_o_pior_ponto():
    linhas, k = _linhas([-400_000, +100_000, -400_000], saldo0=500_000)
    assert [l["saldo_final"] for l in linhas] == [100_000, 200_000, -200_000]
    assert k["necessidade"] == 200_000
    assert k["primeiro_negativo"] == linhas[2]["rotulo"]


# --------------------------------------------------------------- entradas

def test_recebimento_e_deslocado_pelo_dso():
    """Com DSO de ~60 dias, o caixa de novembro é o faturamento de setembro."""
    serie = [(f"2024-{m:02d}", 10_000_000.0) for m in range(1, 13)]
    serie += [(f"2025-{m:02d}", 10_000_000.0) for m in range(1, 13)]
    serie += [(f"2026-{m:02d}", 10_000_000.0) for m in range(1, 9)]
    linhas, ix, nivel, desloc = pj.projetar_entradas(
        serie, {}, ["2026-11"], dso=60.0, hoje=date(2026, 9, 9))
    assert desloc == 2
    assert linhas[0]["origem_faturamento"] == "2026-09"


def test_recebivel_lancado_manda_quando_e_maior():
    """No curto prazo o recebível é FATO e a previsão é modelo."""
    serie = [(f"2025-{m:02d}", 1_000_000.0) for m in range(1, 13)]
    serie += [(f"2026-{m:02d}", 1_000_000.0) for m in range(1, 9)]
    linhas, *_ = pj.projetar_entradas(serie, {"2026-10": 5_000_000.0}, ["2026-10"],
                                      dso=30.0, hoje=date(2026, 9, 9))
    assert linhas[0]["previsto"] == 5_000_000.0
    assert linhas[0]["a_faturar"] == 0.0
    assert linhas[0]["confianca"] == 1.0


# ------------------------------------------- o detalhe de um mes (parte pura)

def test_fim_do_mes_acerta_fevereiro_e_bissexto():
    """O detalhe recorta ate o ultimo dia do mes, e somar 30 dias erraria em
    quatro meses do ano — inclusive fevereiro, que tem a folha inteira."""
    assert pj._fim_do_mes("2026-02") == date(2026, 2, 28)
    assert pj._fim_do_mes("2028-02") == date(2028, 2, 29)   # bissexto
    assert pj._fim_do_mes("2026-11") == date(2026, 11, 30)
    assert pj._fim_do_mes("2026-12") == date(2026, 12, 31)


def test_o_detalhe_reusa_o_motor_da_tabela():
    """O detalhe NAO pode ter conta propria.

    Duas implementacoes do mesmo numero divergem no primeiro dia em que alguem
    mexe numa so — e o sintoma seria a tela dizendo R$ 10,3 mi na linha e outro
    valor no modal que a linha abriu, que e o defeito que mais custa confianca.
    Este guard le a fonte de `get_detalhe` e cobra a chamada a `projetar_saidas`.

    A FONTE SAI DO DISCO, por `ast`, e nao de `inspect.getsource(pj.get_detalhe)`:
    o `@cached` da casa nao usa `functools.wraps`, entao o que o `inspect`
    devolve e o corpo do WRAPPER — tres linhas de cache que nunca conteriam
    `projetar_saidas`. Escrito assim, o guard ficaria vermelho para sempre; com
    a assercao invertida, ficaria VERDE para sempre. Pego na bancada.
    """
    import ast
    import pathlib
    arq = pathlib.Path(pj.__file__)
    arvore = ast.parse(arq.read_text(encoding="utf-8"))
    alvo = next((n for n in arvore.body
                 if isinstance(n, ast.FunctionDef) and n.name == "get_detalhe"), None)
    assert alvo is not None, "get_detalhe sumiu de projecao.py"
    fonte = ast.get_source_segment(arq.read_text(encoding="utf-8"), alvo) or ""
    assert "projetar_saidas(" in fonte, (
        "o detalhe passou a calcular por conta propria; ele tem de reusar o "
        "mesmo motor da tabela")
    # e nao pode ter reimplementado a mediana do nivel por dentro
    assert "statistics." not in fonte, fonte[:200]


def test_todo_duble_cobre_as_colunas_da_consulta_real():
    """Duble com MENOS campos que a fonte nao testa contra a fonte.

    Ele testa contra o que o codigo de hoje por acaso usa — e no dia em que
    alguem passa a ler uma coluna nova, o caminho novo nunca e exercitado.
    O sintoma e mudo, porque `.get()` e `row["x"]` sobre um dict de teste
    completo nunca levantam: a tela mostra "—" e nenhum teste acende.

    Esta armadilha foi encontrada em 09/09/2026 numa frente vizinha (um duble
    do ERP sem a coluna `emissao`, que a consulta tinha ganhado); a varredura
    abaixo e a generalizacao dela. Ela sai da CONSULTA, nao de uma lista
    escrita a mao — consulta que ganha coluna cobra o duble sozinha.
    """
    import re
    from api.financeiro import dda as dda_mod

    from tests.financeiro import test_dda as td

    casos = [
        ("HIST_PAGAR_SQL", pj.HIST_PAGAR_SQL,
         _hist(["2026-01"], T_OPER, 100.0, [(0, 1.0)])[0]),
        ("ERP_TITULOS_SQL", dda_mod.ERP_TITULOS_SQL,
         td._titulo("111", date(2026, 1, 1), 10.0)),
    ]
    assert casos, "varredura vazia"
    for nome, sql, duble in casos:
        colunas = set(re.findall(r"AS (\w+)", sql))
        assert colunas, f"{nome}: nenhuma coluna encontrada — o padrao parou de casar"
        falta = colunas - set(duble)
        assert not falta, (
            f"{nome} devolve {sorted(colunas)} e o duble do teste nao tem "
            f"{sorted(falta)} — o caminho dessas colunas nunca e exercitado")
