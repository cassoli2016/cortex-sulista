# -*- coding: utf-8 -*-
"""A coleta: idempotente, com cursor que não anda à toa, e SEM o trajeto.

O que estes testes cobram é uma decisão de projeto, não um detalhe: a
coordenada entra, vira distância e NÃO é gravada. A cerca precisa saber se a
batida caiu na unidade; não precisa saber por onde a pessoa andou.
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.pontocertificado import cliente, coleta

# duas cercas reais (a de SBC é círculo de 25 m; MAXION é vértice de polígono)
_CERCAS = [
    {"id_local": 702112, "id_cerca": 8758, "nome": "FILIAL SBC",
     "descricao": "FILIAL SBC ", "endereco": "FILIAL SBC - TRANSPORTADORA SULISTA",
     "forma": "circulo", "raio_m": 25.0, "lat": -23.723233921852056,
     "lon": -46.60542011260986, "ativa": True, "local_ativo": True},
    {"id_local": 702102, "id_cerca": 8756, "nome": "MAXION CRZ",
     "descricao": "SULISTA CRZ / MAXION", "endereco": "SULISTA CRZ / MAXION",
     "forma": "poligono", "raio_m": 0.0, "lat": -22.58274709463008,
     "lon": -44.95861401799927, "ativa": True, "local_ativo": True},
]

# marcações já normalizadas pelo cliente (o corpo cru está no test_cliente)
def _m(id_, sit, lat=None, lon=None, mat="003792"):
    return {"id": id_, "nsr": 277700 + id_ % 100, "matricula": mat,
            "marcada_em": "2026-09-09T20:42:05-03:00",
            "inserida_em": "2026-09-09T20:42:17-03:00", "latencia_s": 12,
            "atividade": None, "relogio": "00003.19001.113481", "situacao": sit,
            "local": None if sit != cliente.DENTRO else "FILIAL SBC",
            "local_descricao": "FORA DE CERCA" if sit != cliente.DENTRO else "FILIAL SBC",
            "id_local": 0 if sit != cliente.DENTRO else 8758,
            "lat": lat, "lon": lon}


@pytest.fixture
def esq(esquema_pg, monkeypatch):
    monkeypatch.setattr(coleta, "ESQUEMA", esquema_pg)
    return esquema_pg


# ── a decisão que este módulo carrega ───────────────────────────────────────
def test_a_coordenada_ENTRA_e_NAO_e_gravada(esq, monkeypatch):
    """O trajeto não fica. A tabela não tem sequer coluna para ele."""
    colunas = {c["column_name"] for c in pglocal.query(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'pc_marcacao'""",
        (esq,), esquema=esq)}
    assert "distancia_m" in colunas
    for proibida in ("lat", "lon", "latitude", "longitude", "gps", "cpf", "pis"):
        assert proibida not in colunas, \
            f"pc_marcacao nao pode ter a coluna '{proibida}'"


def test_a_distancia_substitui_a_coordenada(esq, monkeypatch):
    """Batida a ~90 m da cerca de SBC: grava 90, não o ponto."""
    monkeypatch.setattr(coleta, "cercas_do_espelho", lambda: _CERCAS)
    n = coleta._gravar([_m(1, cliente.FORA, -23.72404, -46.60542)], _CERCAS)
    assert n == 1
    r = pglocal.um("SELECT * FROM pc_marcacao WHERE id = 1", esquema=esq)
    assert r["cerca_proxima"] == "FILIAL SBC"
    assert 80 <= r["distancia_m"] <= 100
    assert r["situacao"] == "fora"


def test_sem_coordenada_a_distancia_e_NULA_e_nao_zero(esq):
    """NULL é "não sei". Zero seria "em cima da cerca" — o oposto do que é."""
    coleta._gravar([_m(2, cliente.SEM_COORDENADA)], _CERCAS)
    r = pglocal.um("SELECT * FROM pc_marcacao WHERE id = 2", esquema=esq)
    assert r["distancia_m"] is None
    assert r["situacao"] == "sem_coordenada"


# ── idempotência ────────────────────────────────────────────────────────────
def test_gravar_duas_vezes_nao_duplica(esq):
    """A coleta reexecuta depois de queda: `id` do fornecedor é a chave."""
    lote = [_m(10, cliente.DENTRO, -23.72323, -46.60542), _m(11, cliente.FORA, -23.9, -46.9)]
    coleta._gravar(lote, _CERCAS)
    coleta._gravar(lote, _CERCAS)
    assert pglocal.um("SELECT COUNT(*) n FROM pc_marcacao", esquema=esq)["n"] == 2


def test_reprocessar_corrige_a_situacao(esq):
    """Se a cerca mudar e a marcação for relida, o veredito se atualiza."""
    coleta._gravar([_m(12, cliente.SEM_COORDENADA)], _CERCAS)
    coleta._gravar([_m(12, cliente.DENTRO, -23.72323, -46.60542)], _CERCAS)
    r = pglocal.um("SELECT * FROM pc_marcacao WHERE id = 12", esquema=esq)
    assert r["situacao"] == "dentro"


# ── o cursor ────────────────────────────────────────────────────────────────
def test_o_cursor_nunca_grava_zero(esq):
    """`ultIdImportado=0` devolve VAZIO no fornecedor: um cursor em zero nunca
    anda, e a coleta fica parada sem erro nenhum. O banco recusa."""
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        coleta._mover_cursor(0, 0)


