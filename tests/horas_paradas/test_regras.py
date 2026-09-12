"""A CONTA de horas paradas, perna a perna.

Os casos têm a FORMA dos que a primeira planilha de cliente mostrou (chegou
antes da janela, chegou atrasado, saiu antes da janela, excedeu 20 minutos,
cláusula por mercadoria, exceção por destino) — com números e nomes
inventados: condição comercial de cliente não entra no repositório, que é
público. A conferência contra a planilha real foi feita fora dele (todas as
linhas ao centavo, 12/09/2026) e está descrita em `api/horas_paradas/__init__.py`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from api.horas_paradas import regras as R

D = datetime(2026, 9, 9)


def h(hh, mm=0, dia=0):
    return D + timedelta(days=dia, hours=hh, minutes=mm)


CONTRATO = [
    {"mercadoria": "", "ft_carga_h": 3.0, "ft_descarga_h": 3.0,
     "valor_coleta": 100.0, "valor_entrega": 100.0},
    {"mercadoria": "CAIXAS", "ft_carga_h": 3.0, "ft_descarga_h": 6.5,
     "valor_coleta": 100.0, "valor_entrega": 100.0},
]
PERFIL = {"inicio_carga": R.MAIOR, "inicio_descarga": R.MAIOR,
          "arredondamento_min": 0, "regras": []}


def carga(**kw):
    base = {"mercadoria": "PECAS", "destinatario_codigo": "111",
            "carga_janela": h(10), "carga_chegada": h(10), "carga_saida": h(11),
            "descarga_janela": h(15), "descarga_chegada": h(15),
            "descarga_saida": h(16)}
    base.update(kw)
    return base


def test_chegou_ANTES_da_janela_o_relogio_comeca_na_janela():
    """Esperar a hora marcada não é estadia: 07:40 → janela 10:00 → saída
    10:43 são 43 minutos, não 3h03."""
    p = R.perna(carga(carga_chegada=h(7, 40), carga_saida=h(10, 43)),
                "carga", CONTRATO, PERFIL)
    assert p["inicio_de"] == R.JANELA
    assert p["tempo_s"] == 43 * 60
    assert p["valor"] == 0


def test_chegou_ATRASADO_o_relogio_comeca_na_chegada():
    """O modo `maior` não põe na conta a hora em que o caminhão nem estava lá."""
    p = R.perna(carga(carga_chegada=h(10, 20), carga_saida=h(11, 10)),
                "carga", CONTRATO, PERFIL)
    assert p["inicio_de"] == R.CHEGADA
    assert p["tempo_s"] == 50 * 60


def test_modo_JANELA_e_a_formula_do_ERP_mesmo_com_atraso():
    """O relatório do ERP conta da janela sempre. Existe como opção porque é
    a fórmula de lá — e o teste prova que ela difere da do `maior`."""
    perfil = dict(PERFIL, inicio_carga=R.JANELA)
    p = R.perna(carga(carga_chegada=h(10, 20), carga_saida=h(11, 10)),
                "carga", CONTRATO, perfil)
    assert p["tempo_s"] == 70 * 60


def test_modo_CHEGADA_ignora_a_janela():
    perfil = dict(PERFIL, inicio_carga=R.CHEGADA)
    p = R.perna(carga(carga_janela=h(20), carga_chegada=h(7), carga_saida=h(8)),
                "carga", CONTRATO, perfil)
    assert p["inicio_de"] == R.CHEGADA and p["tempo_s"] == 3600


def test_saiu_antes_da_janela_o_tempo_fica_NEGATIVO_e_nao_cobra():
    """É FATO que a planilha mostra (saiu 5 min antes da hora marcada), não
    erro a esconder. Só o excedente é limitado a zero."""
    p = R.perna(carga(carga_janela=h(12), carga_chegada=h(8), carga_saida=h(11, 55)),
                "carga", CONTRATO, PERFIL)
    assert p["tempo_s"] == -5 * 60
    assert p["excedente_s"] == 0 and p["valor"] == 0 and p["estado"] == R.OK


@pytest.mark.parametrize("minutos, valor_h, esperado", [
    (20, 97.30, 32.43),      # 20 min a R$ 97,30/h
    (62, 97.30, 100.54),     # 1h02 — a hora arredondada ANTES daria 97,30
    (98, 97.30, 158.92),
])
def test_excedente_por_MINUTO_arredonda_so_o_dinheiro(minutos, valor_h, esperado):
    contrato = [dict(CONTRATO[0], valor_coleta=valor_h)]
    p = R.perna(carga(carga_saida=h(13, minutos)), "carga", contrato, PERFIL)
    assert p["excedente_s"] == minutos * 60
    assert p["valor"] == esperado


def test_arredondamento_para_CIMA_na_fracao_do_perfil():
    perfil = dict(PERFIL, arredondamento_min=30)
    p = R.perna(carga(carga_saida=h(13, 20)), "carga", CONTRATO, perfil)
    assert p["excedente_s"] == 20 * 60
    assert p["cobrado_s"] == 30 * 60 and p["valor"] == 50.0
    # exatamente na fração não sobe mais uma
    p = R.perna(carga(carga_saida=h(13, 30)), "carga", CONTRATO, perfil)
    assert p["cobrado_s"] == 30 * 60


def test_clausula_da_MERCADORIA_vale_antes_da_generica():
    p = R.perna(carga(mercadoria="Caixas", descarga_saida=h(22)),
                "descarga", CONTRATO, PERFIL)
    assert p["freetime_h"] == 6.5 and p["clausula"] == "mercadoria"
    assert p["excedente_s"] == 30 * 60


def test_regra_troca_o_inicio_SO_na_perna_declarada():
    perfil = dict(PERFIL, regras=[{"nome": "chega e carrega", "mercadorias": ["PECAS"],
                                   "perna": "carga", "inicio": R.CHEGADA}])
    c = carga(carga_janela=h(20), carga_chegada=h(7), carga_saida=h(8),
              descarga_janela=h(15), descarga_chegada=h(14), descarga_saida=h(16))
    out = R.calcular(c, CONTRATO, perfil)
    assert out["carga"]["inicio_de"] == R.CHEGADA
    assert out["carga"]["regra"] == "chega e carrega"
    assert out["descarga"]["inicio_de"] == R.JANELA
    assert out["descarga"]["regra"] is None


def test_regra_de_clausula_GENERICA_vence_o_nome_da_mercadoria():
    """A exceção que o contrato do ERP não diz: esta mercadoria NÃO usa a
    cláusula que o nome sugere. A linha diz qual regra respondeu."""
    perfil = dict(PERFIL, regras=[{"nome": "caixas pequenas", "mercadorias": ["CAIXAS"],
                                   "clausula": "generica"}])
    p = R.perna(carga(mercadoria="CAIXAS", descarga_saida=h(22)),
                "descarga", CONTRATO, perfil)
    assert p["freetime_h"] == 3.0 and p["clausula"] == "generico"
    assert p["regra"] == "caixas pequenas"


def test_a_PRIMEIRA_regra_que_casa_responde():
    """"Para este destino, o contrato; para os demais, a genérica" só se
    escreve com a específica ANTES da geral."""
    regras = [{"nome": "caixas p/ 111: contrato", "mercadorias": ["CAIXAS"], "destinos": ["111"]},
              {"nome": "caixas outros: generica", "mercadorias": ["CAIXAS"], "clausula": "generica"}]
    perfil = dict(PERFIL, regras=regras)
    a = R.perna(carga(mercadoria="CAIXAS", destinatario_codigo="111"), "descarga", CONTRATO, perfil)
    b = R.perna(carga(mercadoria="CAIXAS", destinatario_codigo="222"), "descarga", CONTRATO, perfil)
    assert a["freetime_h"] == 6.5 and a["regra"] == "caixas p/ 111: contrato"
    assert b["freetime_h"] == 3.0 and b["regra"] == "caixas outros: generica"


def test_destino_casa_pelo_CODIGO_e_nao_pelo_nome():
    r = {"destinos": ["111"]}
    assert R.regra_casa(r, {"destinatario_codigo": "111"}, "carga")
    assert not R.regra_casa(r, {"destinatario_codigo": "1110"}, "carga")
    assert not R.regra_casa(r, {"destinatario_codigo": "", "destino": "111"}, "carga")


def test_mercadoria_casa_pela_normalizacao_da_casa_e_nada_mais():
    """Plural, acento e caixa: sim. Prefixo ou "contém": não."""
    r = {"mercadorias": ["PEÇAS"]}
    assert R.regra_casa(r, {"mercadoria": "pecas"}, "carga")
    assert not R.regra_casa(r, {"mercadoria": "PECAS USADAS"}, "carga")


def test_None_na_regra_HERDA_e_nao_vira_zero():
    perfil = dict(PERFIL, regras=[{"nome": "so o valor", "mercadorias": ["PECAS"],
                                   "freetime_h": None, "valor_h": 200.0}])
    p = R.perna(carga(carga_saida=h(14)), "carga", CONTRATO, perfil)
    assert p["freetime_h"] == 3.0          # do contrato
    assert p["valor"] == 200.0             # 1h excedente a R$ 200


def test_sem_CHEGADA_nao_ha_relogio():
    """Sem prova de que o veículo estava lá, a janela sozinha não é estadia."""
    p = R.perna(carga(carga_chegada=None), "carga", CONTRATO, PERFIL)
    assert p["estado"] == R.SEM_APONTAMENTO and p["valor"] == 0
    assert p["tempo_s"] is None


def test_sem_CONTRATO_nao_se_inventa_freetime():
    p = R.perna(carga(carga_saida=h(20)), "carga", [], PERFIL)
    assert p["estado"] == R.SEM_CONTRATO and p["valor"] == 0
    assert p["tempo_s"] == 10 * 3600


def test_freetime_do_ERP_em_timedelta_e_aceito():
    contrato = [dict(CONTRATO[0], ft_carga_h=timedelta(hours=2))]
    p = R.perna(carga(carga_saida=h(13)), "carga", contrato, PERFIL)
    assert p["freetime_h"] == 2.0 and p["excedente_s"] == 3600


def test_total_da_carga_soma_as_duas_pernas():
    out = R.calcular(carga(carga_saida=h(13, 30), descarga_saida=h(19)), CONTRATO, PERFIL)
    assert out["carga"]["valor"] == 50.0 and out["descarga"]["valor"] == 100.0
    assert out["valor"] == 150.0
