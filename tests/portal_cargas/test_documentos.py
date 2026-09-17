# -*- coding: utf-8 -*-
"""Documentos e Peso das cargas do cliente (`api/portal_cargas/documentos.py`).

O que cada teste segura:

- o ESCOPO: toda consulta leva a raiz e o filtro da Minha Operacao, e o
  download refaz o caminho carga -> documento a partir da CHAVE, sem confiar na
  lista que a tela montou. Chave fora das cargas vira 404 (nao 403);
- a CONTA: peso da carga e dos KPIs so com CT-e valido (o cancelado e
  reemitido dobraria o peso), canhoto "anexado" so quando TODOS os CT-e vivos
  o tem;
- o que NAO SE FABRICA: CT-e sem XML guardado recusa com o motivo, em vez de
  sair um arquivo montado a partir do protocolo.

Nenhum teste vai ao ERP: `db.query` entra por substituicao, e as rotas sao
chamadas direto (sem TestClient, que dispara o startup e aplica migration no
schema padrao).
"""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from api import portal_cliente
from api.portal_cargas import documentos as d

RAIZ = "11222333"
OUTRA = "44555666"
CH_CTE = "3" * 44
CH_NFE = "4" * 44


def _cte(coleta, numero, *, cancelado=False, peso=1000.0, xml=True, canhoto=None, chave=None):
    return {"coleta": coleta, "coleta_chave": f"1|1|1|1|0|1|{coleta}",
            "coleta_emissao": "2026-09-10", "origem": "JOINVILLE", "uf_origem": "SC",
            "destino": "SAO PAULO", "uf_destino": "SP", "destinatario": "DEST",
            "ref_cliente": "", "cte_numero": numero, "cte_serie": 1,
            "cte_id": f"cte{numero}", "cte_emissao": "2026-09-10 10:00",
            "cte_chave": chave or CH_CTE, "cte_protocolo": 135000,
            "cte_cancelado": cancelado, "cte_peso": peso, "cte_tem_xml": xml,
            "canhoto_em": canhoto}


def _nota(cte_id, numero, peso=500.0, xml=True):
    return {"cte_id": cte_id, "numero": numero, "chave": CH_NFE, "peso": peso, "tem_xml": xml}


# ------------------------------------------------------------------ a conta
def test_peso_so_soma_CTe_valido_e_o_cancelado_nao_dobra_a_carga():
    """Carga cujo CT-e foi cancelado e reemitido: o peso e o do reemitido."""
    linhas = [_cte(10, 1, cancelado=True, peso=23710.0),
              _cte(10, 2, peso=23710.0, canhoto="2026-09-12 08:00")]
    r = d.montar(linhas, [_nota("cte2", 7, 23710.0)])
    carga = r["cargas"][0]
    assert carga["peso_kg"] == 23710.0
    assert r["kpis"]["peso_kg"] == 23710.0 and r["kpis"]["ctes"] == 1
    assert carga["notas"] == 1 and carga["canhoto"] is True


def test_canhoto_da_carga_so_e_ANEXADO_quando_todo_CTe_vivo_tem():
    linhas = [_cte(11, 1, canhoto="2026-09-12 08:00"), _cte(11, 2, canhoto=None)]
    assert d.montar(linhas, [])["cargas"][0]["canhoto"] is False


def test_coleta_sem_CTe_aparece_e_conta_a_parte():
    """A carga programada ainda nao faturou: ela existe, sem documento — sumir
    com ela diria ao cliente que a carga nao existe."""
    linha = {**_cte(12, None), "cte_numero": None}
    r = d.montar([linha], [])
    assert r["cargas"][0]["ctes"] == [] and r["cargas"][0]["canhoto"] is None
    assert r["kpis"]["sem_cte"] == 1 and r["kpis"]["cargas"] == 1


