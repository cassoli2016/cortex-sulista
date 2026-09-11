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


# ── O DIA: quem bateu, a que horas e onde ───────────────────────────────────
#
# A aba existe porque o ERP nao responde isto: o AFD entra por importacao
# MANUAL, com mediana de 3 dias de atraso, e "quem bateu hoje" simplesmente
# nao existe la. O que estes guards seguram e o TRATAMENTO DO LUGAR, que tem
# tres respostas e cuja mais comum e uma ausencia — misturar as duas primeiras
# com a terceira foi o defeito que derrubou o ponto por aplicativo em jan/2025.

def _batida_em(cur, id_, situacao, quando, dist=None, cerca=None,
               mat="003792", local=None, relogio="00003.19001.000001"):
    """Insere numa hora EXATA do dia, em vez de "N dias atras".

    A aba corta por DIA LOCAL (`current_date`), e um deslocamento em dias a
    partir de `now()` atravessa a meia-noite dependendo da hora em que a suite
    roda — o teste passaria de manha e falharia a noite.
    """
    cur.execute(
        """INSERT INTO pc_marcacao (id, nsr, matricula, marcada_em, inserida_em,
                                    latencia_s, situacao, distancia_m,
                                    cerca_proxima, local, relogio)
                VALUES (%s, %s, %s, %s, %s, 12, %s, %s, %s, %s, %s)""",
        (id_, 800000 + id_, mat, quando, quando, situacao, dist, cerca,
         local, relogio))


HOJE_8H = "current_date + interval '8 hours'"
HOJE_12H = "current_date + interval '12 hours'"
ONTEM_8H = "current_date - interval '16 hours'"


def _semear_dia(esq, linhas):
    with pglocal.get_conn(esq) as conn, conn.cursor() as cur:
        for kw in linhas:
            quando = kw.pop("quando")
            # O cursor da casa devolve DICIONARIO, nao tupla: `fetchone()[0]`
            # levanta KeyError, que aponta para o teste e nao para a causa.
            cur.execute("SELECT " + quando + " AS q")
            kw["quando"] = cur.fetchone()["q"]
            _batida_em(cur, **kw)


def test_o_dia_agrupa_por_PESSOA_e_nao_por_batida(esq):
    """Quem le a tela procura uma PESSOA, nao uma linha de log. Quatro batidas
    de duas pessoas sao duas linhas, com a primeira e a ultima hora."""
    _semear_dia(esq, [
        dict(id_=1, situacao="dentro", quando=HOJE_8H, local="PIRAQUARA",
             dist=13, cerca="PIRAQUARA", mat="003792"),
        dict(id_=2, situacao="dentro", quando=HOJE_12H, local="PIRAQUARA",
             dist=20, cerca="PIRAQUARA", mat="003792"),
        dict(id_=3, situacao="dentro", quando=HOJE_8H, local="AUDI",
             dist=88, cerca="AUDI", mat="003812"),
    ])
    d = painel.do_dia("hoje")
    assert d["kpis"]["pessoas"] == 2 and d["kpis"]["batidas"] == 3
    p = {x["matricula"]: x for x in d["pessoas"]}["003792"]
    assert p["n"] == 2 and p["primeira"] == "08:00" and p["ultima"] == "12:00"
    assert [b["hora"] for b in p["batidas"]] == ["08:00", "12:00"]


def test_dentro_da_cerca_tem_NOME_de_lugar(esq):
    _semear_dia(esq, [dict(id_=10, situacao="dentro", quando=HOJE_8H,
                           local="PIRAQUARA", dist=13, cerca="PIRAQUARA")])
    assert painel.do_dia("hoje")["pessoas"][0]["batidas"][0]["lugar"] == "PIRAQUARA"


