# -*- coding: utf-8 -*-
"""A conferência documento × CT-e, sem ERP: as linhas têm a FORMA que as
consultas de `validacao.py` devolvem (os nomes de coluna vêm dos `AS` delas)."""
from __future__ import annotations

from datetime import datetime

import pytest

from api import auth
from api.validacao_whirlpool import validacao as V

COLETA = {"filial": 1, "serie": 124, "numero": 20006, "dtemissao": datetime(2026, 9, 14, 19, 0),
          "precalculo_em": datetime(2026, 9, 14, 19, 11), "pagador_nome": "PLANTA"}
ANEXO = {"id": 900, "nomearquivo": "PreCalculoInbound_0010830001", "extensao": "pdf",
         "tamanho": 32000, "dtinc": datetime(2026, 9, 14, 19, 13)}

DOC = {"formato": "precalculo", "icms_pct": 12.0, "transportadora_cnpj": "76104397000123",
       "sem_valor": False, "transporte": "10830001",
       "fornecedores": [
           {"fornecedor": "ALFA", "cnpj": "11111111000111", "frete": 1662.13, "pedagio": 54.06,
            "taxa_coleta": 66.39, "icms": 243.08, "total_pagar": 2025.66, "peso": 195.0,
            "contratante": {"cnpj": "99999999003959"}},
           {"fornecedor": "BETA", "cnpj": "22222222000941", "frete": 90.35, "pedagio": 2.94,
            "taxa_coleta": 3.61, "icms": 13.21, "total_pagar": 110.11, "peso": 10.6,
            "contratante": {"cnpj": "99999999003959"}},
       ]}


def _cte(numero, remetente, destinatario, total, frete, pedagio, taxa, icms, peso, **kw):
    """Um CT-e com o ICMS SÓ no componente 100 — o cabeçalho zerado é o real."""
    k = {"filial": 1, "serie": 2, "numero": numero, "dtemissao": datetime(2026, 9, 16, 1, 8),
         "dtcancelamento": None, "situacaocte": 3, "chave": "4126" + str(numero),
         "remetente": remetente, "destinatario": destinatario,
         "remetente_nome": "R", "destinatario_nome": "D",
         "tomador": "99999999003959", "pagador": "99999999003959",
         "peso": peso, "m3": 0, "total": total, "base_icms": 0, "icms_pct": 0, "icms": 0,
         "filial_cnpj": "76104397000123", "frete": frete, "pedagio": pedagio,
         "taxa_coleta": taxa, "icms_comp": icms, "outros": 0}
    k.update(kw)
    return k


def _ctes_iguais():
    # ALFA como DESTINATÁRIO, BETA como REMETENTE: o par se acha pelos dois lados
    return [_cte(55606, "99999999003959", "11111111000111", 2025.66, 1662.13, 54.06, 66.39, 243.08, 195.0),
            _cte(55605, "22222222000941", "99999999003959", 110.11, 90.35, 2.94, 3.61, 13.21, 10.6)]


def _conferir(ctes, doc=DOC, anexos=(ANEXO,)):
    return V.conferir_coleta(COLETA, list(anexos), {900: doc}, ctes)


def test_tudo_igual_e_conferido_e_o_par_sai_pelos_dois_lados_do_cte():
    r = _conferir(_ctes_iguais())
    assert r["estado"] == "ok", [i for i in r["itens"] if not i["ok"]]
    assert [p["cte"]["numero"] for p in r["pares"]] == [55606, 55605]


def test_icms_vem_do_componente_e_a_aliquota_e_derivada():
    """O cabeçalho do CT-e (`valoricms`, `percaliquotaicms`) vem ZERADO nestes
    CT-es; lido dali, 100% das coletas divergiriam no ICMS."""
    r = _conferir(_ctes_iguais())
    icms = [i for i in r["itens"] if i["rotulo"] in ("ICMS", "% ICMS")]
    assert icms and all(i["ok"] for i in icms), icms


def test_centavos_sao_arredondamento_e_reais_sao_divergencia():
    ctes = _ctes_iguais()
    ctes[0]["frete"] = 1662.41                     # +0,28: o caso real mais comum
    ctes[0]["total"] = 2025.94
    r = _conferir(ctes)
    assert r["estado"] == "arredondamento" and not r["falhas"], r["falhas"]

    ctes[0]["frete"] = 1700.00                     # +37,87
    ctes[0]["total"] = 2063.53
    r = _conferir(ctes)
    assert r["estado"] == "divergente" and r["falhas"]["valores"] == 2


def test_pagina_sem_cte_e_cte_sem_pagina():
    ctes = _ctes_iguais()[:1] + [_cte(55699, "44444444000100", "99999999003959",
                                      50.0, 40.0, 0, 0, 6.0, 5.0)]
    r = _conferir(ctes)
    assert r["estado"] == "divergente"
    rot = [i["rotulo"] for i in r["itens"] if i["grupo"] == "ctes"]
    assert "CT-e de BETA" in rot and "CT-e 55699 sem página no arquivo" in rot