def test_o_payload_e_lista_EXPLICITA_e_nao_copia_da_linha_do_ERP():
    """Coluna nova no ERP nao pode virar campo na tela de um cliente sem
    ninguem decidir."""
    linha = {**_cte(13, 1), "cpf_motorista": "00000000000", "valorfrete": 999.0}
    r = d.montar([linha], [])
    texto = json.dumps(r)
    assert "cpf_motorista" not in texto and "valorfrete" not in texto


def test_indicadores_de_cobertura_do_XML():
    linhas = [_cte(14, 1, xml=True), _cte(15, 2, xml=False)]
    notas = [_nota("cte1", 1, xml=True), _nota("cte2", 2, xml=False)]
    k = d.montar(linhas, notas)["kpis"]
    assert (k["ctes"], k["ctes_com_xml"], k["notas"], k["notas_com_xml"]) == (2, 1, 2, 1)


# ------------------------------------------------------------------ o periodo
def test_periodo_padrao_e_o_ultimo_mes():
    assert d.periodo(None, None, hoje=date(2026, 9, 17)) == ("2026-08-19", "2026-09-17")


def test_periodo_acima_do_teto_e_cortado_a_partir_do_ate():
    de, ate = d.periodo("2026-01-01", "2026-09-17", hoje=date(2026, 9, 17))
    assert ate == "2026-09-17"
    assert (date.fromisoformat(ate) - date.fromisoformat(de)).days + 1 == d.JANELA_MAX_D


def test_periodo_invertido_e_data_ilegivel_nao_derrubam():
    assert d.periodo("2026-09-10", "2026-09-01", hoje=date(2026, 9, 17)) == ("2026-09-01", "2026-09-10")
    assert d.periodo("lixo", "", hoje=date(2026, 9, 17)) == ("2026-08-19", "2026-09-17")


# ------------------------------------------------------------------ o escopo
def test_toda_consulta_leva_o_FILTRO_da_Minha_Operacao():
    """Uma regra de "quem ve o que" so. Se alguem escrever outro filtro aqui,
    as duas telas do portal passam a discordar sobre de quem e a carga."""
    for nome in ("CARGAS_SQL", "NOTAS_SQL", "AUTORIZA_CTE_SQL", "AUTORIZA_NFE_SQL"):
        assert portal_cliente.FILTRO_CLIENTE in getattr(d, nome), nome


def test_chave_invalida_e_recusada_ANTES_de_ir_ao_ERP(monkeypatch):
    chamadas = []
    monkeypatch.setattr(d.db, "query", lambda *a, **k: chamadas.append(a) or [])
    for ruim in ("", "123", "x" * 44, "1" * 43, "1' OR '1'='1"):
        with pytest.raises(d.ForaDoEscopo):
            d.autorizar(RAIZ, ruim)
    assert chamadas == []


def test_chave_de_OUTRO_cliente_e_recusada(monkeypatch):
    """O banco de duble so conhece a chave para a RAIZ dona dela."""
    def query(sql, p):
        if p.get("raiz") != RAIZ:
            return []
        if sql is d.AUTORIZA_CTE_SQL and p["chave"] == CH_CTE:
            return [{"?column?": 1}]
        return []
    monkeypatch.setattr(d.db, "query", query)
    assert d.autorizar(RAIZ, CH_CTE) == "cte"
    with pytest.raises(d.ForaDoEscopo):
        d.autorizar(OUTRA, CH_CTE)


def test_o_tipo_vem_da_AUTORIZACAO_e_nota_nao_sai_como_CTe(monkeypatch):
    def query(sql, p):
        if sql is d.AUTORIZA_NFE_SQL:
            return [{"?column?": 1}]
        if sql is d.XML_SQL:
            return [{"tipodocumento": 6, "conteudoxml": "<nfeProc/>"}]
        return []
    monkeypatch.setattr(d.db, "query", query)
    assert d.xml_autorizado(RAIZ, CH_NFE)[0] == "nfe"