def test_fora_da_cerca_vira_DISTANCIA_e_nao_um_nome(esq):
    """Fora nao tem lugar: o que se sabe e a distancia ate a cerca mais
    proxima. E a unidade muda com a ordem de grandeza, porque "11266 m" e
    "667 m" pedem leituras diferentes — a primeira e outro municipio, a
    segunda e a mesma quadra."""
    _semear_dia(esq, [
        dict(id_=20, situacao="fora", quando=HOJE_8H, dist=11266,
             cerca="SBC ADMINSTRATIVO", local="FORA DE CERCA", mat="003792"),
        dict(id_=21, situacao="fora", quando=HOJE_8H, dist=667,
             cerca="AUDI", local="FORA DE CERCA", mat="003812"),
    ])
    lug = {x["matricula"]: x["batidas"][0]["lugar"]
           for x in painel.do_dia("hoje")["pessoas"]}
    # virgula, nao ponto: o rotulo vai para uma tela em portugues
    assert lug["003792"] == "11,3 km de SBC ADMINSTRATIVO"
    assert lug["003812"] == "667 m de AUDI"


def test_sem_GPS_NUNCA_e_apresentado_como_fora(esq):
    """O fornecedor manda `local` = 'FORA DE CERCA' tambem quando nao houve
    coordenada nenhuma. Repetir esse rotulo transformaria metade das batidas
    em infracao — foi esse erro que fez o ponto por aplicativo ser desligado
    em jan/2025."""
    _semear_dia(esq, [dict(id_=30, situacao="sem_coordenada", quando=HOJE_8H,
                           local="FORA DE CERCA", dist=None, cerca=None)])
    d = painel.do_dia("hoje")
    assert d["pessoas"][0]["batidas"][0]["lugar"] == "sem GPS"
    assert d["kpis"]["fora"] == 0 and d["kpis"]["sem_coordenada"] == 1
    assert [l["local"] for l in d["locais"]] == ["sem GPS"]


def test_o_fora_agrupa_pela_cerca_mais_proxima_e_nao_num_balde(esq):
    """Dez pessoas batendo todo dia a 1,9 km da MESMA unidade nao sao dez
    infracoes: e uma cerca que ninguem cadastrou. Num balde unico chamado
    "fora de cerca" isso e invisivel."""
    _semear_dia(esq, [
        dict(id_=40, situacao="fora", quando=HOJE_8H, dist=1890,
             cerca="SBC OPERACIONAL", mat="003792"),
        dict(id_=41, situacao="fora", quando=HOJE_8H, dist=1900,
             cerca="SBC OPERACIONAL", mat="003812"),
        dict(id_=42, situacao="fora", quando=HOJE_8H, dist=100982,
             cerca="MAXION CRZ", mat="003813"),
    ])
    loc = {l["local"]: l for l in painel.do_dia("hoje")["locais"]}
    assert "longe de SBC OPERACIONAL" in loc and "longe de MAXION CRZ" in loc
    assert loc["longe de SBC OPERACIONAL"]["pessoas"] == 2
    # a mediana e o que separa cerca apertada de local sem cerca
    assert loc["longe de SBC OPERACIONAL"]["distancia_m"] == 1900
    assert loc["longe de MAXION CRZ"]["distancia_m"] == 100982


def test_ontem_e_ontem_e_hoje_e_hoje(esq):
    """O corte e por DIA LOCAL. Se ele escorregar, a tela do RH mostra o dia
    errado sem erro nenhum."""
    _semear_dia(esq, [
        dict(id_=50, situacao="dentro", quando=HOJE_8H, local="PIRAQUARA",
             dist=10, cerca="PIRAQUARA", mat="003792"),
        dict(id_=51, situacao="dentro", quando=ONTEM_8H, local="AUDI",
             dist=20, cerca="AUDI", mat="003812"),
    ])
    assert painel.do_dia("hoje")["kpis"]["batidas"] == 1
    assert painel.do_dia("hoje")["pessoas"][0]["matricula"] == "003792"
    assert painel.do_dia("ontem")["kpis"]["batidas"] == 1
    assert painel.do_dia("ontem")["pessoas"][0]["matricula"] == "003812"


