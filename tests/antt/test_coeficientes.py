"""Coeficientes ANTT: vigência por data e combinações inexistentes."""
from __future__ import annotations

from datetime import date

from api.antt.coeficientes import TIPOS_CARGA, coeficiente


def test_carga_geral_2_eixos_na_vigencia_de_janeiro():
    c = coeficiente("carga_geral", 2, date(2026, 3, 15))
    assert c["ccd"] == 3.6815
    assert c["cc"] == 436.39
    assert c["resolucao"] == "6.076/2026"


def test_mesma_carga_na_vigencia_de_julho_usa_a_tabela_nova():
    c = coeficiente("carga_geral", 2, date(2026, 8, 1))
    assert c["ccd"] == 3.9826
    assert c["cc"] == 451.84
    assert c["resolucao"] == "6.084/2026"


def test_reajuste_do_cc_confere_com_os_3_54_por_cento_anunciados():
    velho = coeficiente("carga_geral", 2, date(2026, 3, 15))["cc"]
    novo = coeficiente("carga_geral", 2, date(2026, 8, 1))["cc"]
    assert abs(novo - velho * 1.0354) < 0.01


def test_tipo_de_carga_inexistente_devolve_none_em_vez_de_zero():
    assert coeficiente("carga_imaginaria", 5, date(2026, 8, 1)) is None


def test_eixo_ausente_na_tabela_cai_no_imediatamente_inferior():
    """Regra da Res. 5.867/2020, nota do Anexo II: eixo não previsto usa a
    quantidade imediatamente inferior. Conteinerizada não tem linha de 3 eixos
    — a calculadora oficial devolve a de 2, e nós temos de devolver o mesmo."""
    dois = coeficiente("conteinerizada", 2, date(2026, 8, 1))
    tres = coeficiente("conteinerizada", 3, date(2026, 8, 1))
    assert tres == dois
    assert tres["ccd"] == 5.1082


def test_eixo_ausente_no_meio_da_tabela_tambem_cai_para_baixo():
    """Granel pressurizada só tem 2, 6 e 9 eixos. Um veículo de 7 eixos usa a
    linha de 6, nunca a de 9 — arredondar para cima cobraria piso maior que o
    devido e acusaria pagamento correto de estar abaixo."""
    seis = coeficiente("granel_pressurizada", 6, date(2026, 8, 1))
    sete = coeficiente("granel_pressurizada", 7, date(2026, 8, 1))
    assert sete == seis


def test_eixo_abaixo_do_minimo_da_tabela_nao_inventa_linha():
    assert coeficiente("granel_pressurizada", 1, date(2026, 8, 1)) is None


def test_data_anterior_a_qualquer_vigencia_devolve_none():
    assert coeficiente("carga_geral", 2, date(2019, 1, 1)) is None


def test_as_doze_classes_estao_declaradas():
    assert len(TIPOS_CARGA) == 12
    assert "carga_geral" in TIPOS_CARGA
    assert "perigosa_granel_liquido" in TIPOS_CARGA


def test_todo_cc_de_julho_e_o_de_janeiro_reajustado_em_3_54():
    """Guarda de transcrição sobre as 78 células de cada vigência.

    A Res. 6.084/2026 reajusta o CC em 3,54% de IPCA sobre a 6.076/2026 — em
    todos os tipos, em todos os eixos. Um dígito trocado na transcrição de
    qualquer célula quebra este teste, que é a razão de ele existir: acusar um
    transportador de pagar abaixo do piso por erro de digitação é pior do que
    não ter a conferência.
    """
    from api.antt.coeficientes import carregar

    dados = carregar()
    jan = {v["resolucao"]: v for v in dados["vigencias"]}["6.076/2026"]["tabelas"]["A"]
    jul = {v["resolucao"]: v for v in dados["vigencias"]}["6.084/2026"]["tabelas"]["A"]

    assert set(jan) == set(jul), "os dois períodos têm de cobrir os mesmos tipos"
    conferidas = 0
    for tipo, linhas in jan.items():
        assert set(linhas) == set(jul[tipo]), f"eixos divergem em {tipo}"
        for eixos, linha in linhas.items():
            esperado = linha["cc"] * 1.0354
            achado = jul[tipo][eixos]["cc"]
            assert abs(achado - esperado) <= 0.02, (
                f"{tipo}/{eixos} eixos: CC de julho {achado} não é "
                f"{linha['cc']} + 3,54% ({esperado:.2f})")
            conferidas += 1
    assert conferidas == 78


def test_ccd_sempre_cresce_com_o_numero_de_eixos():
    """Sanidade física: mais eixos custa mais por km. Pega dígito trocado que
    o teste do reajuste não pega, porque o CCD não tem fator único."""
    from api.antt.coeficientes import carregar

    for v in carregar()["vigencias"]:
        for tipo, linhas in v["tabelas"]["A"].items():
            eixos = sorted(linhas)
            ccds = [linhas[e]["ccd"] for e in eixos]
            assert ccds == sorted(ccds), (
                f"{v['resolucao']} {tipo}: CCD não é crescente em eixos: {ccds}")
