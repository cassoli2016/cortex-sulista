"""O payload das ordens de compra, com dublê de cursor que responde por SQL.

Dublê com a ORDEM DE GRANDEZA do real: dezenas de OCs, fila de poucas horas,
um fornecedor com 51 ordens para exercitar o corte de 50, suspensa com data
de aprovação gravada sem usuário (649 casos reais), aprovador sem alçada.
"""
from __future__ import annotations

import pytest

from api import suprimentos_oc as oc


def _linha(**kw):
    base = {"numero": 1, "filial": 1, "tipo": 3, "emissao": "2026-08-20", "aprovada_em": "2026-08-20",
            "suspensa_em": None, "prazo": None, "aprovado": 1, "suspensa": False, "encaminhada": True,
            "sem_data_aprovacao": False, "prazo_informado": False, "prazo_vencido": False,
            "dias_aberta": 5, "horas_aprovacao": 3.0, "fornecedor": "FORN A", "codigo_forn": "111",
            "criador_cod": 10, "aprovador_cod": 23, "aprovador2_cod": None, "direcionado_cod": None,
            "tem_nf": True, "valor": 1000.0, "valor_pendente": 0.0}
    base.update(kw)
    return base


USUARIOS = [{"codigo": 10, "nome": "CRIADOR UM", "ativo": True},
            {"codigo": 23, "nome": "APROVADOR VINTE E TRES", "ativo": True},
            {"codigo": 518, "nome": "APROVADOR INATIVO", "ativo": False},
            {"codigo": 66, "nome": "SEGUNDO APROVADOR", "ativo": True}]
ALCADAS = [{"cod": 23, "valormaximo": 2000000.0}, {"cod": 6, "valormaximo": 22000.0}]
TS = [{"ts": __import__("datetime").datetime(2026, 9, 1, 10, 0)}]


class _Cur:
    def __init__(self, respostas):
        self.r, self._atual, self.executados = respostas, [], []

    def execute(self, sql, params=None):
        self.executados.append((sql, params))
        if "current_timestamp AS ts" in sql:
            self._atual = TS
            return
        for chave, valor in self.r.items():
            if sql == chave:
                self._atual = valor
                return
        self._atual = []

    def fetchall(self):
        return list(self._atual)

    def fetchone(self):
        return self._atual[0] if self._atual else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, respostas):
        self.cur = _Cur(respostas)

    def cursor(self):
        return self.cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def dublar(monkeypatch):
    conns = []

    def _fazer(respostas):
        respostas = {oc.OC_USUARIOS_SQL: USUARIOS, oc.OC_ALCADAS_SQL: ALCADAS, **respostas}
        c = _Conn(respostas)
        conns.append(c)
        monkeypatch.setattr(oc.db, "get_conn", lambda: c)
        # cadastros são cacheados por uma hora: cada teste começa vazio
        oc._CADASTROS.update(ts=0.0, usuarios={}, alcadas={})
        return c
    return _fazer


LINHAS = [
    _linha(numero=1, valor=500.0),                                                    # recebida
    _linha(numero=2, tem_nf=True, valor=1000.0, valor_pendente=300.0),                 # recebida parcial
    _linha(numero=3, aprovado=2, encaminhada=True, aprovador_cod=None, horas_aprovacao=None,
           tem_nf=False, valor_pendente=200.0, valor=200.0),                            # fila
    _linha(numero=4, aprovado=2, encaminhada=False, aprovador_cod=None, horas_aprovacao=None,
           tem_nf=False, valor_pendente=150.0, valor=150.0),                            # rascunho
    _linha(numero=5, tem_nf=False, dias_aberta=40, valor=700.0, valor_pendente=700.0),  # atrasada (dias)
    _linha(numero=6, tem_nf=False, prazo_informado=True, prazo_vencido=True, prazo="2026-08-25",
           dias_aberta=8, valor=90.0, valor_pendente=90.0),                             # atrasada (prazo)
    _linha(numero=7, tem_nf=False, dias_aberta=2, valor=60.0, valor_pendente=60.0),     # aguardando
    _linha(numero=8, aprovado=2, suspensa=True, suspensa_em="2026-08-28", encaminhada=False,
           aprovador_cod=None, horas_aprovacao=None, tem_nf=False, valor=400.0, valor_pendente=400.0),  # suspensa
    _linha(numero=9, aprovado=3, suspensa=True, encaminhada=True, aprovador_cod=None,
           horas_aprovacao=None, tem_nf=False, valor=45.0, valor_pendente=45.0),         # reprovada
    _linha(numero=10, sem_data_aprovacao=True, aprovada_em=None, horas_aprovacao=None,
           valor=80.0),                                                                 # legada
    _linha(numero=11, valor=2500000.0, aprovador_cod=23, aprovador2_cod=None, horas_aprovacao=30.0),  # acima da alçada
    _linha(numero=12, valor=2500000.0, aprovador_cod=23, aprovador2_cod=66, horas_aprovacao=1.0),     # acima, com 2º
    _linha(numero=13, aprovador_cod=518, horas_aprovacao=48.0, valor=10.0),             # aprovador inativo, sem alçada
] + [_linha(numero=100 + i, codigo_forn="222", fornecedor="FORN B", valor=1.0, criador_cod=11)
     for i in range(51)]                                                                # 51 OCs: 1 oculta

