"""Os números do resumo diário de faturamento.

Este arquivo existe por causa de DUAS armadilhas específicas:

1. O CÓRTEX tem TRÊS recortes de receita na mesma resposta da Visão Geral
   (`faturamento_mes` = faturas emitidas, `realizado_acumulado` = a régua da
   META, `receita_mes_cte`). Misturar numerador de uma régua com denominador
   de outra dá 96% de atingimento onde o real é 91,3%.

2. O resumo sai às 07:00 — o dia corrente tem meta CHEIA e realizado de
   minutos, então TODA conta do mês usa só DIAS FECHADOS, o dia da mensagem
   é sempre ONTEM, e no dia 1º a mensagem vira o FECHAMENTO do mês anterior.

TODO teste fixa a data: o cálculo separa fechados de restantes por
`hoje.day`, e teste amarrado ao relógio real falharia só quando o calendário
virasse — acusando o commit inocente do dia (já aconteceu nesta casa). E no
dia 1º real, sem mock, o provedor iria buscar o mês anterior no ERP.
"""
from __future__ import annotations

from datetime import date

from api.whatsapp import valores as v

# Recorte real da Visão Geral em 28/08/2026, com os três números de receita
# lado a lado, que é o que torna a confusão possível.
VISAO = {
    "faturamento_mes": 11287791.78,        # faturas emitidas — NÃO é a régua
    "realizado_acumulado": 10735390.66,    # a régua da meta (MTD do painel)
    "meta_acumulada": 11756257.68,
    "atingimento_mes": 0.9131639465731752,
    "faturamento_mes_ant": 10390732.37,
    "diario": [{"dia": 1, "realizado": 160945.43, "meta": 174774.47},
               {"dia": 2, "realizado": 0.0, "meta": 0.0},
               {"dia": 27, "realizado": 480210.11, "meta": 552857.99},
               {"dia": 28, "realizado": 104007.09, "meta": 552857.99},
               {"dia": 29, "realizado": 0.0, "meta": 552857.99},
               {"dia": 30, "realizado": 0.0, "meta": 552857.99}],
}


def _hoje(monkeypatch, ano, mes, dia):
    class _H(date):
        @classmethod
        def today(cls):
            return cls(ano, mes, dia)
    monkeypatch.setattr(v, "date", _H)


def test_formata_em_real_sem_depender_de_locale():
    """O Windows desta bancada não tem locale pt-BR instalado."""
    assert v.brl(10735390.66) == "R$ 10.735.390,66"
    assert v.brl(0) == "R$ 0,00"
    assert v.brl(-1234.5) == "-R$ 1.234,50"
    assert v.brl(None) == "R$ 0,00"


def test_o_mes_da_mensagem_e_o_mes_ATE_ONTEM_e_nunca_as_faturas(monkeypatch):
    """Numerador e denominador saem do MESMO `diario` (a régua da meta),
    recortados nos dias fechados — e `faturamento_mes` (as faturas, 11,28 mi)
    continua proibido: numerador de outra régua."""
    _hoje(monkeypatch, 2026, 8, 29)                    # dias 1-28 fechados
    d = v.faturamento_diario(VISAO)
    # fechados: 160.945,43 + 480.210,11 + 104.007,09 = 745.162,63
    # metas:    174.774,47 + 552.857,99 + 552.857,99 = 1.280.490,45 → 58,2%
    assert d["titulo_mes"] == "MÊS ATÉ ONTEM"
    assert d["acumulado_mes"] == "R$ 745.162,63"
    assert d["meta_mes"] == "R$ 1.280.490,45"
    assert d["atingimento_mes"] == "58,2%"
    assert "11.287.791" not in str(d)                  # faturas emitidas não entram


def test_o_dia_da_mensagem_e_sempre_ONTEM(monkeypatch):
    """"Sempre mostrar o fechamento do dia anterior" (pedido de 01/09/2026).
    O parcial de hoje cedo não entra — às 07:00 ele tem minutos de emissão."""
    _hoje(monkeypatch, 2026, 8, 29)
    d = v.faturamento_diario(VISAO)
    assert d["data"] == "28/08/2026"
    assert d["faturado_dia"] == "R$ 104.007,09"        # o dia 28, fechado
    assert d["atingimento_dia"] == "18,8%"
    assert "em curso" not in d["atingimento_dia"]
    assert d["farol_dia"] == "🔴"


def test_ontem_sem_meta_nao_e_zero_por_cento(monkeypatch):
    """Domingo e feriado não têm meta. "0,0%" acusaria quem cumpriu."""
    _hoje(monkeypatch, 2026, 8, 29)
    visao = {**VISAO, "diario": [{"dia": 28, "realizado": 5000.0, "meta": 0.0}]}
    d = v.faturamento_diario(visao)
    assert d["atingimento_dia"] == "sem meta no dia"
    assert d["farol_dia"] == "⚪"


