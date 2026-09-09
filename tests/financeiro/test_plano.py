"""Engenharia de caixa — a parte PURA, sem banco.

Os números das fixtures são os MEDIDOS em 09/09/2026, porque é deles que as
regras saíram:

    saldo de partida                       R$    156.555
    saída projetada (média mensal)         R$ 12,2 milhões  -> piso de 5 dias
                                                               ~ R$ 2,0 milhões
    recebível LANÇADO de convênio          R$  5,69 milhões (acaba em dez/26)
    fatia elegível do faturamento          49,8% (mediana de 6 meses)
    taxa medida no portal (mky_recebiveis) 1,17% a.m., ~plana por prazo

O que cada teste protege está no próprio nome: são as quatro decisões do
módulo, e cada uma custa dinheiro real se invertida.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.financeiro import plano as pl


# ---------------------------------------------------------------- fixtures

def _linha(mes, entradas, saidas, a_faturar=0.0, rotulo=None, confianca=0.5):
    """Uma linha no formato que `projecao.montar()` devolve."""
    return {"mes": mes, "rotulo": rotulo or mes, "entradas": entradas,
            "saidas": saidas, "a_faturar": a_faturar, "confianca": confianca,
            "saldo_final": 0.0}


def _taxa_fixa(pct):
    return lambda _prazo: pct


HOJE = date(2026, 9, 9)


# ---------------------------------------------------------------- o piso

class TestPiso:

    def test_o_piso_e_MOVEL_e_acompanha_a_saida_de_cada_mes(self):
        """Piso fixo envelhece: a mesma folga vira aperto num mês maior."""
        linhas = [_linha("2026-09", 7_762_000, 10_427_000),
                  _linha("2026-10", 11_943_000, 12_545_000)]
        piso = pl.piso_por_mes(linhas, dias=5)
        # 10.427.000 / 30 * 5
        assert piso["2026-09"] == pytest.approx(1_737_833.33, abs=1)
        assert piso["2026-10"] == pytest.approx(2_090_833.33, abs=1)
        # e o mês mais caro tem piso MAIOR — é isso que "móvel" quer dizer
        assert piso["2026-10"] > piso["2026-09"]

    def test_piso_zero_e_um_piso_valido_e_nao_vira_o_padrao_por_acidente(self):
        linhas = [_linha("2026-09", 1.0, 3_000_000)]
        assert pl.piso_por_mes(linhas, dias=0)["2026-09"] == 0.0


# ---------------------------------------------------------------- a pilha

class TestPilha:

    def test_as_duas_metades_NAO_se_sobrepoem(self):
        """`a_faturar` já é o que EXCEDE o lançado — por isso somam sem contar
        duas vezes. Se um dia a projeção mudar essa definição, este teste é o
        que avisa."""
        linhas = [_linha("2026-10", entradas=11_943_000, saidas=0,
                         a_faturar=6_169_000)]
        p = pl.pilha_por_mes(linhas, {"2026-10": 1_387_681.0}, share=0.4979)
        assert p["2026-10"]["lancado"] == 1_387_681.0
        assert p["2026-10"]["futuro"] == pytest.approx(3_071_545.1, abs=1)
        assert p["2026-10"]["total"] == pytest.approx(4_459_226.1, abs=2)

    def test_a_fatia_elegivel_NAO_se_aplica_ao_lancado(self):
        """O lançado já É de cliente com convênio — ele veio filtrado do ERP.
        Multiplicá-lo pela fatia cortaria pela metade a única parte da pilha
        que é FATO."""
        linhas = [_linha("2026-10", entradas=1_000_000, saidas=0, a_faturar=0.0)]
        p = pl.pilha_por_mes(linhas, {"2026-10": 900_000.0}, share=0.5)
        assert p["2026-10"]["lancado"] == 900_000.0
        assert p["2026-10"]["futuro"] == 0.0

    def test_mes_sem_lancado_ainda_tem_pilha_de_faturamento_futuro(self):
        """Sem esta metade o plano diria 'descoberto total a partir de jan/27',
        que é falso: a empresa não para de faturar."""
        linhas = [_linha("2027-05", entradas=11_794_938, saidas=0,
                         a_faturar=11_794_938)]
        p = pl.pilha_por_mes(linhas, {}, share=0.4979)
        assert p["2027-05"]["lancado"] == 0.0
        assert p["2027-05"]["total"] > 5_000_000


# ---------------------------------------------------------------- o prazo

class TestPrazo:

    def test_no_mes_corrente_a_operacao_e_HOJE_nao_no_dia_15(self):
        """Quem lê a tela hoje vai ao banco hoje. Cobrar 15 dias a mais de
        deságio encareceria no papel uma operação que já poderia estar feita."""
        d = pl._prazo_dias("2026-09", "2026-10", HOJE)   # 09/09 -> 15/10
        assert d == 36

    def test_nos_meses_seguintes_a_operacao_e_no_MEIO_do_mes(self):
        d = pl._prazo_dias("2026-10", "2026-11", HOJE)   # 15/10 -> 15/11
        assert d == 31

    def test_o_prazo_nunca_e_zero_nem_negativo(self):
        assert pl._prazo_dias("2026-10", "2026-10", HOJE) >= 1


# ---------------------------------------------------------------- o motor

class TestSimular:

    def test_ANTECIPAR_E_SAQUE_e_o_saque_esvazia_o_mes_de_origem(self):
        """A regra que transforma 'quanto antecipar' numa sequência.

        Setembro fura e saca de outubro; outubro tem de receber MENOS por
        exatamente o que foi sacado. Sem isso o plano antecipa o mesmo dinheiro
        doze vezes e fecha todos os meses — o erro mais caro que este módulo
        pode cometer, porque ele produz um painel verde.
        """
        linhas = [_linha("2026-09", 1_000_000, 2_000_000),
                  _linha("2026-10", 5_000_000, 1_000_000)]
        pilha = {"2026-09": {"lancado": 0.0, "futuro": 0.0, "total": 0.0},
                 "2026-10": {"lancado": 3_000_000.0, "futuro": 0.0,
                             "total": 3_000_000.0}}
        r = pl.simular(linhas, pilha, {"2026-09": 0.0, "2026-10": 0.0},
                       _taxa_fixa(0.0), saldo_inicial=0.0, hoje=HOJE)
        set_, out = r["linhas"]
        assert set_["antecipar"] == pytest.approx(1_000_000, abs=1)
        # e outubro recebe 5.000.000 - 1.000.000
        assert out["sacado_de_mim"] == pytest.approx(1_000_000, abs=1)
        assert out["entradas"] == pytest.approx(4_000_000, abs=1)
        assert out["entradas_projetadas"] == 5_000_000

    def test_o_saque_e_BRUTO_porque_o_desagio_sai_de_dentro(self):
        """Para o caixa receber 100 mil a 3% é preciso sacar 103.092,78.
        Sacar 100 mil deixaria o mês 3 mil abaixo do piso — e o mês em que
        isso acontece é justamente o mês apertado."""
        linhas = [_linha("2026-09", 0.0, 100_000),
                  _linha("2026-10", 500_000, 0.0)]
        pilha = {"2026-09": {"lancado": 0, "futuro": 0, "total": 0},
                 "2026-10": {"lancado": 500_000.0, "futuro": 0.0,
                             "total": 500_000.0}}
        # taxa tal que o deságio do prazo (36 dias) dê exatamente 3%
        taxa = 3.0 / (36 / 30.0)
        r = pl.simular(linhas, pilha, {"2026-09": 0.0, "2026-10": 0.0},
                       _taxa_fixa(taxa), saldo_inicial=0.0, hoje=HOJE)
        set_ = r["linhas"][0]
        assert set_["antecipar"] == pytest.approx(103_092.78, abs=1)
        assert set_["liquido"] == pytest.approx(100_000, abs=1)
        assert set_["custo"] == pytest.approx(3_092.78, abs=1)
        # e o saldo fecha EXATAMENTE no piso, não abaixo dele
        assert set_["saldo_final"] == pytest.approx(0.0, abs=1)

    def test_NAO_saca_do_proprio_mes(self):
        """O recebível que vence em setembro já está na entrada de setembro:
        antecipá-lo não muda o saldo do mês, só paga deságio."""
        linhas = [_linha("2026-09", 1_000_000, 2_000_000)]
        pilha = {"2026-09": {"lancado": 9_000_000.0, "futuro": 0.0,
                             "total": 9_000_000.0}}
        r = pl.simular(linhas, pilha, {"2026-09": 0.0}, _taxa_fixa(1.17),
                       saldo_inicial=0.0, hoje=HOJE)
        assert r["linhas"][0]["antecipar"] == 0.0
        assert r["linhas"][0]["descoberto"] == pytest.approx(1_000_000, abs=1)

    def test_saca_do_mes_mais_PROXIMO_primeiro_porque_e_o_mais_barato(self):
        linhas = [_linha("2026-09", 0.0, 1_000_000),
                  _linha("2026-10", 0.0, 0.0),
                  _linha("2026-11", 0.0, 0.0)]
        pilha = {"2026-09": {"lancado": 0, "futuro": 0, "total": 0},
                 "2026-10": {"lancado": 400_000.0, "futuro": 0.0, "total": 400_000.0},
                 "2026-11": {"lancado": 900_000.0, "futuro": 0.0, "total": 900_000.0}}
        r = pl.simular(linhas, pilha, {m["mes"]: 0.0 for m in linhas},
                       _taxa_fixa(1.17), saldo_inicial=0.0, hoje=HOJE)
        ops = r["linhas"][0]["operacoes"]
        assert [o["origem"] for o in ops] == ["2026-10", "2026-11"]
        # outubro foi consumido INTEIRO antes de novembro ser tocado
        assert ops[0]["bruto"] == pytest.approx(400_000, abs=1)
        assert ops[0]["prazo_dias"] < ops[1]["prazo_dias"]

    def test_pilha_esgotada_vira_DESCOBERTO_e_nao_saldo_negativo_silencioso(self):
        linhas = [_linha("2026-09", 0.0, 5_000_000),
                  _linha("2026-10", 0.0, 0.0)]
        pilha = {"2026-09": {"lancado": 0, "futuro": 0, "total": 0},
                 "2026-10": {"lancado": 100_000.0, "futuro": 0.0, "total": 100_000.0}}
        r = pl.simular(linhas, pilha, {"2026-09": 0.0, "2026-10": 0.0},
                       _taxa_fixa(0.0), saldo_inicial=0.0, hoje=HOJE)
        set_ = r["linhas"][0]
        assert set_["antecipar"] == pytest.approx(100_000, abs=1)
        assert set_["descoberto"] == pytest.approx(4_900_000, abs=1)

    def test_a_SATURACAO_mede_quanto_da_pilha_do_mes_o_plano_precisou(self):
        """É o alarme que acende ANTES do descoberto — ver o docstring."""
        linhas = [_linha("2026-09", 0.0, 500_000),
                  _linha("2026-10", 0.0, 0.0)]
        pilha = {"2026-09": {"lancado": 0, "futuro": 0, "total": 0},
                 "2026-10": {"lancado": 1_000_000.0, "futuro": 0.0,
                             "total": 1_000_000.0}}
        r = pl.simular(linhas, pilha, {"2026-09": 0.0, "2026-10": 0.0},
                       _taxa_fixa(0.0), saldo_inicial=0.0, hoje=HOJE)
        assert r["linhas"][1]["saturacao"] == pytest.approx(0.5, abs=0.001)

    def test_mes_folgado_nao_antecipa_nada(self):
        linhas = [_linha("2026-09", 3_000_000, 1_000_000),
                  _linha("2026-10", 0.0, 0.0)]
        pilha = {m: {"lancado": 9e9, "futuro": 0.0, "total": 9e9}
                 for m in ("2026-09", "2026-10")}
        r = pl.simular(linhas, pilha, {"2026-09": 0.0, "2026-10": 0.0},
                       _taxa_fixa(1.17), saldo_inicial=0.0, hoje=HOJE)
        assert r["linhas"][0]["antecipar"] == 0.0
        assert r["linhas"][0]["custo"] == 0.0

    def test_a_operacao_diz_de_QUAL_metade_da_pilha_saiu(self):
        """Um plano que só fecha com faturamento futuro tem outro risco, e some
        se as duas metades virarem um número só."""
        linhas = [_linha("2026-09", 0.0, 1_000_000),
                  _linha("2026-10", 0.0, 0.0)]
        pilha = {"2026-09": {"lancado": 0, "futuro": 0, "total": 0},
                 "2026-10": {"lancado": 300_000.0, "futuro": 900_000.0,
                             "total": 1_200_000.0}}
        r = pl.simular(linhas, pilha, {"2026-09": 0.0, "2026-10": 0.0},
                       _taxa_fixa(0.0), saldo_inicial=0.0, hoje=HOJE)
        op = r["linhas"][0]["operacoes"][0]
        assert op["de_lancado"] == pytest.approx(300_000, abs=1)
        assert op["de_futuro"] == pytest.approx(700_000, abs=1)
        assert op["de_lancado"] + op["de_futuro"] == pytest.approx(op["bruto"], abs=1)


# ---------------------------------------------------------------- a cauda

class TestCauda:

    def test_tres_meses_depois_do_horizonte_e_viram_o_ano(self):
        linhas = [_linha("2027-08", 0.0, 0.0)]
        assert pl.meses_de_cauda(linhas) == ["2027-09", "2027-10", "2027-11"]
        assert pl.meses_de_cauda([_linha("2026-11", 0.0, 0.0)]) == [
            "2026-12", "2027-01", "2027-02"]

    def test_sem_a_cauda_o_ULTIMO_mes_fica_descoberto_por_construcao(self):
        """O corte da janela não é um fato sobre a empresa. Medido em
        09/09/2026: sem cauda, jul/27 e ago/27 somavam R$ 21,7 milhões de
        'descoberto' com R$ 5,7 milhões de pilha intocada em cada um."""
        linhas = [_linha("2026-09", 0.0, 0.0), _linha("2026-10", 0.0, 1_000_000)]
        pilha = {"2026-09": {"lancado": 0, "futuro": 0, "total": 0},
                 "2026-10": {"lancado": 0, "futuro": 0, "total": 0},
                 "2026-11": {"lancado": 0.0, "futuro": 2_000_000.0,
                             "total": 2_000_000.0}}
        piso = {"2026-09": 0.0, "2026-10": 0.0}
        sem = pl.simular(linhas, pilha, piso, _taxa_fixa(0.0), 0.0, HOJE)
        assert sem["linhas"][-1]["descoberto"] == pytest.approx(1_000_000, abs=1)
        com = pl.simular(linhas, pilha, piso, _taxa_fixa(0.0), 0.0, HOJE,
                         meses_extra=["2026-11"])
        assert com["linhas"][-1]["descoberto"] == 0.0

    def test_a_cauda_NAO_vira_linha_no_resultado(self):
        """Ela é fonte de saque, não mês do plano: mostrar um 13º mês na tela
        seria publicar projeção que ninguém calculou."""
        linhas = [_linha("2026-09", 0.0, 100.0)]
        pilha = {"2026-09": {"lancado": 0, "futuro": 0, "total": 0},
                 "2026-10": {"lancado": 0.0, "futuro": 5_000.0, "total": 5_000.0}}
        r = pl.simular(linhas, pilha, {"2026-09": 0.0}, _taxa_fixa(0.0), 0.0,
                       HOJE, meses_extra=["2026-10"])
        assert [l["mes"] for l in r["linhas"]] == ["2026-09"]


# ---------------------------------------------------------------- o resumo

class TestResumir:

    def _plano(self):
        linhas = [_linha("2026-09", 0.0, 1_000_000, rotulo="set/26"),
                  _linha("2026-10", 0.0, 0.0, rotulo="out/26"),
                  _linha("2026-11", 0.0, 0.0, rotulo="nov/26")]
        pilha = {"2026-09": {"lancado": 0, "futuro": 0, "total": 0},
                 "2026-10": {"lancado": 600_000.0, "futuro": 0.0, "total": 600_000.0},
                 "2026-11": {"lancado": 900_000.0, "futuro": 0.0, "total": 900_000.0}}
        return pl.simular(linhas, pilha, {m: 0.0 for m in pilha},
                          _taxa_fixa(1.17), saldo_inicial=0.0, hoje=HOJE)

    def test_antecipar_agora_e_o_numero_do_PRIMEIRO_mes_nao_o_total(self):
        """O número de ação é o do mês corrente. O total de 12 meses responde
        outra pergunta e confundi-los manda a tesouraria ao banco com um
        número cinco vezes maior que o necessário."""
        r = self._plano()
        k = pl.resumir(r["linhas"], [], r["operacoes"])
        assert k["antecipar_agora"] == r["linhas"][0]["antecipar"]
        assert k["mes_agora"] == "set/26"
        assert k["antecipar_12m"] > k["antecipar_agora"] or \
            k["meses_com_operacao"] == 1

    def test_capital_medio_NAO_e_a_soma_do_nominal(self):
        """Somar o nominal e chamar de dívida erra por um fator de cinco: o
        mesmo dinheiro gira várias vezes no ano. Mesma definição de
        `antecipacoes.estrategia` — Σ(valor × prazo) ÷ 365."""
        ops = [{"bruto": 1_000_000.0, "prazo_dias": 36},
               {"bruto": 1_000_000.0, "prazo_dias": 73}]
        c = pl._capital(ops, custo=30_000.0)
        assert c["capital_medio"] == pytest.approx(
            (1_000_000 * 36 + 1_000_000 * 73) / 365.0, abs=1)
        assert c["capital_medio"] < 2_000_000        # menor que o nominal
        assert c["giros_ano"] == pytest.approx(2_000_000 / c["capital_medio"], abs=0.1)
        assert c["prazo_medio"] == pytest.approx(54.5, abs=0.1)

    def test_custo_efetivo_e_sobre_o_capital_medio_nao_sobre_o_nominal(self):
        """É a única leitura em que o deságio e o rotativo ficam na mesma
        régua. Sobre o nominal, a antecipação parece cinco vezes mais barata
        do que é."""
        c = pl._capital([{"bruto": 1_000_000.0, "prazo_dias": 73}], custo=23_400.0)
        assert c["custo_efetivo_aa"] == pytest.approx(
            23_400.0 / (1_000_000 * 73 / 365.0) * 100, abs=0.01)

    def test_primeiro_saturado_acende_antes_do_descoberto(self):
        plano = [{"rotulo": "set/26", "saturacao": 0.5, "descoberto": 0.0,
                  "antecipar": 1.0, "custo": 0.0, "entradas_projetadas": 0.0,
                  "saidas": 0.0, "pilha": 1.0, "piso": 0.0, "operacoes": [],
                  "saldo_final": 0.0},
                 {"rotulo": "out/26", "saturacao": 1.0, "descoberto": 0.0,
                  "antecipar": 1.0, "custo": 0.0, "entradas_projetadas": 0.0,
                  "saidas": 0.0, "pilha": 1.0, "piso": 0.0, "operacoes": [],
                  "saldo_final": 0.0}]
        k = pl.resumir(plano, [])
        assert k["primeiro_saturado"] == "out/26"
        assert k["meses_saturados"] == 1
        assert k["descoberto_total"] == 0.0     # e nenhum descoberto ainda

    def test_estrutural_mes_ignora_a_antecipacao(self):
        """Ele mede o fluxo da empresa, não o do plano: é a resposta a 'e
        depois?'. Medir sobre o saldo já antecipado daria zero para sempre,
        porque o plano fecha no piso por construção."""
        plano = [{"rotulo": "a", "saturacao": None, "descoberto": 0.0,
                  "antecipar": 5_000_000.0, "custo": 0.0, "piso": 0.0,
                  "entradas_projetadas": 1_000_000.0, "saidas": 1_800_000.0,
                  "pilha": 0.0, "operacoes": [], "saldo_final": 0.0}]
        assert pl.resumir(plano, [])["estrutural_mes"] == pytest.approx(-800_000)


# ---------------------------------------------------------------- a fatia

class TestFatiaElegivel:

    # os doze meses medidos em 09/09/2026
    MEDIDO = [("2025-09", 36.8), ("2025-10", 37.8), ("2025-11", 38.1),
              ("2025-12", 31.2), ("2026-01", 37.8), ("2026-02", 43.2),
              ("2026-03", 42.5), ("2026-04", 45.5), ("2026-05", 50.8),
              ("2026-06", 52.9), ("2026-07", 48.8), ("2026-08", 54.7)]

    def _linhas(self):
        return [{"mes": m, "total": 100.0, "elegivel": p} for m, p in self.MEDIDO]

    def test_a_janela_e_de_SEIS_meses_e_a_fatia_bate_o_medido(self):
        f = pl.fatia_elegivel(self._linhas())
        assert f["n"] == 6
        assert f["share"] == pytest.approx(0.498, abs=0.001)

    def test_e_MEDIANA_nao_media_por_causa_da_tendencia_de_alta(self):
        """A série sobe (36,8% -> 54,7%). A média de doze meses responde com um
        número que já não descreve a empresa: 43,4% contra 49,8%."""
        seis = self._linhas()[-6:]
        media12 = sum(l["elegivel"] for l in self._linhas()) / 12 / 100
        assert media12 == pytest.approx(0.434, abs=0.002)
        assert pl.fatia_elegivel(self._linhas())["share"] > media12
        assert len(seis) == 6

    def test_um_mes_fora_da_curva_NAO_move_a_fatia(self):
        """Média deixaria um mês fraco de um cliente grande mudar o tamanho do
        plano inteiro."""
        linhas = self._linhas()
        base = pl.fatia_elegivel(linhas)["share"]
        linhas[-1] = {**linhas[-1], "elegivel": 2.0}
        assert pl.fatia_elegivel(linhas)["share"] == pytest.approx(base, abs=0.03)

    def test_sem_historia_a_fatia_e_zero_e_nao_um_chute(self):
        f = pl.fatia_elegivel([])
        assert f["share"] == 0.0 and f["n"] == 0


# ------------------------------------------------------- a curva de taxa

def test_a_taxa_de_fallback_e_PESSIMISTA_em_relacao_a_medida():
    """Um plano barato demais por falta de dado se executa; um caro demais se
    questiona. O portal media 1,17% a.m. em 09/09/2026."""
    assert pl.TAXA_FALLBACK > 1.17