MENSAL = [{"mes": "2026-08", "ocs": 3, "valor": 100.0}]


def _payload(dublar, **filtros):
    dublar({oc.OC_ROWS_SQL: LINHAS, oc.OC_MENSAL_SQL: MENSAL})
    return oc.get_ordens_compra(None, "2026-06-03", "2026-09-01", **filtros)


def test_kpis_separam_os_estados(dublar):
    k = _payload(dublar)["kpis"]
    assert k["ocs"] == 13 + 51
    assert k["fila"] == 1 and k["fila_valor"] == 200.0
    assert k["rascunhos"] == 1 and k["rascunhos_valor"] == 150.0
    assert k["aguardando"] == 3 and k["atrasadas"] == 2       # atrasada é subconjunto de aguardando
    assert k["aguardando_valor"] == pytest.approx(700 + 90 + 60)
    assert k["atrasadas_valor"] == pytest.approx(700 + 90)
    assert k["suspensas"] == 1 and k["reprovadas"] == 1
    assert k["recebidas"] == 13 + 51 - 1 - 1 - 3 - 1 - 1        # o resto
    assert k["parciais"] == 1
    assert k["cadastro_sem_data"] == 1 and k["cadastro_sem_data_valor"] == 80.0
    assert k["acima_alcada"] == 1 and k["acima_alcada_valor"] == 2500000.0
    assert k["com_segundo_aprovador"] == 1


def test_tempo_de_aprovacao_e_mediana_sem_suspensas(dublar):
    t = _payload(dublar)["tempo_aprovacao"]
    # 3.0 ×(2 recebidas + 5 + 6 + 7 + 51) … a mediana fica em 3 h; suspensa e
    # reprovada (horas None) ficam fora; a de 48 h e a de 30 h puxam o máximo
    assert t["n"] > 50 and t["mediana_h"] == 3.0 and t["max_h"] == 48.0
    assert 3.0 <= t["p90_h"] <= 48.0


def test_aprovadores_trazem_alcada_e_o_inativo(dublar):
    por = {a["cod"]: a for a in _payload(dublar)["por_aprovador"]}
    a23 = por[23]
    assert a23["alcada"] == 2000000.0 and a23["acima_alcada"] == 1 and a23["com_segundo"] == 1
    assert a23["nome"].startswith("APROVADOR") and a23["ativo"] is True
    a518 = por[518]
    assert a518["ativo"] is False
    assert a518["alcada"] is None and a518["acima_alcada"] is None   # sem alçada: n/d, nunca zero
    assert None not in por                                            # suspensa/reprovada/fila fora