def test_o_dia_de_HOJE_se_declara_em_curso(esq):
    """As 8h da manha quem entra as 13h ainda nao bateu. Sem esta marca, a
    contagem de hoje se le como o dia inteiro — e "so 57 de 90 bateram" vira
    acusacao contra quem esta no horario."""
    _semear_dia(esq, [dict(id_=60, situacao="dentro", quando=HOJE_8H,
                           local="PIRAQUARA", dist=10, cerca="PIRAQUARA")])
    assert painel.do_dia("hoje")["em_curso"] is True
    assert painel.do_dia("ontem")["em_curso"] is False


def test_o_relogio_compartilhado_se_declara(esq):
    """Das 59 series vistas em 90 dias, 57 sao de UMA pessoa (aplicativo no
    aparelho dela) e uma e usada por 42 pessoas de todas as filiais, sempre
    sem GPS. Quem le uma batida sem GPS precisa saber de qual das duas ela
    veio — a tela nao afirma o que o relogio E, mas diz quantas pessoas o
    usam, que e o que da para provar."""
    _semear_dia(esq, [
        dict(id_=70, situacao="sem_coordenada", quando=HOJE_8H,
             relogio="00000.31900.997904", mat="003792"),
        dict(id_=71, situacao="sem_coordenada", quando=HOJE_12H,
             relogio="00000.31900.997904", mat="003812"),
        dict(id_=72, situacao="dentro", quando=HOJE_8H, local="PIRAQUARA",
             dist=10, cerca="PIRAQUARA", relogio="00003.19001.000009",
             mat="003813"),
    ])
    por_mat = {x["matricula"]: x for x in painel.do_dia("hoje")["pessoas"]}
    assert por_mat["003792"]["batidas"][0]["relogio_pessoas"] == 2
    assert por_mat["003813"]["batidas"][0]["relogio_pessoas"] == 1


def test_dia_invalido_NAO_chega_ao_SQL():
    """`dia` vem da barra de endereco. A data entra numa clausula com
    parametro, mas `hoje`/`ontem` viram SQL literal — entao o que nao for uma
    das tres formas conhecidas cai em `hoje`, e nao no meio da consulta."""
    assert painel._dia_pedido("2026-09-10") == "2026-09-10"
    assert painel._dia_pedido("HOJE") == "hoje"
    assert painel._dia_pedido("ontem") == "ontem"
    for lixo in ["'; DROP TABLE pc_marcacao; --", "2026-9-1", "", None,
                 "current_date", "10/09/2026"]:
        assert painel._dia_pedido(lixo) == "hoje", lixo


def test_o_dia_no_snapshot_do_copiloto_e_so_NUMERO(esq, monkeypatch):
    """O snapshot vai para modelo EXTERNO quando o Ollama local nao responde.
    E isso que obriga cada valor a ser escalar: sem nome, sem chapa, sem
    filial. O guard roda contra o banco de teste CHEIO — com o banco vazio ele
    passaria por vacuidade, aprovando qualquer vazamento futuro.
    """
    from api import frequencia
    _semear_dia(esq, [
        dict(id_=80, situacao="dentro", quando=HOJE_8H, local="PIRAQUARA",
             dist=10, cerca="PIRAQUARA", mat="003792"),
        dict(id_=81, situacao="fora", quando=HOJE_12H, dist=11266,
             cerca="SBC ADMINSTRATIVO", mat="003812"),
    ])
    # o modulo do painel ja aponta para o schema de teste pela fixture; o que
    # falta e o ERP, que aqui nao existe — e nome ausente nao pode derrubar
    monkeypatch.setattr(painel, "_nomes", lambda: {})

    r = frequencia._escalares_do_dia()
    assert r["hoje_pessoas_que_bateram"] == 2 and r["hoje_batidas"] == 2
    assert r["hoje_batidas_fora_de_cerca"] == 1
    assert all(not isinstance(v, (list, dict)) for v in r.values()), r
    bruto = " ".join(str(v) for v in r.values()).upper()
    for proibido in ("003792", "003812", "PIRAQUARA", "SBC"):
        assert proibido not in bruto, f"{proibido} vazou para o snapshot"
