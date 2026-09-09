# -*- coding: utf-8 -*-
"""A antecipacao como linha de credito, e o contrafactual.

O que estes testes travam nao e aritmetica: sao as tres formas de mentir com
estes numeros. Somar o nominal e chamar de divida (erra por um fator de 5),
deixar um investidor de dois titulos definir o "melhor preco" (inventa
economia que ninguem poderia ter capturado), e publicar a economia de um
corte de prazo sem o caixa que ela custa (propaganda).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api import pglocal
from api.antecipacoes import estrategia


def _inserir(esquema, linhas):
    """linhas: (ext, investidor, dias_atras, prazo, valor, taxa)."""
    hoje = date.today()
    with pglocal.get_conn(esquema) as conn, conn.cursor() as cur:
        for ext, inv, atras, prazo, valor, taxa in linhas:
            criado = hoje - timedelta(days=atras)
            venc = criado + timedelta(days=prazo)
            recebe = valor - valor * taxa / 100.0 * prazo / 30.0
            # `buyer_nome` E OBRIGATORIO AQUI, e esquece-lo custou dois testes
            # vermelhos que pareciam defeito do modulo: sem investidor, o
            # contrafactual agrupa tudo num balde so, o "melhor preco" vira a
            # media de todo mundo e a economia da exatamente ZERO. Duble que
            # omite a coluna sobre a qual a analise inteira gira nao testa a
            # analise -- testa a media consigo mesma.
            cur.execute(
                "INSERT INTO mky_recebiveis (seller_id, external_id, status,"
                " sponsor_cnpj, invoice_number, buyer_nome, payment_value,"
                " receipt_value, purchased_tax, payment_date, criado_fornecedor)"
                " VALUES ('1', %s, 'SOLD', '111', %s, %s, %s, %s, %s, %s, %s)",
                (ext, ext, inv, valor, recebe, taxa, venc, criado))


class TestLinhaDeCredito:
    def test_capital_medio_nao_e_a_soma_do_nominal(self, esquema_pg):
        # R$ 100 mil antecipados por 73 dias NAO sao R$ 100 mil de divida:
        # sao 100.000 x 73/365 = R$ 20 mil de capital medio. Confundir os dois
        # multiplica a divida por 5 nesta carteira.
        _inserir(esquema_pg, [("A", "BANCO X", 10, 73, 100000.0, 1.20)])
        L = estrategia.montar(esquema=esquema_pg)["linha"]
        assert L["nominal"] == pytest.approx(100000.0)
        assert L["capital_medio"] == pytest.approx(100000.0 * 73 / 365, rel=1e-6)
        assert L["capital_medio"] < L["nominal"] / 4, \
            "capital medio virou soma do nominal"
        assert L["giros"] == pytest.approx(365 / 73, rel=1e-6)

    def test_custo_efetivo_e_sobre_o_capital_e_nao_sobre_o_nominal(
            self, esquema_pg):
        _inserir(esquema_pg, [("A", "BANCO X", 10, 73, 100000.0, 1.20)])
        L = estrategia.montar(esquema=esquema_pg)["linha"]
        # desagio de 1,20% a.m. por 73 dias = 2,92% do nominal...
        assert L["desagio_pct"] == pytest.approx(2.92, abs=0.01)
        # ...que sobre o capital MEDIO e' cinco vezes isso ao ano
        assert L["custo_efetivo_aa"] == pytest.approx(
            L["custo"] / L["capital_medio"] * 100, rel=1e-9)
        assert L["custo_efetivo_aa"] > 4 * L["desagio_pct"], \
            "o custo anual saiu sobre o nominal, e nao sobre o capital"


class TestContrafactual:
    def test_investidor_sem_base_nao_define_o_melhor_preco(self, esquema_pg):
        # 40 titulos a 1,30 com o BANCO CARO e UM titulo a 0,50 com o BARATO.
        # Aquele 0,50 nao era uma porta por onde o volume inteiro passaria:
        # deixa-lo definir o melhor preco inventaria uma economia enorme.
        linhas = [(f"C{i}", "BANCO CARO", 10, 60, 10000.0, 1.30)
                  for i in range(40)]
        linhas.append(("B1", "BANCO BARATO", 10, 60, 10000.0, 0.50))
        _inserir(esquema_pg, linhas)
        c = estrategia.montar(esquema=esquema_pg)["contrafactual"]
        assert c["economia"] < 1.0, (
            "um investidor com 1 titulo nao pode virar o preco de referencia; "
            f"economia apurada: {c['economia']}")

    def test_com_base_dos_dois_lados_a_economia_aparece(self, esquema_pg):
        # agora o BARATO tem 25 titulos: era alternativa de verdade
        linhas = [(f"C{i}", "BANCO CARO", 10, 60, 10000.0, 1.30)
                  for i in range(25)]
        linhas += [(f"B{i}", "BANCO BARATO", 10, 60, 10000.0, 1.00)
                   for i in range(25)]
        _inserir(esquema_pg, linhas)
        c = estrategia.montar(esquema=esquema_pg)["contrafactual"]
        # os 25 caros pagaram 0,30 p.p. a mais por 2 meses sobre R$ 250 mil
        assert c["economia"] == pytest.approx(250000 * 0.30 / 100 * 2, rel=0.02)
        assert c["economia_pct"] > 0

    def test_o_contrafactual_nunca_e_negativo_no_agregado(self, esquema_pg):
        # o melhor preco e' um MINIMO: por construcao nao pode custar mais
        linhas = [(f"X{i}", "BANCO A" if i % 2 else "BANCO B", 10 + i % 5,
                   45 + i, 5000.0 + i, 1.0 + (i % 7) / 10.0) for i in range(60)]
        _inserir(esquema_pg, linhas)
        c = estrategia.montar(esquema=esquema_pg)["contrafactual"]
        assert c["economia"] >= -0.01, c["economia"]
        assert c["no_melhor_preco"] <= c["pago"] + 0.01


class TestCortes:
    def test_todo_corte_publica_o_caixa_que_ele_custa(self, esquema_pg):
        _inserir(esquema_pg, [
            ("CURTO", "BANCO X", 5, 20, 50000.0, 1.20),
            ("LONGO", "BANCO X", 5, 80, 50000.0, 1.20)])
        cortes = {c["dias"]: c for c in estrategia.montar(esquema=esquema_pg)["cortes"]}
        c30 = cortes[30]
        assert c30["economia"] > 0, "cortar em 30 dias tira o titulo de 20 dias"
        assert c30["caixa_abre_mao"] == pytest.approx(50000.0), \
            "economia sem o caixa que ela custa e' propaganda"
        assert c30["titulos_fora"] == 1
        # o preco da economia, na mesma unidade: reais de caixa por real poupado
        assert c30["caixa_por_real"] == pytest.approx(
            c30["caixa_abre_mao"] / c30["economia"], rel=1e-9)
        assert c30["caixa_por_real"] > 1, \
            "se um real de economia custasse menos de um real de caixa, o " \
            "corte seria obvio — e nao e'"

    def test_sem_antecipacao_diz_o_motivo_em_vez_de_zero_verde(self, esquema_pg):
        d = estrategia.montar(esquema=esquema_pg)
        assert d["disponivel"] is False and "antecipa" in d["motivo"]