def test_semear_nao_roda_duas_vezes(esq, monkeypatch):
    monkeypatch.setattr(cliente, "cercas", lambda **k: _CERCAS)
    monkeypatch.setattr(cliente, "marcacoes_por_periodo",
                        lambda *a, **k: [_m(100, cliente.DENTRO, -23.72323, -46.60542)])
    monkeypatch.setattr(coleta, "sincronizar_cercas", lambda: {"lidas": 2, "gravadas": 2})
    p = coleta.semear("01/09/2026", "09/09/2026")
    assert p["semeado"] is True and p["ultimo_id"] == 100
    de_novo = coleta.semear("01/09/2026", "09/09/2026")
    assert de_novo["semeado"] is False


def test_coletar_sem_cursor_nao_inventa_ponto_de_partida(esq):
    r = coleta.coletar()
    assert r["ok"] is False and "semear" in r["motivo"]


def test_coletar_pagina_por_pagina_ate_a_fila_secar(esq, monkeypatch):
    """Página CHEIA significa que há mais: parar nela perde o resto em silêncio.

    `PAGINA` vira 2 aqui para o teste exercitar o laço sem fabricar mil linhas —
    o que se prova é a REGRA (cheia => pede de novo), não o número.
    """
    monkeypatch.setattr(coleta, "cercas_do_espelho", lambda: _CERCAS)
    monkeypatch.setattr(cliente, "PAGINA", 2)
    coleta._mover_cursor(1000, 0)
    paginas = [
        [_m(1001, cliente.DENTRO, -23.72323, -46.60542),
         _m(1002, cliente.FORA, -23.9, -46.9)],          # CHEIA (2 de 2)
        [_m(3000, cliente.FORA, -23.9, -46.9)],          # parcial: fim da fila
    ]
    chamadas = []

    def falso(ultimo, **k):
        chamadas.append(ultimo)
        return paginas.pop(0) if paginas else []

    monkeypatch.setattr(cliente, "marcacoes_desde", falso)
    r = coleta.coletar()
    assert r["ok"] is True
    assert r["marcacoes"] == 3
    assert len(chamadas) == 2, "parou na primeira pagina cheia e perdeu o resto"
    assert chamadas[1] > chamadas[0], "a segunda pagina foi pedida do id novo"


def test_pagina_PARCIAL_encerra_a_coleta(esq, monkeypatch):
    """O espelho da regra acima: página não cheia é fim de fila, e pedir de
    novo seria uma chamada inútil por ciclo, para sempre."""
    monkeypatch.setattr(coleta, "cercas_do_espelho", lambda: _CERCAS)
    monkeypatch.setattr(cliente, "PAGINA", 2)
    coleta._mover_cursor(2000, 0)
    chamadas = []

    def falso(ultimo, **k):
        chamadas.append(ultimo)
        return [_m(2001, cliente.DENTRO, -23.72323, -46.60542)]   # 1 de 2

    monkeypatch.setattr(cliente, "marcacoes_desde", falso)
    coleta.coletar()
    assert len(chamadas) == 1


def test_falha_no_meio_NAO_avanca_o_cursor_alem_do_gravado(esq, monkeypatch):
    """O cursor é de mão única: avançar sem ter gravado perde o intervalo.

    A primeira página vem CHEIA (para o laço continuar) e a segunda explode.
    """
    monkeypatch.setattr(coleta, "cercas_do_espelho", lambda: _CERCAS)
    monkeypatch.setattr(cliente, "PAGINA", 2)
    coleta._mover_cursor(5000, 0)
    lotes = [[_m(5001, cliente.DENTRO, -23.72323, -46.60542),
              _m(5002, cliente.FORA, -23.9, -46.9)]]

    def falso(ultimo, **k):
        if lotes:
            return lotes.pop(0)
        raise cliente.PontoCertificadoIndisponivel("SelecionaMarcacoes: HTTP 500")

    monkeypatch.setattr(cliente, "marcacoes_desde", falso)
    r = coleta.coletar()
    assert r["ok"] is False and r["marcacoes"] == 2
    c = coleta.cursor()
    assert int(c["ultimo_id"]) == 5002, "o cursor tem de parar no ultimo GRAVADO"
    assert c["ultimo_erro"] and "PontoCertificadoIndisponivel" in c["ultimo_erro"]


# ── cercas ──────────────────────────────────────────────────────────────────
def test_resposta_vazia_do_fornecedor_nao_apaga_o_espelho(esq, monkeypatch):
    """Coleta vazia NUNCA vira snapshot completo — a casa ficaria sem cerca."""
    monkeypatch.setattr(cliente, "cercas", lambda **k: _CERCAS)
    coleta.sincronizar_cercas()
    monkeypatch.setattr(cliente, "cercas", lambda **k: [])
    r = coleta.sincronizar_cercas()
    assert r["gravadas"] == 0
    assert len(coleta.cercas_do_espelho()) == 2, "o espelho foi apagado"


def test_o_poligono_sobrevive_ao_espelho(esq, monkeypatch):
    monkeypatch.setattr(cliente, "cercas", lambda **k: _CERCAS)
    coleta.sincronizar_cercas()
    formas = {c["nome"]: c["forma"] for c in coleta.cercas_do_espelho()}
    assert formas["MAXION CRZ"] == "poligono"
    assert formas["FILIAL SBC"] == "circulo"


# ── estado ──────────────────────────────────────────────────────────────────
def test_estado_nunca_levanta_sem_tabela(monkeypatch):
    """Ele alimenta a Saúde numa instalação onde a migration ainda não rodou."""
    monkeypatch.setattr(coleta, "ESQUEMA", "teste_inexistente_zzz")
    d = coleta.estado()
    assert d["cursor"] is None and d["por_situacao"] == {}