def test_CTe_sem_XML_guardado_RECUSA_com_o_motivo(monkeypatch):
    def query(sql, p):
        if sql is d.AUTORIZA_CTE_SQL:
            return [{"?column?": 1}]
        return []            # XML_SQL: nada guardado
    monkeypatch.setattr(d.db, "query", query)
    with pytest.raises(d.SemArquivo, match="SEFAZ"):
        d.xml_autorizado(RAIZ, CH_CTE)


# ------------------------------------------------------------------ as rotas
def _req(raiz=None):
    return SimpleNamespace(state=SimpleNamespace(sessao={"cliente_cnpj_raiz": raiz}))


def test_rota_de_download_404_para_chave_fora_e_409_para_sem_arquivo(monkeypatch):
    from api import main as m

    def fora(raiz, chave):
        raise d.ForaDoEscopo("x")
    monkeypatch.setattr(d, "xml_autorizado", fora)
    r = m.portal_cargas_documento(_req(RAIZ), chave=CH_CTE, formato="xml")
    assert r.status_code == 404
    assert "suas cargas" in json.loads(r.body)["mensagem"]

    def sem(raiz, chave):
        raise d.SemArquivo("O CT-e está autorizado, mas o arquivo XML dele não está guardado")
    monkeypatch.setattr(d, "xml_autorizado", sem)
    r = m.portal_cargas_documento(_req(RAIZ), chave=CH_CTE, formato="pdf")
    assert r.status_code == m.HTTP_RECUSA
    assert "não está guardado" in json.loads(r.body)["mensagem"]


def test_rota_de_download_entrega_o_XML_como_ANEXO(monkeypatch):
    from api import main as m
    monkeypatch.setattr(d, "xml_autorizado", lambda raiz, chave: ("nfe", "<nfeProc>x</nfeProc>"))
    r = m.portal_cargas_documento(_req(RAIZ), chave=CH_NFE, formato="xml")
    assert r.status_code == 200 and r.body == b"<nfeProc>x</nfeProc>"
    assert r.headers["content-disposition"] == f'attachment; filename="NFe-{CH_NFE}.xml"'


def test_cliente_VINCULADO_nao_escapa_do_CNPJ_dele_pelo_parametro(monkeypatch):
    """O `raiz` da URL existe para gente da casa; para quem tem vinculo, a
    rota ignora — a mesma trava da Minha Operacao."""
    from api import main as m
    vistas = []
    monkeypatch.setattr(d, "xml_autorizado",
                        lambda raiz, chave: vistas.append(raiz) or ("nfe", "<x/>"))
    m.portal_cargas_documento(_req(RAIZ), chave=CH_NFE, formato="xml", raiz=OUTRA)
    assert vistas == [RAIZ]


def test_gente_da_casa_sem_cliente_escolhido_nao_baixa_nada(monkeypatch):
    from api import main as m
    monkeypatch.setattr(d, "xml_autorizado",
                        lambda *a: pytest.fail("baixou sem cliente escolhido"))
    r = m.portal_cargas_documento(_req(None), chave=CH_NFE, formato="xml")
    assert r.status_code == m.HTTP_RECUSA


def test_lista_para_gente_da_casa_sem_escolha_devolve_os_clientes(monkeypatch):
    from api import main as m
    monkeypatch.setattr(portal_cliente, "get_clientes",
                        lambda dias: {"clientes": [{"raiz": RAIZ, "nome": "X", "cargas": 3}]})
    monkeypatch.setattr(d, "get_documentos", lambda *a: pytest.fail("consultou sem cliente"))
    r = m.portal_cargas_documentos(_req(None))
    corpo = json.loads(r.body)
    assert r.status_code == 200 and corpo["escolher"] is True and corpo["clientes"]


def test_a_rota_do_portal_de_cargas_e_da_tela_pcdoc_e_so_dela():
    from api import auth
    assert auth.TELAS["pcdoc"][1] == "Portal de Cargas"
    assert auth.TELAS["cliop"][1] == "Portal de Cargas"
    mapeadas = [telas for pref, telas in auth.ROTA_TELAS if pref == "/api/portal/cargas"]
    assert mapeadas == [frozenset({"pcdoc"})]
