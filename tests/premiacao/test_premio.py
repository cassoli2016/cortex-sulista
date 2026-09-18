# -*- coding: utf-8 -*-
"""O que se paga: base × nota, com teto de 100%.

Os valores destes testes são INVENTADOS — 100, 200, 1000. A tabela real vive no
banco e não entra no repositório, que é público; um teste com os números da
casa publicaria a folha em texto claro.

O que estes testes seguram:

- teto de 100%: a reputação passa de 100 de propósito, o pagamento não;
- SEM TABELA NÃO PAGA ZERO. Zero é um número que alguém decidiu; ausência de
  cadastro é outra coisa, e a linha diz qual das duas é;
- a escada de tempo de casa substitui o valor fixo da filial, e quem está sem
  admissão cai no PRIMEIRO degrau — na dúvida a casa não paga a mais;
- o ajuste manual vence tudo, exige motivo e autor, e EXPIRA com o ciclo;
- o valor vale por VERSÃO: mexer em setembro não mexe no que agosto pagou.
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.premiacao import config, identidade, parametros, premio, ranking

CICLO = "2026-09"


@pytest.fixture
def base(esquema_pg, monkeypatch):
    for mod in (premio, parametros, config, identidade):
        monkeypatch.setattr(mod, "ESQUEMA", esquema_pg)
    _motorista(esquema_pg, "11111111111", "111", "MOTORISTA UM", "RODOVIARIO",
               "SBC", "2020-01")
    _motorista(esquema_pg, "22222222222", "222", "MOTORISTA DOIS", "MANOBRA",
               "JOI", "2026-05")
    return esquema_pg


def _motorista(esq, cpf, codigo, nome, tipo, filial, admissao):
    pglocal.executar(
        "INSERT INTO prm_motorista(cpf, nome, cadastro_codigo, tipo,"
        " tipo_origem, filial, filial_origem, admissao, ativo)"
        " VALUES(%s,%s,%s,%s,'manual',%s,'folha',%s,1)",
        (cpf, nome, codigo, tipo, filial, admissao), esquema=esq)


def _ranking(**notas):
    """Um ranking de mentira: só o que o pagamento lê."""
    linhas = []
    for codigo, nota in notas.items():
        linhas.append({
            "motorista": codigo.replace("m", ""), "nome": f"MOTORISTA {codigo}",
            "tipo": "RODOVIARIO" if codigo == "m111" else "MANOBRA",
            "filial": "SBC" if codigo == "m111" else "JOI",
            "admissao": "2020-01" if codigo == "m111" else "2026-05",
            "gobrax": None, "conduta": nota, "gr": None,
            "nota": nota, "status": "BOM", "categoria": "OURO",
        })
    return {"ciclo": CICLO, "rotulo": "16/08 a 15/09 de 2026", "linhas": linhas,
            "fontes": {}, "pendencias": {}}


def _com(monkeypatch, **notas):
    monkeypatch.setattr(ranking, "montar",
                        lambda c=None, dir_snapshots=None: _ranking(**notas))


# ------------------------------------------------------------------ a conta
@pytest.mark.parametrize("base_valor, nota, esperado", [
    (1000, 100, 1000.0),
    (1000, 86.3, 863.0),
    (1000, 0, 0.0),
    (1000, 106, 1000.0),      # TETO: a reputação passa de 100, o pagamento não
    (1000, -5, 0.0),
])
def test_o_premio_e_base_vezes_nota_com_TETO_de_100(base_valor, nota, esperado):
    assert premio.valor_do_premio(base_valor, nota)["valor"] == esperado


def test_sem_base_ou_sem_nota_NAO_ha_valor():
    assert premio.valor_do_premio(None, 90)["valor"] is None
    assert premio.valor_do_premio(1000, None)["valor"] is None


# --------------------------------------------------------------- a tabela
def test_sem_tabela_a_linha_NAO_paga_zero_e_diz_o_motivo(base, monkeypatch):
    """Zero é um número que alguém decidiu. Ausência de cadastro é outra coisa."""
    _com(monkeypatch, m111=90.0)
    linha = premio.montar(CICLO)["linhas"][0]
    assert linha["valor"] is None and linha["base"] is None
    assert linha["base_origem"] == "sem_tabela"
    assert "sem valor na tabela" in linha["motivo"]


def test_o_valor_da_filial_paga_a_nota_do_ciclo(base, monkeypatch):
    premio.salvar_tabela(CICLO, "RODOVIARIO", {"SBC": {"valor": 1000}},
                         autor="gestor")
    _com(monkeypatch, m111=90.0)
    linha = premio.montar(CICLO)["linhas"][0]
    assert linha["base"] == 1000.0 and linha["base_origem"] == "tabela"
    assert linha["valor"] == 900.0 and linha["motivo"] == ""


def test_o_valor_vale_por_VERSAO_e_o_ciclo_passado_nao_muda(base, monkeypatch):
    premio.salvar_tabela("2026-01", "RODOVIARIO", {"SBC": {"valor": 1000}},
                         autor="gestor")
    premio.salvar_tabela("2026-09", "RODOVIARIO", {"SBC": {"valor": 2000}},
                         autor="gestor")
    assert premio.tabela("2026-05")["base"]["RODOVIARIO"]["SBC"]["valor"] == 1000
    assert premio.tabela("2026-09")["base"]["RODOVIARIO"]["SBC"]["valor"] == 2000


def test_salvar_recusa_grupo_desconhecido_valor_negativo_e_autor_vazio(base):
    with pytest.raises(ValueError, match="Grupo inválido"):
        premio.salvar_tabela(CICLO, "ENTREGADOR", {"SBC": {"valor": 1}}, "x")
    with pytest.raises(ValueError, match="negativo"):
        premio.salvar_tabela(CICLO, "RODOVIARIO", {"SBC": {"valor": -1}}, "x")
    with pytest.raises(ValueError, match="quem está salvando"):
        premio.salvar_tabela(CICLO, "RODOVIARIO", {"SBC": {"valor": 1}}, "")


# ------------------------------------------------------ escada de tempo de casa
def test_a_escada_SUBSTITUI_o_valor_fixo_da_filial(base, monkeypatch):
    premio.salvar_tabela(CICLO, "MANOBRA",
                         {"JOI": {"valor": 9999, "usa_escada": True}},
                         autor="gestor")
    premio.salvar_escada(CICLO, "MANOBRA", [
        {"ate_meses": 6, "valor": 100}, {"ate_meses": 12, "valor": 200},
        {"ate_meses": 9999, "valor": 300}], autor="gestor")
    _com(monkeypatch, m222=100.0)
    linha = premio.montar(CICLO)["linhas"][0]
    assert linha["meses_casa"] == 4            # admitido em 2026-05, ciclo 09
    assert linha["base"] == 100.0 and linha["base_origem"] == "escada"
    assert linha["valor"] == 100.0


@pytest.mark.parametrize("meses, esperado", [
    (0, 100), (6, 100), (7, 200), (12, 200), (13, 300), (400, 300),
    (None, 100),        # sem admissão: PRIMEIRO degrau, nunca o último
])
def test_o_degrau_e_o_primeiro_que_cabe_e_sem_admissao_e_o_menor(meses, esperado):
    degraus = [{"ate_meses": 12, "valor": 200}, {"ate_meses": 6, "valor": 100},
               {"ate_meses": 9999, "valor": 300}]     # fora de ordem de propósito
    assert premio.valor_da_escada(degraus, meses) == esperado


def test_a_escada_e_SUBSTITUIDA_por_inteiro(base):
    """Degrau que sai do formulário tem de sair do banco — senão continua
    pagando calado."""
    premio.salvar_escada(CICLO, "MANOBRA", [
        {"ate_meses": 6, "valor": 100}, {"ate_meses": 12, "valor": 200}],
        autor="gestor")
    premio.salvar_escada(CICLO, "MANOBRA", [{"ate_meses": 6, "valor": 100}],
                         autor="gestor")
    assert premio.tabela(CICLO)["escada"]["MANOBRA"] == [
        {"ate_meses": 6, "valor": 100.0}]


def test_a_escada_recusa_dois_degraus_com_o_mesmo_limite(base):
    with pytest.raises(ValueError, match="mesmo limite"):
        premio.salvar_escada(CICLO, "MANOBRA", [
            {"ate_meses": 6, "valor": 100}, {"ate_meses": 6, "valor": 200}],
            autor="gestor")


@pytest.mark.parametrize("admissao, ciclo, esperado", [
    ("2020-01", "2026-09", 80), ("2026-09", "2026-09", 0),
    ("2026-12", "2026-09", 0),          # admissão futura não vira tempo negativo
    (None, "2026-09", None), ("", "2026-09", None),
])
def test_os_meses_de_casa(admissao, ciclo, esperado):
    assert premio.meses_de_casa(admissao, ciclo) == esperado


# ----------------------------------------------------------------- o ajuste
def test_o_ajuste_VENCE_a_tabela_e_diz_de_onde_veio(base, monkeypatch):
    premio.salvar_tabela(CICLO, "RODOVIARIO", {"SBC": {"valor": 1000}},
                         autor="gestor")
    premio.ajustar(CICLO, "11111111111", 500, motivo="acordo de transição",
                   autor="gestor")
    _com(monkeypatch, m111=90.0)
    linha = premio.montar(CICLO)["linhas"][0]
    assert linha["base"] == 500.0 and linha["base_origem"] == "ajuste"
    assert linha["ajuste_motivo"] == "acordo de transição"
    assert linha["valor"] == 450.0


def test_o_ajuste_EXIGE_motivo_e_autor(base):
    with pytest.raises(ValueError, match="motivo"):
        premio.ajustar(CICLO, "11111111111", 500, motivo="  ", autor="gestor")
    with pytest.raises(ValueError, match="quem está ajustando"):
        premio.ajustar(CICLO, "11111111111", 500, motivo="x", autor="")


def test_o_ajuste_e_DO_CICLO_e_nao_vaza_para_o_seguinte(base):
    premio.ajustar(CICLO, "11111111111", 500, motivo="x", autor="gestor")
    assert "11111111111" in premio.ajustes(CICLO)
    assert premio.ajustes("2026-10") == {}


def test_limpar_o_ajuste_devolve_o_motorista_a_tabela(base, monkeypatch):
    premio.salvar_tabela(CICLO, "RODOVIARIO", {"SBC": {"valor": 1000}},
                         autor="gestor")
    premio.ajustar(CICLO, "11111111111", 500, motivo="x", autor="gestor")
    premio.limpar_ajuste(CICLO, "11111111111")
    _com(monkeypatch, m111=90.0)
    linha = premio.montar(CICLO)["linhas"][0]
    assert linha["base"] == 1000.0 and linha["base_origem"] == "tabela"


# ------------------------------------------------------------------- a tela
def test_sem_nota_no_ciclo_NAO_se_paga_e_a_linha_diz(base, monkeypatch):
    premio.salvar_tabela(CICLO, "RODOVIARIO", {"SBC": {"valor": 1000}},
                         autor="gestor")
    _com(monkeypatch, m111=None)
    linha = premio.montar(CICLO)["linhas"][0]
    assert linha["base"] == 1000.0 and linha["valor"] is None
    assert linha["motivo"] == "sem nota no ciclo"


def test_os_KPIs_dizem_o_a_pagar_o_TETO_e_quem_ficou_de_fora(base, monkeypatch):
    premio.salvar_tabela(CICLO, "RODOVIARIO", {"SBC": {"valor": 1000}},
                         autor="gestor")
    _com(monkeypatch, m111=90.0, m222=100.0)     # o segundo é MANOBRA sem tabela
    k = premio.montar(CICLO)["kpis"]
    assert k["a_pagar"] == 900.0
    assert k["teto"] == 1000.0, "o teto só soma quem tem valor base"
    assert k["pagos"] == 1 and k["sem_valor"] == 1 and k["sem_tabela"] == 1


def test_o_CPF_nao_sai_no_payload_do_pagamento(base, monkeypatch):
    import json
    premio.salvar_tabela(CICLO, "RODOVIARIO", {"SBC": {"valor": 1000}},
                         autor="gestor")
    premio.ajustar(CICLO, "11111111111", 500, motivo="x", autor="gestor")
    _com(monkeypatch, m111=90.0)
    assert "11111111111" not in json.dumps(premio.montar(CICLO))


def test_banco_fora_do_ar_nao_inventa_valor(base, monkeypatch):
    """Pagar por padrão de código seria a pior falha possível aqui: um número
    plausível, em reais, que ninguém decidiu."""
    def explode(*a, **k):
        raise RuntimeError("sem banco")
    monkeypatch.setattr(config, "versao_de", explode)
    tab = premio.tabela(CICLO)
    assert tab["base"] == {} and "indisponível" in tab["motivo"]
