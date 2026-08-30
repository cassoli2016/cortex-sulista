"""A régua de condução: motor ligado parado e faixa verde.

PREMIAÇÃO DECIDE DINHEIRO, e a pergunta "por que recebi isso em março?" sempre
aparece — meses depois, quando quem configurou já mudou o número três vezes.
Estes testes trancam o que faz essa pergunta ter resposta: a régua é nossa, é
linear, é parâmetro da versão, e a conta vem aberta.

POR QUE A RÉGUA NÃO É A NOTA DO FORNECEDOR
==========================================
Medido em 30/08/2026 sobre as 98 placas da competência: **seis dos catorze
indicadores vieram com `score` 0 em TODOS os veículos**. Régua que zera a frota
inteira não separa ninguém e não se explica a quem perdeu o prêmio.

POR QUE OS DOIS INDICADORES SÃO TRATADOS DIFERENTE
==================================================
Saiu do dado, não de preferência:
- `idle` tem dispersão real (p25 9,2% · p75 16,7% · máx 60,4%) → GRADUA;
- `greenRange` tem a metade central em cinco pontos (93,8% a 98,8%) → não
  gradua, EXCEPCIONA. Graduar ali daria a mesma nota para todo mundo.
"""
from __future__ import annotations

import pytest

from api.premiacao import config as cf
from api.premiacao.conducao import avaliar, nota_idle, penalidade_verde

D = cf.defaults()


# ── motor ligado parado: gradua ─────────────────────────────────────────────


@pytest.mark.parametrize("pct,esperado", [
    (0.0, 100.0),      # ninguém deixa o motor ligado parado
    (9.2, 100.0),      # p25 da frota: quartil de cima leva nota cheia
    (10.0, 100.0),     # o alvo, exato
    (25.0, 0.0),       # o teto, exato
    (60.4, 0.0),       # o pior da frota
])
def test_a_nota_de_idle_nas_pontas(pct, esperado):
    assert nota_idle(pct, D["idle_alvo"], D["idle_teto"]) == esperado


def test_entre_alvo_e_teto_a_nota_cai_LINEARMENTE():
    """Linear e não escalonada: com degraus, um décimo de ponto percentual
    decidiria dez pontos de nota, e a diferença entre 14,9% e 15,1% viraria
    uma discussão que o dado não sustenta."""
    meio = (D["idle_alvo"] + D["idle_teto"]) / 2
    assert nota_idle(meio, D["idle_alvo"], D["idle_teto"]) == 50.0
    # e é monotônica: mais motor parado nunca dá nota maior
    notas = [nota_idle(p, D["idle_alvo"], D["idle_teto"])
             for p in range(0, 40)]
    assert notas == sorted(notas, reverse=True)


def test_sem_medida_e_NONE_e_nao_zero():
    """Motorista sem telemetria no mês não é motorista que deixou o motor
    ligado o mês inteiro. Quem decide o que fazer com a ausência é o motor de
    cálculo, que sabe se há outros eixos para compensar."""
    assert nota_idle(None, 10.0, 25.0) is None
    r = avaliar({"greenRange": {"pct": 95.0}}, D)
    assert r["nota"] is None and "sem medida" in r["motivo"]


def test_teto_menor_que_alvo_e_RECUSADO():
    """Configuração invertida daria nota crescente com o motor parado — e
    ninguém perceberia olhando a tela."""
    with pytest.raises(ValueError, match="maior que o alvo"):
        nota_idle(12.0, 25.0, 10.0)


# ── faixa verde: piso, não gradação ─────────────────────────────────────────


@pytest.mark.parametrize("pct", [100.0, 98.8, 96.9, 93.8, 85.0])
def test_dentro_da_faixa_normal_da_frota_NAO_desconta(pct):
    """93,8% a 98,8% é onde metade da frota está: premiar diferença aí seria
    premiar ruído — a armadilha da coluna que repete o mesmo valor."""
    assert penalidade_verde(pct, D["verde_piso"], D["verde_desconto_max"]) == 0.0


def test_abaixo_do_piso_desconta_e_cresce_ate_o_maximo():
    assert penalidade_verde(0.0, D["verde_piso"], D["verde_desconto_max"]) == \
        D["verde_desconto_max"]
    meio = penalidade_verde(D["verde_piso"] / 2, D["verde_piso"],
                            D["verde_desconto_max"])
    assert 0 < meio < D["verde_desconto_max"]


def test_faixa_verde_ausente_nao_desconta():
    """Ausência de medida não é desempenho ruim."""
    assert penalidade_verde(None, 85.0, 20.0) == 0.0


# ── a conta aberta ──────────────────────────────────────────────────────────


def test_a_avaliacao_devolve_as_PARCELAS_e_nao_so_o_total():
    """Quem pergunta "por que essa nota?" precisa ver de onde ela veio."""
    r = avaliar({"idle": {"pct": 12.7}, "greenRange": {"pct": 70.0}}, D)
    assert r["idle_nota"] == 82.0
    assert r["verde_desconto"] == 3.5
    assert r["nota"] == pytest.approx(78.5, abs=0.1)
    assert "12.7%" in r["motivo"] and "faixa verde" in r["motivo"]


def test_o_motivo_diz_o_alvo_e_o_teto_usados():
    """Sem os números da régua no texto, o motivo não explica nada — a pessoa
    teria de ir procurar a configuração da competência."""
    r = avaliar({"idle": {"pct": 12.7}}, D)
    assert "10%" in r["motivo"] and "25%" in r["motivo"]


def test_a_nota_nunca_fica_NEGATIVA():
    """Desconto maior que a nota zeraria abaixo de zero e o total do prêmio
    passaria a subtrair de outros eixos."""
    r = avaliar({"idle": {"pct": 24.9}, "greenRange": {"pct": 0.0}}, D)
    assert r["nota"] == 0.0


# ── é parâmetro da versão, e é isso que dá resposta em março ────────────────


def test_a_regua_e_configuravel_por_competencia():
    frouxa = {**D, "idle_alvo": 20.0, "idle_teto": 40.0}
    assert avaliar({"idle": {"pct": 18.0}}, D)["nota"] == 46.7
    assert avaliar({"idle": {"pct": 18.0}}, frouxa)["nota"] == 100.0


def test_os_quatro_parametros_estao_no_catalogo_da_versao():
    """Se não estiverem em PARAMS, não são congelados na versão — e aí mudar a
    régua reescreveria retroativamente o prêmio de meses já pagos."""
    for k in ("idle_alvo", "idle_teto", "verde_piso", "verde_desconto_max"):
        assert k in cf.PARAMS, k
        assert k in cf.defaults()


def test_os_padroes_saem_da_frota_medida_e_nao_de_numero_redondo():
    """O alvo fica no quartil de cima (p25 = 9,2%) e o teto acima do p75
    (16,7%), onde começa a cauda que destoa. Um padrão que não separa a frota
    faria o eixo não valer nada."""
    assert D["idle_alvo"] == 10.0 and D["idle_teto"] == 25.0
    # a mediana da frota (12,7%) tem de cair no MEIO da régua, não numa ponta
    n = nota_idle(12.7, D["idle_alvo"], D["idle_teto"])
    assert 60.0 < n < 95.0, f"a mediana da frota tirou {n} — régua desbalanceada"
