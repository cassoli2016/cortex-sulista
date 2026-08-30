"""Custo de folha por natureza — e o que o total de proventos não é.

O DEFEITO QUE ISTO CONSERTA
===========================
A tela somava `tipoeven='P'` e chamava de custo. Medido, esse número carrega
eventos de CIRCULAÇÃO: `ADIANTAMENTO DE SALARI` sai como provento
(R$ 3.460.109 em 12 meses) e `ADIANTAMENTO QUINZENAL` volta como desconto
(R$ 3.463.158). É a MESMA quinzena, e bate centavo a centavo em 9 de 13 meses.
Somá-la é contar o salário duas vezes — 14,2% do total.

O QUE NÃO SE INVENTA
====================
O encargo patronal não está na ficha; só as bases estão. FGTS é calculável
(8% fixados em lei, iguais para todo regime) e entra com a alíquota dita. INSS
patronal NÃO: a alíquota depende do enquadramento e há eventos de SIMPLES na
ficha, onde o patronal está dentro do DAS. Estimar 20% somaria ~R$ 2,8 milhões
inventados. É a regra das multas: dizer que não dá para medir é a resposta.

O BUG QUE A MEDIÇÃO PEGOU
=========================
A primeira classificação jogou **R$ 3,25 milhões em "Outros"** — 13,4% do
custo, o terceiro maior balde. Causa: `_sem_acento` faz `.upper()`, então o
"o" de "13o" chega como "O", e o padrão estava em minúscula. O 13º salário
inteiro virava categoria sem nome. Depois do conserto, "Outros" caiu para 1,1%.
"""
from __future__ import annotations

from api.rh import folha_estrutura as fe


# ── a classificação ─────────────────────────────────────────────────────────


def test_o_13o_e_reconhecido_APESAR_do_upper():
    """O bug que custou R$ 3,25 milhões em "Outros": o `.upper()` transforma
    "13o" em "13O", e o padrão em minúscula não casava."""
    for ev in ("2A PARCELA DE 13o SALA", "1A PARCELA DE 13o SALA",
               "13o SALARIO PROPORCION", "MEDIA VALOR 13o",
               "ADIANTAMENTO DE 13o SA"):
        assert fe.natureza(ev) == "13º salário", ev


def test_a_ORDEM_das_naturezas_importa():
    """"DSR HORAS EXTRAS 50%" é hora extra, não DSR genérico. E "1/3 MEDIA DE
    FERIAS" é férias, não média de salário — `MEDIA` fica por último de
    propósito, como rede e não como primeira peneira."""
    assert fe.natureza("DSR HORAS EXTRAS 50%") == "Hora extra"
    assert fe.natureza("DSR H EXTRAS NOT 50%") == "Hora extra"
    assert fe.natureza("1/3 MEDIA DE FERIAS") == "Férias"
    assert fe.natureza("MEDIAS S/ VARIAVEIS -") == "Salário"


def test_evento_desconhecido_vai_para_OUTROS_e_nao_some():
    """Empurrá-lo para "Salário" o esconderia dentro do maior balde — que é
    como uma rubrica nova deixa de ser notada."""
    assert fe.natureza("EVENTO QUE NINGUEM VIU") == "Outros"


def test_as_familias_cobrem_os_eventos_de_verdade():
    esperado = {
        "SALARIO BASE": "Salário", "H.E 50%": "Hora extra",
        "H.E NOT 50%": "Hora extra", "ADICIONAL NOTURNO 20%": "Adicional noturno",
        "FERIAS NORMAIS": "Férias", "1/3 S/ REMUNERACAO DE": "Férias",
        "AVISO PREVIO INDENIZAD": "Rescisão", "SALDO DE SALARIO": "Rescisão",
        "DIARIAS PAGAS": "Diárias", "TOTAL DIARIAS MES": "Diárias",
        "PREMIO PRODUTIVIDADE": "Prêmio e PLR",
        "PLR - PARTICIPACAO DOS": "Prêmio e PLR",
        "PTS-PREMIO TEMPO DE SE": "Prêmio e PLR",
        "AJUDA DE CUSTO": "Ajuda de custo",
        "ATESTADO MEDICO": "Afastamento", "SALARIO MATERNIDADE": "Afastamento",
    }
    ruins = {ev: (fe.natureza(ev), q) for ev, q in esperado.items()
             if fe.natureza(ev) != q}
    assert not ruins, ruins


# ── a circulação ────────────────────────────────────────────────────────────


def test_o_ADIANTAMENTO_e_circulacao_e_sai_do_custo():
    assert fe.e_circulacao("ADIANTAMENTO DE SALARI") is True
    assert fe.e_circulacao("INSUFICIENCIA DE SALDO") is True
    assert fe.e_circulacao("SALARIO BASE") is False
    assert fe.e_circulacao("ADIANTAMENTO DE 13o SA") is False, (
        "o adiantamento de 13º é custo de verdade daquele mês, não circulação")


# ── a decomposição da variação ──────────────────────────────────────────────


def _mes(comp, custo, pessoas):
    return {"comp": comp, "custo_efetivo": custo, "pessoas": pessoas,
            "custo_medio": round(custo / pessoas, 2) if pessoas else None,
            "circulacao": 0.0, "proventos": custo, "descontos": 0.0,
            "naturezas": {}, "base_fgts": None, "base_inss": None, "fgts": None}


def test_a_variacao_separa_GENTE_de_CUSTO_MEDIO():
    """"O custo caiu" não decide nada. As duas parcelas têm donos diferentes:
    dimensionamento e composição salarial."""
    meses = [_mes("2025-08", 100000.0, 100), _mes("2026-08", 63000.0, 70)]
    v = fe.variacao(meses)
    assert v["delta"] == -37000.0
    # -30 pessoas × R$ 1.000 = -30.000 · 70 pessoas × -R$ 100 = -7.000
    assert v["por_pessoas"] == -30000.0
    assert v["por_custo_medio"] == -7000.0
    assert round(v["por_pessoas"] + v["por_custo_medio"], 2) == v["delta"]


def test_a_comparacao_prefere_o_MESMO_MES_do_ano_anterior():
    """Mês contra mês carregaria a sazonalidade do 13º — novembro e dezembro
    são estruturalmente maiores."""
    meses = [_mes("2025-08", 100000.0, 100), _mes("2026-07", 80000.0, 80),
             _mes("2026-08", 63000.0, 70)]
    v = fe.variacao(meses)
    assert v["de"] == "2025-08" and v["comparacao"] == "ano anterior"


def test_sem_o_mesmo_mes_cai_no_ANTERIOR_e_DIZ():
    meses = [_mes("2026-07", 80000.0, 80), _mes("2026-08", 63000.0, 70)]
    v = fe.variacao(meses)
    assert v["de"] == "2026-07" and v["comparacao"] == "mês anterior"


def test_sem_base_de_comparacao_devolve_None_em_vez_de_inventar():
    assert fe.variacao([_mes("2026-08", 100.0, 1)]) is None
    assert fe.variacao([]) is None


# ── o que não se calcula ────────────────────────────────────────────────────


def test_so_o_FGTS_tem_aliquota_aplicada():
    """8%, fixados em lei e iguais para todo regime. O INSS patronal depende do
    enquadramento — estimá-lo somaria milhões inventados ao custo."""
    assert fe.FGTS_ALIQUOTA == 0.08
    import inspect
    fonte = inspect.getsource(fe)
    assert "0.20" not in fonte and "0.2 " not in fonte, (
        "apareceu uma alíquota de patronal no módulo")
