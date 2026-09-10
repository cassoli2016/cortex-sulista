# -*- coding: utf-8 -*-
"""O que a aba Cercas e batidas afirma — e o que ela se recusa a afirmar.

O TESTE CENTRAL DAQUI É SOBRE UM ERRO QUE EU COMETI
===================================================
A primeira versão da calibração tomava o p95 de TODAS as batidas atribuídas a
uma cerca — inclusive as que caíram a 12 km e só tinham aquela como a mais
próxima — e chamava aquilo de "dispersão real". Dava p95 de 12.285 m para uma
cerca de 200 m, e o veredito "apertado" saía para todas, sempre.

O número parecia certo: vinha de um percentil sobre dado real. Mas média de
quem está dentro com quem está a 12 km não descreve nenhum dos dois.

`test_reprovada_LONGE_nao_acusa_raio_apertado` é o guard dessa lição.
"""
from __future__ import annotations

import pytest

from api import pglocal, queries
from api.pontocertificado import painel

_CERCAS = [
    ("FILIAL SBC", 8758, 702112, "circulo", 25.0, True),
    ("MAXION CRZ", 8756, 702102, "poligono", 0.0, True),
    ("DESLIGADA", 8736, 702067, "circulo", 40.0, False),
]


def _cerca(cur, nome, id_cerca, id_local, forma, raio, ativa):
    cur.execute(
        """INSERT INTO pc_cerca (id_local, id_cerca, nome, forma, raio_m, lat, lon,
                                 ativa, local_ativo)
                VALUES (%s,%s,%s,%s,%s,-23.72,-46.60,%s,true)""",
        (id_local, id_cerca, nome, forma, raio, ativa))


def _batida(cur, id_, situacao, dist=None, cerca=None, mat="003792", dias=1):
    cur.execute(
        """INSERT INTO pc_marcacao (id, nsr, matricula, marcada_em, inserida_em,
                                    latencia_s, situacao, distancia_m, cerca_proxima)
                VALUES (%s, %s, %s, now() - make_interval(days => %s),
                        now() - make_interval(days => %s), 12, %s, %s, %s)""",
        (id_, 900000 + id_, mat, dias, dias, situacao, dist, cerca))


@pytest.fixture
def esq(esquema_pg, monkeypatch):
    monkeypatch.setattr(painel, "ESQUEMA", esquema_pg)
    queries._RESP_CACHE.clear()
    with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
        for c in _CERCAS:
            _cerca(cur, *c)
    yield esquema_pg
    queries._RESP_CACHE.clear()


def _semear(esq, linhas):
    with pglocal.get_conn(esq) as conn, conn.cursor() as cur:
        for l in linhas:
            _batida(cur, *l)


# ── a lição do erro ─────────────────────────────────────────────────────────
def test_reprovada_LONGE_nao_acusa_raio_apertado(esq):
    """Quinze batidas reprovadas a 2 km de uma cerca de 25 m NÃO tornam o raio
    apertado: aumentar o raio para 2 km não é a resposta para ninguém.

    Foi exatamente isto que a primeira versão errava, e o veredito saía
    "apertado" para todas as cercas da casa.
    """
    _semear(esq, [(i, "fora", 2000, "FILIAL SBC") for i in range(1, 16)])
    c = {x["nome"]: x for x in painel.calibracao()}["FILIAL SBC"]
    assert c["veredito"] == "ok"
    assert c["ate250"] == 0 and c["longe"] == 15
    assert "não é raio" in c["motivo"]


def test_reprovada_PERTO_acusa_raio_apertado(esq):
    """O outro lado: reprovada a 60 m de um raio de 25 m é problema de raio."""
    _semear(esq, [(20, "fora", 60, "FILIAL SBC"), (21, "fora", 90, "FILIAL SBC")])
    c = {x["nome"]: x for x in painel.calibracao()}["FILIAL SBC"]
    assert c["veredito"] == "apertado"
    assert c["ate250"] == 2 and c["mais_perto"] == 60
    assert "60 m" in c["motivo"]


def test_poligono_nao_recebe_veredito_de_raio(esq):
    """Área desenhada por vértices não tem raio, e a distância ali é medida até
    o vértice — não até a borda. Dizer "raio 0 m, apertado" seria um número
    errado com cara de certo."""
    _semear(esq, [(30, "fora", 80, "MAXION CRZ")])
    c = {x["nome"]: x for x in painel.calibracao()}["MAXION CRZ"]
    assert c["veredito"] == "n/d"
    assert c["raio_m"] is None
    assert "vértice" in c["motivo"]