def test_peso_diferente_diverge_e_tolera_um_por_cento():
    ctes = _ctes_iguais()
    ctes[0]["peso"] = 196.5                        # +0,77%
    assert _conferir(ctes)["estado"] == "ok"
    ctes[0]["peso"] = 250.0
    assert _conferir(ctes)["falhas"] == {"peso": 1}


def test_partes_contratante_e_filial_emissora():
    ctes = _ctes_iguais()
    ctes[1]["filial_cnpj"] = "76104397000204"
    ctes[1]["tomador"] = ctes[1]["pagador"] = "55555555000100"
    assert _conferir(ctes)["falhas"] == {"partes": 2}


def test_estados_sem_arquivo_nao_lido_sem_cte_e_sem_valor():
    assert _conferir(_ctes_iguais(), anexos=())["estado"] == "sem_arquivo"
    assert _conferir(_ctes_iguais(), doc={"formato": "desconhecido",
                                          "motivo": "requisição de transporte expresso"})["estado"] == "nao_lido"
    assert _conferir([])["estado"] == "sem_cte"
    zerado = {**DOC, "sem_valor": True}
    r = _conferir(_ctes_iguais(), doc=zerado)
    assert r["estado"] == "sem_valor"
    assert not [i for i in r["itens"] if i["grupo"] == "valores"]


def test_cte_cancelado_nao_entra_na_conferencia():
    ctes = _ctes_iguais() + [_cte(55600, "99999999003959", "11111111000111", 1.0, 1.0, 0, 0, 0, 195.0,
                                  dtcancelamento=datetime(2026, 9, 15))]
    r = _conferir(ctes)
    assert r["estado"] == "ok" and r["ctes"] == 2 and r["ctes_cancelados"] == 1


def test_ordem_de_coleta_confere_o_peso_total():
    ordem = {"formato": "ordem_coleta", "peso_coleta": 205.6, "peso_entrega": 205.6}
    assert _conferir(_ctes_iguais(), doc=ordem)["estado"] == "ok"
    ordem["peso_coleta"] = 400.0
    assert _conferir(_ctes_iguais(), doc=ordem)["falhas"] == {"peso": 1}


def test_o_precalculo_mais_recente_responde():
    velho = {**ANEXO, "id": 899, "dtinc": datetime(2026, 9, 13)}
    doc_velho = {**DOC, "fornecedores": [{**DOC["fornecedores"][0], "total_pagar": 1.0}]}
    r = V.conferir_coleta(COLETA, [velho, ANEXO], {899: doc_velho, 900: DOC}, _ctes_iguais())
    assert r["documento"]["anexo_id"] == 900 and r["estado"] == "ok"


def test_snapshot_do_copiloto_nao_baixa_pdf(monkeypatch, tmp_path):
    """Leitura barata: o que não está lido em disco é CONTADO, não baixado."""
    monkeypatch.setattr(V, "DIR_CACHE", tmp_path)
    chamadas = []

    def falso_query(sql, params=None):
        chamadas.append(sql)
        if "conteudoarquivo" in sql:
            raise AssertionError("o snapshot tentou baixar o PDF do ERP")
        if "arquivobinario b" in sql and "JOIN arquivo" in sql:
            return [{"filial": 1, "serie": 124, "numero": 20006, **ANEXO}]
        if "conhecimento_composicao" in sql:
            return []
        return [dict(COLETA, grupo=1, empresa=1, unidade=1, diferenciadornumero=1,
                     remetente="99999999003959", pagador="99999999003959",
                     tomador="99999999003959")]
    monkeypatch.setattr(V.db, "query", falso_query)
    r = V.resumo_copiloto()
    assert r["anexos_ainda_nao_lidos"] == 1
    assert r["contagem"]["nao_lido"] == 1
    assert "coletas" in r and isinstance(r["coletas"], int)   # só contagem, sem lista


def test_sql_sem_porcento_solto():
    """`%` fora de placeholder vira erro do psycopg só na hora da consulta."""
    import re
    for nome in ("COLETAS_SQL", "ANEXOS_SQL", "CTES_SQL", "BYTES_SQL"):
        sql = getattr(V, nome)
        assert not re.search(r"%(?!\(\w+\)s|s)", sql), nome


@pytest.mark.parametrize("rota", ["/api/operacao/whirlpool/validacao",
                                  "/api/operacao/whirlpool/anexo/123"])
def test_rotas_sao_da_tela_whrval(rota):
    telas = next(t for pref, t in auth.ROTA_TELAS if rota.startswith(pref))
    assert telas == frozenset({"whrval"})
    assert "whrval" in auth.TELAS
