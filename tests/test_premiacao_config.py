"""Configuração da premiação: parâmetros versionados e classificação.

Premiação decide dinheiro de gente, e a pergunta "por que recebi isso em
março?" sempre aparece — normalmente meses depois, quando quem configurou já
mudou o peso três vezes. Estes testes trancam o que faz essa pergunta ter
resposta.
"""
from __future__ import annotations

import pytest

from api.premiacao import classificacao as cl
from api.premiacao import config as cf


@pytest.fixture(autouse=True)
def esq(esquema_pg):
    cf.ESQUEMA = esquema_pg
    cl.ESQUEMA = esquema_pg
    try:
        yield esquema_pg
    finally:
        cf.ESQUEMA = None
        cl.ESQUEMA = None


def _eixos(peso=10, ativo=1):
    return {k: {"peso": peso, "ativo": ativo} for k in cf.EIXOS}


# ── versionamento ────────────────────────────────────────────────────────────


def test_sem_versao_a_tela_abre_com_os_padroes(esq):
    """Travar por falta de configuração esconderia justamente a configuração
    que falta fazer."""
    d = cf.ler("2026-08")
    assert d["padrao"] is True and d["versao"] is None
    assert d["params"] == cf.defaults()
    assert set(d["eixos"]) == set(cf.EIXOS)


def test_a_competencia_HERDA_a_ultima_versao_vigente(esq):
    """`<=` e não `=`: configurar uma vez em janeiro vale para o ano todo.
    Exigir uma versão por mês faria a premiação parar de calcular no primeiro
    mês em que alguém esquecesse."""
    cf.salvar("2026-01", cf.defaults(), _eixos(), esquema=esq)
    for comp in ("2026-01", "2026-02", "2026-12"):
        assert cf.ler(comp)["versao"]["vigente_de"] == "2026-01"
    # e uma versão nova passa a valer só DAQUI PARA A FRENTE
    cf.salvar("2026-06", {**cf.defaults(), "valor_por_km": 0.25},
              _eixos(), esquema=esq)
    assert cf.ler("2026-05")["params"]["valor_por_km"] == 0.10
    assert cf.ler("2026-06")["params"]["valor_por_km"] == 0.25


def test_configurar_agosto_NAO_mexe_em_julho(esq):
    """A regra que existe para a pergunta "por que paguei isso?" ter resposta."""
    cf.salvar("2026-07", {**cf.defaults(), "valor_por_km": 0.10},
              _eixos(), esquema=esq)
    cf.salvar("2026-08", {**cf.defaults(), "valor_por_km": 0.50},
              _eixos(), esquema=esq)
    assert cf.ler("2026-07")["params"]["valor_por_km"] == 0.10


def test_salvar_de_novo_no_mesmo_mes_ATUALIZA_em_vez_de_duplicar(esq):
    """Duas versões vigentes no mesmo mês seriam duas respostas para a mesma
    pergunta."""
    cf.salvar("2026-03", cf.defaults(), _eixos(), nota="primeira", esquema=esq)
    cf.salvar("2026-03", cf.defaults(), _eixos(), nota="segunda", esquema=esq)
    assert len(cf.versoes(esq)) == 1
    assert cf.ler("2026-03")["versao"]["nota"] == "segunda"


def test_parametro_novo_no_codigo_cai_no_padrao(esq):
    """Um deploy que acrescenta parâmetro não pode fazer versões antigas
    pararem de calcular."""
    cf.salvar("2026-01", {"valor_por_km": 0.20}, _eixos(), esquema=esq)
    p = cf.ler("2026-01")["params"]
    assert p["valor_por_km"] == 0.20
    assert p["km_minimo"] == cf.defaults()["km_minimo"]


# ── validação ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("params,trecho", [
    ({"valor_por_km": 0}, "maior que zero"),
    # -1 cai na faixa ANTES da regra do zero, e a mensagem dela e melhor:
    # diz qual e o intervalo aceito em vez de so dizer que esta errado
    ({"valor_por_km": -1}, "entre"),
    ({"nota_minima": 150}, "entre"),
    ({"km_minimo": -5}, "entre"),
    ({"valor_por_km": "abc"}, "número"),
])
def test_parametro_fora_da_faixa_e_RECUSADO(esq, params, trecho):
    """A mensagem tem de dizer QUAL parâmetro e QUAL faixa — recusa genérica
    manda a pessoa adivinhar."""
    with pytest.raises(ValueError) as e:
        cf.salvar("2026-01", {**cf.defaults(), **params}, _eixos(), esquema=esq)
    assert trecho in str(e.value)