def test_cerca_sem_batida_nao_recebe_veredito(esq):
    """Silêncio não é aprovação: sem batida atribuída, não há o que medir."""
    c = {x["nome"]: x for x in painel.calibracao()}["DESLIGADA"]
    assert c["veredito"] == "n/d" and "sem batida" in c["motivo"]


def test_a_cerca_desligada_aparece_como_desligada(esq):
    assert {x["nome"]: x for x in painel.calibracao()}["DESLIGADA"]["ativa"] is False


# ── os KPIs ─────────────────────────────────────────────────────────────────
def test_sem_coordenada_e_contado_separado_de_fora(esq):
    """São 51% das batidas: somá-las a "fora" dobraria a infração inventada."""
    _semear(esq, [(40, "dentro", 10, "FILIAL SBC"), (41, "fora", 900, "FILIAL SBC"),
                  (42, "sem_coordenada"), (43, "sem_coordenada")])
    k = painel.resumo()["kpis"]
    assert k["dentro"] == 1 and k["fora"] == 1 and k["sem_coordenada"] == 2
    assert k["pct_sem_coordenada"] == 50.0
    assert k["pct_fora"] == 25.0


def test_a_serie_marca_o_dia_de_HOJE(esq):
    """Uma coluna baixa às 9h não é queda de movimento — é dia em curso."""
    _semear(esq, [(50, "dentro", 10, "FILIAL SBC", "003792", 0),
                  (51, "dentro", 10, "FILIAL SBC", "003792", 3)])
    serie = painel.resumo()["serie"]
    assert serie[-1]["parcial"] is True
    assert all(x["parcial"] is False for x in serie[:-1])


def test_a_latencia_e_MEDIANA_e_nao_media(esq):
    """Lançamento retroativo (uma batida inserida 4 dias depois) puxa a média
    para 46 minutos e descreve mal as outras 874, que chegam em segundos."""
    with pglocal.get_conn(esq) as conn, conn.cursor() as cur:
        for i, lat in enumerate([10, 11, 12, 13, 345355], start=60):
            cur.execute(
                """INSERT INTO pc_marcacao (id, nsr, matricula, marcada_em,
                                            inserida_em, latencia_s, situacao)
                        VALUES (%s,%s,'003792', now() - interval '1 day',
                                now() - interval '1 day', %s, 'dentro')""",
                (i, 900000 + i, lat))
    assert painel.resumo()["kpis"]["latencia_s"] == 12


# ── por pessoa ──────────────────────────────────────────────────────────────
def test_por_pessoa_so_lista_quem_bateu_fora(esq):
    _semear(esq, [(70, "dentro", 10, "FILIAL SBC", "111"),
                  (71, "fora", 900, "FILIAL SBC", "222"),
                  (72, "sem_coordenada", None, None, "333")])
    m = {x["matricula"] for x in painel.por_pessoa()}
    assert m == {"222"}


def test_por_pessoa_ordena_por_FORA_e_nao_por_total(esq):
    """Quem tem 3 de 3 fora importa mais que quem tem 2 de 50."""
    _semear(esq, [(80, "fora", 900, "FILIAL SBC", "AAA"),
                  (81, "fora", 900, "FILIAL SBC", "AAA"),
                  (82, "fora", 900, "FILIAL SBC", "AAA"),
                  (83, "fora", 900, "FILIAL SBC", "BBB"),
                  (84, "fora", 900, "FILIAL SBC", "BBB")]
                 + [(90 + i, "dentro", 10, "FILIAL SBC", "BBB") for i in range(48)])
    p = painel.por_pessoa()
    assert p[0]["matricula"] == "AAA" and p[0]["pct_fora"] == 100.0


# ── ausência de tabela ──────────────────────────────────────────────────────
def test_sem_a_migration_a_tela_nao_explode(monkeypatch):
    """A tela abre numa instalação onde a coleta ainda não foi aplicada."""
    monkeypatch.setattr(painel, "ESQUEMA", "teste_inexistente_zzz")
    queries._RESP_CACHE.clear()
    d = painel.resumo()
    assert d["kpis"]["batidas"] == 0
    assert painel.calibracao() == [] and painel.por_pessoa() == []