def test_ontem_sem_linha_no_diario_sai_zerado_e_sem_meta(monkeypatch):
    """O GROUP BY não devolve o dia sem emissão e sem meta — a linha ausente
    é um domingo, não um erro."""
    _hoje(monkeypatch, 2026, 8, 31)                    # dia 30 não tem linha? tem
    visao = {**VISAO, "diario": [{"dia": 28, "realizado": 104007.09,
                                  "meta": 552857.99}]}
    d = v.faturamento_diario(visao)                    # ontem = 30, sem linha
    assert d["faturado_dia"] == "R$ 0,00"
    assert d["atingimento_dia"] == "sem meta no dia"


def test_falta_para_a_meta_nunca_e_negativa(monkeypatch):
    """Meta superada mostra "R$ 0,00" a faltar, não um valor negativo que se
    lê como dívida."""
    _hoje(monkeypatch, 2026, 8, 29)
    visao = {**VISAO,
             "diario": [{"dia": 27, "realizado": 3000000.0, "meta": 1000000.0},
                        {"dia": 30, "realizado": 0.0, "meta": 1000000.0}]}
    assert v.faturamento_diario(visao)["falta_mes"] == "R$ 0,00"


def test_mes_sem_emissao_nenhuma_silencia_em_vez_de_mandar_zero(monkeypatch):
    """Mandar "faturamos R$ 0,00" com o mês sem emissão seria alarme falso —
    é o terceiro estado da agenda (nada a enviar)."""
    _hoje(monkeypatch, 2026, 8, 15)
    d = v.faturamento_diario({"diario": [{"dia": i, "realizado": 0.0,
                                          "meta": 100.0} for i in range(1, 15)]})
    assert "_silencio" in d
    _hoje(monkeypatch, 2026, 8, 29)
    assert v.faturamento_diario(VISAO).get("_silencio") is None


def test_diario_vazio_nao_estoura(monkeypatch):
    _hoje(monkeypatch, 2026, 8, 29)
    d = v.faturamento_diario({"diario": [], "meta_acumulada": 0,
                              "realizado_acumulado": 0})
    assert d["faturado_dia"] == "R$ 0,00"
    assert d["atingimento_dia"] == "sem meta no dia"
    assert "_silencio" in d


def test_todas_as_variaveis_do_contexto_sao_preenchidas(monkeypatch):
    """O contrato: tudo que o catálogo declara o provedor entrega. Uma
    faltando deixaria o envio recusado por variável em branco — e o defeito
    só apareceria na hora de mandar."""
    _hoje(monkeypatch, 2026, 8, 29)
    from api.whatsapp import modelos as md
    declaradas = md.variaveis_do_contexto("faturamento")
    entregues = set(v.faturamento_diario(VISAO))
    assert declaradas == entregues, declaradas ^ entregues


def test_provedor_desconhecido_devolve_vazio_e_nao_estoura():
    """A tela pergunta por todos os contextos; não ter provedor é resposta
    normal."""
    assert v.obter("nao-existe") == {}
    assert v.obter("") == {}


def test_o_contexto_faturamento_aponta_para_o_provedor():
    from api.whatsapp import modelos as md
    assert md.provedor_do_contexto("faturamento") == "faturamento_diario"
    assert md.provedor_do_contexto("cobranca") == ""


# ---------------------------------------------------------------------------
# Previsão de fechamento, ritmo necessário e pontos de atenção
# ---------------------------------------------------------------------------

def test_previsao_e_o_realizado_mais_o_ritmo_sobre_a_meta_restante(monkeypatch):
    """Ritmo 50% sobre meta restante de 1.000 → fecha em 1.000 de 2.000."""
    _hoje(monkeypatch, 2026, 8, 29)
    visao = {"diario": [{"dia": 27, "realizado": 500.0, "meta": 1000.0},
                        {"dia": 29, "realizado": 0.0, "meta": 500.0},
                        {"dia": 30, "realizado": 0.0, "meta": 500.0}]}
    d = v.faturamento_diario(visao)
    assert d["previsao_mes"] == "R$ 1.000,00"
    assert d["farol_previsao"] == "📉"
    assert d["previsao_vs_meta"] == "-50,0% vs meta do mês"
    assert d["titulo_previsao"] == "PREVISÃO DE FECHAMENTO"
    assert "🔴" in d["pontos_atencao"] and "abaixo da meta" in d["pontos_atencao"]


def test_previsao_na_meta_fica_verde_e_sem_pontos(monkeypatch):
    _hoje(monkeypatch, 2026, 8, 29)
    visao = {"diario": [{"dia": 27, "realizado": 1000.0, "meta": 1000.0},
                        {"dia": 30, "realizado": 0.0, "meta": 1000.0}]}
    d = v.faturamento_diario(visao)
    assert d["farol_previsao"] == "📈"
    assert d["pontos_atencao"].startswith("✅")