def test_todos_os_eixos_desligados_e_RECUSADO(esq):
    with pytest.raises(ValueError, match="ao menos um eixo|Ao menos um eixo"):
        cf.salvar("2026-01", cf.defaults(), _eixos(ativo=0), esquema=esq)


def test_soma_de_pesos_zero_e_RECUSADA(esq):
    """Todos os eixos ativos com peso zero não dá divisão nenhuma."""
    with pytest.raises(ValueError, match="soma dos pesos"):
        cf.salvar("2026-01", cf.defaults(), _eixos(peso=0), esquema=esq)


def test_competencia_invalida_e_RECUSADA(esq):
    for ruim in ("2026", "2026-13", "agosto", ""):
        with pytest.raises(ValueError):
            cf.salvar(ruim, cf.defaults(), _eixos(), esquema=esq)


def test_eixo_com_peso_zero_NAO_e_o_mesmo_que_desligado(esq):
    """Zero é uma escolha ("mediu, não vale nota"); desligado é "não entra".
    A diferença importa ao ligar um eixo aos poucos — o número combinado não
    pode se perder no caminho."""
    e = _eixos()
    e["diesel"] = {"peso": 30, "ativo": 0}
    cf.salvar("2026-01", cf.defaults(), e, esquema=esq)
    lido = cf.ler("2026-01")["eixos"]["diesel"]
    assert lido["ativo"] == 0 and lido["peso"] == 30


# ── classificação de ocorrência ──────────────────────────────────────────────


def test_a_proposta_acerta_a_gravidade_da_multa():
    """O nome do tipo já carrega a gravidade; o peso sai dela e não de um
    número inventado."""
    g = cf and cl.propor("MULTA DE TRANSITO (INFRACAO GRAVISSIMA)")
    l = cl.propor("MULTA DE TRANSITO (INFRACAO LEVE)")
    assert g[0] == "demerito" and l[0] == "demerito"
    assert g[2] > l[2], "gravíssima tem de pesar mais que leve"


def test_a_proposta_casa_COM_E_SEM_acento():
    """O ERP escreve "MÉRITO POR AJUDAR À OPERAÇÃO"; a regra aqui está sem
    acento. Comparar cru fazia o tipo cair em não classificado, e nada
    acusava — foi assim que três tipos ficaram pendentes por engano."""
    assert cl.propor("MÉRITO POR AJUDAR À OPERAÇÃO")[0] == "merito"
    assert cl.propor("MERITO POR AJUDAR A OPERACAO")[0] == "merito"
    assert cl.propor("COLISÃO EM OBJETO DENTRO DE CLIENTE")[0] == "demerito"


def test_contratacao_de_agregado_e_NEUTRO():
    """É um terço das linhas e é registro de entrada. Como demérito, todo
    agregado novo nasceria penalizado."""
    classe, _, peso, _ = cl.propor("PONTOS DE CONTRATACAO NOVO AGREGADO")
    assert classe == "neutro" and peso == 0


def test_tipo_desconhecido_nasce_NAO_CLASSIFICADO_e_nao_neutro():
    """A diferença é o ponto: o ERP ganha tipo novo sem avisar, e um tipo novo
    entrando como neutro sumiria da tela — a premiação seguiria ignorando algo
    que talvez devesse contar."""
    assert cl.propor("ALGO QUE O ERP INVENTOU AMANHA")[0] == "nao_classificado"


def test_salvar_recusa_classe_invalida(esq):
    with pytest.raises(ValueError):
        cl.salvar(1, "qualquer_coisa", esquema=esq)
    with pytest.raises(ValueError):
        cl.salvar(1, "demerito", peso=-1, esquema=esq)