def test_fornecedores_top_com_universo_e_corte_de_50(dublar):
    d = _payload(dublar)
    assert d["fornecedores_total"] == 2
    b = next(f for f in d["fornecedores"] if f["fornecedor"] == "FORN B")
    assert b["ocs"] == 51 and len(b["ordens"]) == 50 and b["ocultas"] == 1
    a = next(f for f in d["fornecedores"] if f["fornecedor"] == "FORN A")
    assert a["atrasadas"] == 2 and a["em_aprovacao"] == 2 and a["suspensas"] == 2
    assert a["valor_pendente"] == pytest.approx(700 + 90 + 60)
    assert a["doc"] == "11•" or "•" in a["doc"]
    ordens = {o["numero"]: o for o in a["ordens"]}
    assert ordens[8]["status"] == "suspensa" and ordens[8]["suspensa_em"] == "2026-08-28"
    assert ordens[8]["aprovador"] is None                             # a suspensão não é aprovação
    assert ordens[2]["parcial"] and ordens[2]["valor_pendente"] == 300.0
    assert ordens[1]["valor_pendente"] == 0.0
    assert ordens[11]["acima_alcada"] and not ordens[12]["acima_alcada"]
    assert ordens[12]["aprovador2"] == "SEGUNDO APROVADOR"


def test_filtro_de_status_nao_esvazia_as_facetas(dublar):
    d = _payload(dublar, status="atrasada")
    assert d["kpis"]["ocs"] == 2
    # a faceta de criadores ignora o próprio filtro? Não: ignora só o SEU
    # campo. Criador 11 (FORN B) não tem OC atrasada, então some daqui…
    assert {c["codigo"] for c in d["criadores"]} == {10}
    # …mas o filtro de criador não esvazia a lista de criadores
    d2 = _payload(dublar, criador=11)
    assert {c["codigo"] for c in d2["criadores"]} == {10, 11}
    assert d2["kpis"]["ocs"] == 51


def test_filtro_de_fornecedor_por_nome(dublar):
    d = _payload(dublar, fornecedor="forn b")
    assert d["kpis"]["ocs"] == 51 and d["fornecedores_total"] == 1


def test_serializa_e_cita_a_fonte(dublar):
    import json
    d = _payload(dublar)
    json.dumps(d)
    assert "ordemcompra" in d["fonte"] and d["dias_parada"] == 30
    assert d["atualizado_em"].startswith("2026-09-01T10:00")


# ----------------------------------------------------------- em aberto
KPI_ABERTA = [{"ocs": 104, "valor": 173592.5, "paradas": 6, "paradas_valor": 36911.0,
               "prazo_vencido": 2, "prazo_vencido_valor": 698.4, "prazo_informado": 82,
               "cita_nf": 9, "cita_nf_valor": 56695.2, "suspensas": 3740, "suspensas_valor": 17300000.0,
               "mais_antiga": "2025-06-10"}]
FAIXAS = [{"faixa": "1_ate_7", "ocs": 95, "valor": 135405.0, "prazo_vencido": 0},
          {"faixa": "5_mais_180", "ocs": 2, "valor": 1243.0, "prazo_vencido": 0}]
LISTA = [{"numero": 2699, "filial": 20, "tipo": 3, "dias": 448, "emissao": "2025-06-10",
          "aprovada_em": "2025-06-10", "prazo": None, "prazo_vencido": False, "cita_nf": True,
          "valor": 994.4, "observacao": "NF 123", "fornecedor": "FORN A"},
         {"numero": 30, "filial": 1, "tipo": 6, "dias": 31, "emissao": "2026-07-30",
          "aprovada_em": "2026-08-01", "prazo": None, "prazo_vencido": False, "cita_nf": False,
          "valor": 10.0, "observacao": "", "fornecedor": "FORN B"},
         {"numero": 31, "filial": 1, "tipo": 6, "dias": 3, "emissao": "2026-08-29",
          "aprovada_em": "2026-08-29", "prazo": "2026-08-30", "prazo_vencido": True, "cita_nf": False,
          "valor": 10.0, "observacao": "", "fornecedor": "FORN B"},
         {"numero": 32, "filial": 1, "tipo": 6, "dias": 1, "emissao": "2026-08-31",
          "aprovada_em": "2026-08-31", "prazo": None, "prazo_vencido": False, "cita_nf": False,
          "valor": 10.0, "observacao": "", "fornecedor": "FORN B"}]
FORN = [{"fornecedor": "FORN A", "ocs": 1, "pendente": 994.4, "dias_max": 448},
        {"fornecedor": "FORN B", "ocs": 1, "pendente": 10.0, "dias_max": 31}]
