# -*- coding: utf-8 -*-
"""Elegiveis fora de portal: a direcao que a conciliacao nao olha.

O ERP e a fonte da verdade aqui, e nao o portal -- so a Tupy tem integracao,
e uma posicao de portal desatualizada nao pode se disfarcar de "nao ha nada a
antecipar". Os testes abaixo travam as quatro decisoes que fazem esse numero
ser confiavel: a chave normalizada, o escopo por sacado, o piso de prazo e a
separacao entre filial cadastrada e filial da mesma raiz.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api import pglocal
from api.antecipacoes import elegiveis


class TestChave:
    def test_normaliza_zeros_e_sufixo_de_parcela(self):
        # a forma da Monkey e a do ERP tem de virar a MESMA chave: e este
        # par exato que fazia 0 de 288 casarem
        assert elegiveis.normalizar_documento("000051366-1") == "51366"
        assert elegiveis.normalizar_documento("51366") == "51366"
        assert elegiveis.normalizar_documento(" 000102113 ") == "102113"
        assert elegiveis.normalizar_documento(100226.0) == "1002260"

    def test_documento_vazio_nao_vira_chave(self):
        # string vazia como chave faria TODOS os vazios casarem entre si
        for x in ("", "   ", None, "-", "0000", "0-0"):
            assert elegiveis.normalizar_documento(x) is None, x


class TestCurva:
    """A curva de taxa e MEDIDA, e uma faixa sem base nao vira preco."""

    # LITERAL, copiado da medicao real de 09/09/2026 — nunca derivado do
    # codigo que o le: duble montado a partir da constante testada nao testa
    # a constante.
    LINHAS = [
        {"teto": 20, "base": 13, "taxa": 1.1361, "nominal": 33084.0,
         "tx_ponderada": 33084.0 * 1.1361},
        {"teto": 40, "base": 35, "taxa": 1.1797, "nominal": 34944.0,
         "tx_ponderada": 34944.0 * 1.1797},
        {"teto": 60, "base": 102, "taxa": 1.1857, "nominal": 126818.0,
         "tx_ponderada": 126818.0 * 1.1857},
        {"teto": 84, "base": 847, "taxa": 1.1747, "nominal": 1807246.0,
         "tx_ponderada": 1807246.0 * 1.1747},
        {"teto": 999999, "base": 348, "taxa": 1.1644, "nominal": 1070269.0,
         "tx_ponderada": 1070269.0 * 1.1644},
    ]

    def test_faixa_sem_base_cai_na_referencia_em_vez_de_virar_preco(self):
        faixas, ref = elegiveis.montar_curva(self.LINHAS, base_minima=50)
        por_teto = {t: tx for t, tx, _ in faixas}
        # 13 e 35 titulos nao formam preco: as duas usam a referencia
        assert por_teto[20] == pytest.approx(ref)
        assert por_teto[40] == pytest.approx(ref)
        # 102, 847 e 348 formam: cada uma fica com a propria taxa
        assert por_teto[60] == pytest.approx(1.1857)
        assert por_teto[84] == pytest.approx(1.1747)
        assert por_teto[999999] == pytest.approx(1.1644)

    def test_a_referencia_e_ponderada_pelo_valor_nunca_media_das_medias(self):
        # Sem numero magico: o duble e aproximado (nominal arredondado), entao
        # travar o valor exato so testaria a aritmetica do proprio duble. O que
        # se afirma aqui e a PROPRIEDADE — a faixa de 847 titulos e R$ 1,8 mi
        # manda mais que a de 13 titulos e R$ 33 mil.
        _, ref = elegiveis.montar_curva(self.LINHAS)
        simples = sum(l["taxa"] for l in self.LINHAS) / len(self.LINHAS)
        curta = next(l["taxa"] for l in self.LINHAS if l["teto"] == 20)
        pesada = next(l["taxa"] for l in self.LINHAS if l["teto"] == 84)
        assert abs(ref - pesada) < abs(ref - curta), \
            "a referencia tem de puxar para a faixa com mais valor"
        assert abs(ref - simples) > 1e-3, (ref, simples)
        assert min(l["taxa"] for l in self.LINHAS) < ref < max(
            l["taxa"] for l in self.LINHAS), ref

    def test_sem_medicao_nao_se_inventa_taxa(self):
        faixas, ref = elegiveis.montar_curva([])
        assert (faixas, ref) == (None, None)
        assert elegiveis.taxa_estimada(60, faixas, ref) is None,             "sem base, o desagio fica em branco em vez de virar numero"

    def test_o_prazo_escolhe_a_faixa_e_o_extremo_nao_estoura(self):
        faixas, ref = elegiveis.montar_curva(self.LINHAS)
        assert elegiveis.taxa_estimada(70, faixas, ref) == pytest.approx(1.1747)
        assert elegiveis.taxa_estimada(10_000, faixas, ref) == pytest.approx(1.1644)


@pytest.fixture()
def cenario(esquema_pg):
    """Um sacado cadastrado, uma filial da mesma raiz SEM cadastro."""
    with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ant_sacados (cnpj, nome, portal, elegivel)"
                    " VALUES ('11111111000101','ACME MATRIZ','tupy',1),"
                    "        ('22222222000101','FORA DO CONVENIO',NULL,0)")
    return esquema_pg


def _erp(rows):
    """Dubla o contas a receber do ERP. LITERAL, nunca derivado do codigo que
    o le -- entrada que representa formato externo se copia do real."""
    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a, **k): self._r = rows
        def fetchall(self): return self._r
    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return _Cur()
    return lambda: _Conn()


class TestElegiveis:
    def test_o_que_esta_no_portal_nao_conta_como_oportunidade(
            self, cenario, monkeypatch):
        hoje = date(2026, 9, 9)
        venc = hoje + timedelta(days=60)
        monkeypatch.setattr(elegiveis.db, "get_conn", _erp([
            {"documento": "51366", "cnpj": "11111111000101", "vencimento": venc,
             "sacado": "ACME MATRIZ", "valor": 1000.0},
            {"documento": "51367", "cnpj": "11111111000101", "vencimento": venc,
             "sacado": "ACME MATRIZ", "valor": 2000.0},
        ]))
        # o 51366 esta no portal, gravado na forma da Monkey
        with pglocal.get_conn(cenario) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO mky_recebiveis (seller_id, external_id,"
                        " status, sponsor_cnpj, invoice_number)"
                        " VALUES ('1','X','SOLD','11111111000101','000051366-1')")
        d = elegiveis.montar(esquema=cenario, hoje=hoje)
        g = d["linhas"][0]
        assert g["no_portal"] == 1 and g["valor_no_portal"] == 1000.0, \
            "a chave normalizada tem de reconhecer 000051366-1 como 51366"
        assert g["antecipavel"] == 1 and g["valor_antecipavel"] == 2000.0

    def test_documento_de_OUTRO_sacado_nao_marca_como_ja_antecipado(
            self, cenario, monkeypatch):
        # numeracao de NF se repete entre emitentes: a nota 51366 da ACME nao
        # e a nota 51366 de outro sacado. Sem escopo, esta linha sumiria.
        hoje = date(2026, 9, 9)
        monkeypatch.setattr(elegiveis.db, "get_conn", _erp([
            {"documento": "51366", "cnpj": "11111111000101",
             "vencimento": hoje + timedelta(days=60),
             "sacado": "ACME MATRIZ", "valor": 5000.0},
        ]))
        with pglocal.get_conn(cenario) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO mky_recebiveis (seller_id, external_id,"
                        " status, sponsor_cnpj, invoice_number)"
                        " VALUES ('1','X','SOLD','99999999000199','000051366-1')")
        g = elegiveis.montar(esquema=cenario, hoje=hoje)["linhas"][0]
        assert g["antecipavel"] == 1 and g["no_portal"] == 0, \
            "casou nota de sacado diferente"

    def test_prazo_curto_sai_do_total_mas_continua_visivel(
            self, cenario, monkeypatch):
        hoje = date(2026, 9, 9)
        monkeypatch.setattr(elegiveis.db, "get_conn", _erp([
            {"documento": "1", "cnpj": "11111111000101",
             "vencimento": hoje + timedelta(days=3),
             "sacado": "ACME MATRIZ", "valor": 9000.0},
            {"documento": "2", "cnpj": "11111111000101",
             "vencimento": hoje + timedelta(days=60),
             "sacado": "ACME MATRIZ", "valor": 1000.0},
        ]))
        g = elegiveis.montar(esquema=cenario, hoje=hoje)["linhas"][0]
        assert g["valor_antecipavel"] == 1000.0, "3 dias nao e operacao"
        assert g["curto"] == 1 and g["valor_curto"] == 9000.0, \
            "o curto prazo tem de continuar visivel, nao sumir do total"
        assert g["fora"] == 2

    def test_filial_da_mesma_raiz_nao_entra_no_total_dos_cadastrados(
            self, cenario, monkeypatch):
        hoje = date(2026, 9, 9)
        venc = hoje + timedelta(days=60)
        monkeypatch.setattr(elegiveis.db, "get_conn", _erp([
            {"documento": "1", "cnpj": "11111111000101", "vencimento": venc,
             "sacado": "ACME MATRIZ", "valor": 1000.0},
            {"documento": "2", "cnpj": "11111111000999", "vencimento": venc,
             "sacado": "ACME OUTRA FILIAL", "valor": 8000.0},
        ]))
        d = elegiveis.montar(esquema=cenario, hoje=hoje)
        assert d["cadastrados"]["valor"] == 1000.0, \
            "presumir que a raiz e elegivel inventa oportunidade"
        assert d["mesma_raiz"]["valor"] == 8000.0
        assert d["mesma_raiz"]["sacados"] == 1
        naocad = [g for g in d["linhas"] if not g["cadastrado"]]
        assert len(naocad) == 1 and naocad[0]["cnpj"] == "11111111000999"

    def test_sacado_nao_elegivel_fica_de_fora_da_consulta(self, cenario):
        # a raiz 22222222 tem elegivel=0: nem chega a ser perguntada ao ERP
        with pglocal.get_conn(cenario) as conn, conn.cursor() as cur:
            cur.execute("SELECT cnpj FROM ant_sacados WHERE elegivel = 1")
            assert [r["cnpj"] for r in cur.fetchall()] == ["11111111000101"]

    def test_sem_sacado_elegivel_diz_o_motivo_em_vez_de_zero_verde(
            self, esquema_pg):
        d = elegiveis.montar(esquema=esquema_pg, hoje=date(2026, 9, 9))
        assert d["disponivel"] is False and "sacado" in d["motivo"]