def test_dias_seguidos_abaixo_da_meta_viram_ponto_de_atencao(monkeypatch):
    """Três dias fechados abaixo — o de hoje NÃO conta (ainda vai acontecer)."""
    _hoje(monkeypatch, 2026, 8, 29)
    visao = {"diario": [{"dia": 26, "realizado": 50.0, "meta": 100.0},
                        {"dia": 27, "realizado": 50.0, "meta": 100.0},
                        {"dia": 28, "realizado": 50.0, "meta": 100.0},
                        {"dia": 29, "realizado": 0.0, "meta": 100.0}]}
    d = v.faturamento_diario(visao)
    assert "📉 3 dias seguidos abaixo da meta diária" in d["pontos_atencao"]


def test_ritmo_necessario_divide_a_falta_pelos_dias_com_meta(monkeypatch):
    """Falta 1.000 e restam 2 dias com meta (hoje conta: às 07:00 o dia
    inteiro está pela frente). Domingo no meio não entra no divisor."""
    _hoje(monkeypatch, 2026, 8, 29)
    visao = {"diario": [{"dia": 28, "realizado": 1000.0, "meta": 1000.0},
                        {"dia": 29, "realizado": 0.0, "meta": 500.0},
                        {"dia": 30, "realizado": 0.0, "meta": 0.0},
                        {"dia": 31, "realizado": 0.0, "meta": 500.0}]}
    d = v.faturamento_diario(visao)
    assert d["linha_ritmo"] == "Ritmo p/ meta: R$ 500,00/dia (2 dias com meta)"


def test_meta_do_mes_ja_batida_e_dito_em_vez_de_ritmo_zero(monkeypatch):
    _hoje(monkeypatch, 2026, 8, 29)
    visao = {"diario": [{"dia": 28, "realizado": 3000.0, "meta": 1000.0},
                        {"dia": 30, "realizado": 0.0, "meta": 1000.0}]}
    assert "batida" in v.faturamento_diario(visao)["linha_ritmo"]


def test_o_link_do_painel_esta_presente_e_e_https(monkeypatch):
    _hoje(monkeypatch, 2026, 8, 29)
    d = v.faturamento_diario(VISAO)
    assert d["link_painel"].startswith("https://")


# ---------------------------------------------------------------------------
# O dia 1º: a mensagem vira o FECHAMENTO do mês anterior
# ---------------------------------------------------------------------------

DIARIO_AGO = [{"dia": i, "realizado": 400000.0, "meta": 450000.0}
              for i in range(1, 31)] + \
             [{"dia": 31, "realizado": 500000.0, "meta": 450000.0}]
# total realizado 12,5 mi · meta 13,95 mi → 89,6%


def test_dia_1_mostra_o_fechamento_do_mes_anterior(monkeypatch):
    """"No caso do dia primeiro mostrar o fechamento do mês" — o diário lido
    é o do mês ANTERIOR, o título muda e a previsão vira resultado final."""
    _hoje(monkeypatch, 2026, 9, 1)
    d = v.faturamento_diario({"diario": [], "faturamento_mes_ant": 0},
                             diario_ant=DIARIO_AGO)
    assert d["titulo_mes"] == "FECHAMENTO DE AGOSTO"
    assert d["titulo_previsao"] == "RESULTADO FINAL"
    assert d["data"] == "31/08/2026"                   # ontem, o último dia
    assert d["faturado_dia"] == "R$ 500.000,00"
    assert d["acumulado_mes"] == "R$ 12.500.000,00"
    assert d["meta_mes"] == "R$ 13.950.000,00"
    assert d["atingimento_mes"] == "89,6%"
    # o resultado final é o próprio realizado — não há mais o que prever
    assert d["previsao_mes"] == "R$ 12.500.000,00"
    assert d["farol_previsao"] == "📉"
    assert "🔴 Fechou R$ 1.450.000,00 abaixo da meta" in d["pontos_atencao"]
    assert "Média realizada" in d["linha_ritmo"]
    assert d.get("_silencio") is None


def test_dia_1_com_meta_batida_celebra(monkeypatch):
    _hoje(monkeypatch, 2026, 9, 1)
    diario = [{"dia": 30, "realizado": 2000.0, "meta": 1000.0},
              {"dia": 31, "realizado": 2000.0, "meta": 1000.0}]
    d = v.faturamento_diario({"diario": []}, diario_ant=diario)
    assert "✅ Meta do mês batida" in d["pontos_atencao"]
    assert d["farol_previsao"] == "📈"


def test_dia_1_com_mes_anterior_vazio_silencia(monkeypatch):
    """Sem movimento nem meta no mês anterior não há fechamento a anunciar."""
    _hoje(monkeypatch, 2026, 9, 1)
    d = v.faturamento_diario({"diario": []}, diario_ant=[])
    assert "_silencio" in d