FILA = [{"numero": 25714, "filial": 1, "tipo": 6, "emissao": "2026-08-31", "encaminhada": True,
         "encaminhada_em": "2026-08-31 11:24", "horas": 36, "criador_cod": 10, "direcionado_cod": None,
         "valor": 85.0, "fornecedor": "FORN A"},
        {"numero": 25715, "filial": 1, "tipo": 6, "emissao": "2026-09-01", "encaminhada": True,
         "encaminhada_em": "2026-09-01 08:00", "horas": 2, "criador_cod": 10, "direcionado_cod": 518,
         "valor": 15.0, "fornecedor": "FORN A"},
        {"numero": 7, "filial": 2, "tipo": 3, "emissao": "2023-06-03", "encaminhada": False,
         "encaminhada_em": None, "horas": 28473, "criador_cod": 10, "direcionado_cod": None,
         "valor": 123.0, "fornecedor": "FORN B"}]


def _pendentes(dublar):
    dublar({oc.OC_ABERTA_KPI_SQL: KPI_ABERTA, oc.OC_ABERTA_FAIXA_SQL: FAIXAS,
            oc.OC_ABERTA_LISTA_SQL: LISTA, oc.OC_ABERTA_FORN_SQL: FORN, oc.OC_FILA_SQL: FILA})
    return oc.get_oc_pendentes()


def test_em_aberto_gradua_a_acao_e_conta_o_universo(dublar):
    d = _pendentes(dublar)
    sn = d["sem_nota"]
    assert [r["acao"] for r in sn["lista"]] == ["suspender", "validar", "validar", "cobrar"]
    assert sn["lista_total"] == 104 and sn["fornecedores_total"] == 2
    assert sn["kpis"]["suspensas"] == 3740
    assert d["dias_min"] == 30 and "não segue os filtros" in d["fonte"]


def test_fila_separa_encaminhada_de_rascunho_e_ve_o_inativo(dublar):
    f = _pendentes(dublar)["fila"]
    k = f["kpis"]
    assert k["fila"] == 2 and k["fila_valor"] == 100.0 and k["fila_horas_max"] == 36
    assert k["fila_direcionado_inativo"] == 1
    assert k["rascunhos"] == 1 and k["rascunho_mais_antigo"] == "2023-06-03"
    itens = {i["numero"]: i for i in f["itens"]}
    assert itens[25715]["direcionado"] == "APROVADOR INATIVO" and itens[25715]["direcionado_ativo"] is False
    assert itens[25714]["direcionado"] is None and itens[25714]["direcionado_ativo"] is None
    assert itens[7]["situacao"] == "rascunho" and itens[25714]["situacao"] == "fila"
    assert itens[7]["criador"] == "CRIADOR UM"


def test_dias_min_chega_ao_sql(dublar):
    c = dublar({oc.OC_ABERTA_KPI_SQL: KPI_ABERTA, oc.OC_ABERTA_FAIXA_SQL: FAIXAS,
                oc.OC_ABERTA_LISTA_SQL: LISTA, oc.OC_ABERTA_FORN_SQL: FORN, oc.OC_FILA_SQL: FILA})
    oc.get_oc_pendentes(dias_min=90)
    params = [p for s, p in c.cur.executados if s == oc.OC_ABERTA_KPI_SQL]
    assert params == [{"dias_min": 90}]


# ----------------------------------------------------------- copiloto
def test_snapshot_so_leva_escalares(monkeypatch, dublar):
    from api import queries
    monkeypatch.setattr(queries, "get_oc_pendentes", lambda: _pendentes(dublar))
    monkeypatch.setattr(queries, "get_ordens_compra", lambda *a, **k: _payload(dublar))
    s = oc.snapshot_copiloto()

    def _so_escalar(x, caminho="$"):
        if isinstance(x, dict):
            for k, v in x.items():
                _so_escalar(v, f"{caminho}.{k}")
        else:
            assert not isinstance(x, (list, tuple)), caminho
            assert not (isinstance(x, str) and "FORN" in x), caminho   # nome de fornecedor não sai
    _so_escalar(s)
    assert s["fila_aprovacao"] == 2 and s["sem_nota_paradas"] == 6 and s["mes"]["fila"] == 1
    assert s["tempo_aprovacao_mes"]["mediana_h"] == 3.0