# ── carência e recoleta ──────────────────────────────────────────────────────
#
# O defeito que a carência conserta: hoje um snapshot tirado no dia 1º do mês
# seguinte fica com `parcial=False` e NUNCA MAIS é recoletado — congelando um
# mês em que ocorrência, multa e abastecimento ainda iam chegar. Não há erro
# nenhum: só um número menor do que devia, para sempre.

from datetime import date  # noqa: E402

from api.premiacao import apuracao as ap  # noqa: E402


@pytest.mark.parametrize("hoje,esperado,apuravel", [
    (date(2026, 8, 15), "em_curso", False),
    (date(2026, 8, 31), "em_curso", False),
    (date(2026, 9, 1), "em_carencia", False),
    (date(2026, 9, 9), "em_carencia", False),
    # o DECIMO dia ja completou a carencia: 31/08 + 10 = 10/09, e nesse dia os
    # dez dias de setembro ja passaram
    (date(2026, 9, 10), "apuravel", True),
    (date(2026, 12, 1), "apuravel", True),
])
def test_os_TRES_estados_da_competencia(esq, hoje, esperado, apuravel):
    """Dois estados não bastam: entre "mês acabou" e "dado estável" há os dias
    em que o lançamento ainda chega."""
    e = ap.estado("2026-08", hoje=hoje, esquema=esq)
    assert e["estado"] == esperado
    assert e["apuravel"] is apuravel
    assert e["motivo"]


def test_o_prazo_sai_da_VERSAO_vigente(esq):
    """Mudar a carência de 10 para 20 dias não pode reabrir meses já apurados
    sob o prazo antigo."""
    cf.salvar("2026-01", {**cf.defaults(), "dias_apuracao": 20},
              _eixos(), esquema=esq)
    e = ap.estado("2026-08", hoje=date(2026, 9, 15), esquema=esq)
    assert e["dias_apuracao"] == 20 and e["estado"] == "em_carencia"


def test_snapshot_tirado_DENTRO_da_carencia_e_recoletado(esq):
    """A regra que faltava. Sem ela o número do mês vale o que era no dia 1º."""
    dentro = {"coletado_em": "2026-09-02T08:00:00", "parcial": False}
    assert ap.precisa_recoletar("2026-08", dentro,
                                hoje=date(2026, 9, 20), esquema=esq) is True
    depois = {"coletado_em": "2026-09-12T08:00:00", "parcial": False}
    assert ap.precisa_recoletar("2026-08", depois,
                                hoje=date(2026, 9, 20), esquema=esq) is False


def test_sem_snapshot_sempre_recoleta(esq):
    assert ap.precisa_recoletar("2026-08", None, hoje=date(2026, 12, 1),
                                esquema=esq) is True


def test_em_carencia_recoleta_sempre(esq):
    """Enquanto o dado se move, refaz — é para isso que a carência existe."""
    snap = {"coletado_em": "2026-09-05T08:00:00", "parcial": False}
    assert ap.precisa_recoletar("2026-08", snap, hoje=date(2026, 9, 6),
                                esquema=esq) is True


def test_o_periodo_de_recoleta_inclui_as_duas_pontas():
    assert ap.competencias("2026-05", "2026-08") == [
        "2026-05", "2026-06", "2026-07", "2026-08"]
    assert ap.competencias("2026-08", "2026-08") == ["2026-08"]
    # invertido é aceito: quem digita ao contrário quis o mesmo intervalo
    assert ap.competencias("2026-08", "2026-05")[0] == "2026-05"
    # e vira o ano corretamente
    assert ap.competencias("2025-11", "2026-02") == [
        "2025-11", "2025-12", "2026-01", "2026-02"]


def test_periodo_grande_demais_e_RECUSADO():
    """Recoletar é uma volta na API por mês. Um erro de digitação (2020 em vez
    de 2026) não pode virar cinquenta chamadas — e recusar é melhor que
    truncar, porque truncar devolveria um resultado que PARECE completo."""
    with pytest.raises(ValueError, match="máximo|grande demais"):
        ap.competencias("2015-01", "2026-08")


def test_competencia_invalida_na_recoleta_e_RECUSADA():
    for ruim in ("2026", "agosto", "2026-13"):
        with pytest.raises(ValueError):
            ap.competencias(ruim, "2026-08")
