"""Os números do resumo diário de faturamento.

Este arquivo existe por causa de UMA armadilha específica do CÓRTEX: há TRÊS
recortes de receita na mesma resposta da Visão Geral, e eles não são o mesmo
número —

    faturamento_mes        faturas emitidas       R$ 11,28 mi
    realizado_acumulado    a régua da META        R$ 10,73 mi
    receita_mes_cte        CT-e                   (outro corte ainda)

Misturar o numerador de uma régua com o denominador de outra dá um atingimento
de 96% onde o real é 91,3% — e a mensagem sai para a diretoria dizendo que a
meta está quase batida quando falta um milhão.
"""
from __future__ import annotations

from datetime import date

from api.whatsapp import valores as v

# Recorte real da Visão Geral em 28/08/2026, com os três números de receita
# lado a lado, que é o que torna a confusão possível.
VISAO = {
    "faturamento_mes": 11287791.78,        # faturas emitidas — NÃO é a régua
    "realizado_acumulado": 10735390.66,    # a régua da meta
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


def test_formata_em_real_sem_depender_de_locale():
    """O Windows desta bancada não tem locale pt-BR instalado."""
    assert v.brl(10735390.66) == "R$ 10.735.390,66"
    assert v.brl(0) == "R$ 0,00"
    assert v.brl(-1234.5) == "-R$ 1.234,50"
    assert v.brl(None) == "R$ 0,00"


def test_o_atingimento_do_mes_vem_PRONTO_e_nao_e_recalculado():
    """A conta certa é `realizado_acumulado / meta_acumulada` = 91,3%.
    Recalcular aqui abriria a chance de usar `faturamento_mes` (11,28 mi) por
    engano, que daria 96% — quase-batida onde falta um milhão."""
    d = v.faturamento_diario(VISAO)
    assert d["atingimento_mes"] == "91,3%"
    assert d["acumulado_mes"] == "R$ 10.735.390,66"   # a régua, não as faturas
    assert "11.287.791" not in str(d)                  # faturas emitidas não entram


def test_o_dia_e_o_ULTIMO_COM_MOVIMENTO_e_nao_o_ultimo_da_serie():
    """Os dias 29 e 30 ainda não aconteceram. Pegar o fim da série mandaria
    "faturamos R$ 0" todo dia."""
    d = v.faturamento_diario(VISAO)
    assert d["faturado_dia"] == "R$ 104.007,09"        # dia 28, não o 30


def test_dia_em_curso_e_DITO_na_mensagem(monkeypatch):
    """Às 11h o dia tinha 20% da meta: número certo, leitura desastrosa. Quem
    lê no celular não tem a hachura do painel para avisar."""
    class _Hoje(date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 28)           # o mesmo dia do último movimento

    monkeypatch.setattr(v, "date", _Hoje)
    d = v.faturamento_diario(VISAO)
    assert "dia ainda em curso" in d["atingimento_dia"]
    assert d["atingimento_dia"].startswith("18,8%")


def test_dia_FECHADO_nao_leva_a_marca(monkeypatch):
    class _Hoje(date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 29)           # o dia 28 já fechou

    monkeypatch.setattr(v, "date", _Hoje)
    d = v.faturamento_diario(VISAO)
    assert d["atingimento_dia"] == "18,8%"
    assert "em curso" not in d["atingimento_dia"]


def test_dia_sem_meta_nao_e_zero_por_cento():
    """Domingo e feriado não têm meta. "0,0%" acusaria quem cumpriu."""
    visao = {**VISAO, "diario": [{"dia": 28, "realizado": 5000.0, "meta": 0.0}]}
    assert v.faturamento_diario(visao)["atingimento_dia"] == "sem meta no dia"


def test_falta_para_a_meta_nunca_e_negativa():
    """Meta superada mostra "R$ 0,00" a faltar, não um valor negativo que se
    lê como dívida."""
    visao = {**VISAO, "realizado_acumulado": 12000000.0}
    assert v.faturamento_diario(visao)["falta_mes"] == "R$ 0,00"


def test_mes_sem_movimento_nenhum_nao_estoura():
    d = v.faturamento_diario({"diario": [], "meta_acumulada": 0,
                              "realizado_acumulado": 0})
    assert d["faturado_dia"] == "R$ 0,00"
    assert d["atingimento_dia"] == "sem meta no dia"


def test_todas_as_variaveis_do_contexto_sao_preenchidas():
    """O contrato: o catálogo declara nove variáveis e o provedor entrega as
    nove. Uma faltando deixaria o envio recusado por variável em branco — e o
    defeito só apareceria na hora de mandar."""
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
