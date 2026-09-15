# -*- coding: utf-8 -*-
"""A tratativa da cobrança: histórico só de acréscimo, situação calculada contra
hoje, a chave do grupo que não sai do servidor, e as rotas com sessão de
verdade.

Nomes e valores são de mentira — o repositório é público.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import auth, pglocal, queries
from api.financeiro import cobranca_tratativa as ct
# a Régua de dublê com os tipos do ERP (GRUPO FICTICIO = grupo 7, e o avulso)
from tests.financeiro.test_inadimplencia_regra_bi import AVULSO, ava  # noqa: F401

HOJE = date(2026, 9, 15)
REF = "0123456789abcdef"
LINHA = {"cliente": "GRUPO FICTICIO", "vencido": 500.0, "titulos": ["101/1", "102/1", "103/1"]}


@pytest.fixture
def esq(esquema_pg, monkeypatch):
    monkeypatch.setattr(ct, "ESQUEMA", esquema_pg)
    return esquema_pg


def _reg(dados, *, hoje=HOJE, ref=REF, linha=LINHA, autor="ana@sulista.com.br"):
    return ct.registrar(ref, dados, autor=autor, linha=linha, hoje=hoje)


# ════════════════════════════════════════════════════ gravar e ler ═════

def test_registra_e_le_do_mais_novo_para_o_mais_antigo(esq):
    a = _reg({"tipo": "contato", "canal": "ligacao", "descricao": "Falei com o financeiro."})
    b = _reg({"tipo": "promessa", "descricao": "Prometeu pagar as duas.",
              "promessa_data": "2026-09-20", "promessa_valor": 200,
              "titulos": ["102/1", "101/1"]})
    h = ct.historico(REF)
    assert [e["id"] for e in h] == [b["id"], a["id"]]
    assert h[0]["tipo_rotulo"] == "Promessa de pagamento"
    assert h[0]["titulos"] == ["101/1", "102/1"]
    assert (h[0]["promessa_data"], h[0]["promessa_valor"]) == ("2026-09-20", 200.0)
    assert (h[1]["vencido_ref"], h[1]["titulos_ref"]) == (500.0, 3), "a foto do ERP no registro"
    assert h[1]["canal_rotulo"] == "Ligação"
    assert h[1]["autor_nome"] == "ana", "sem cadastro de usuário, o nome sai do e-mail"
    assert "ana@sulista.com.br" not in json.dumps(h), "o e-mail fica no banco e na trilha"


def test_o_historico_e_IMUTAVEL_no_proprio_banco(esq):
    """Registro errado se corrige com registro novo: o gatilho recusa UPDATE e
    DELETE venha de onde vier — regra só no Python a próxima rota esquece."""
    e = _reg({"tipo": "contato", "descricao": "Primeiro contato."})
    for sql in ("UPDATE cob_tratativa SET descricao = 'reescrito' WHERE id = %s",
                "DELETE FROM cob_tratativa WHERE id = %s"):
        with pytest.raises(psycopg.errors.RaiseException, match="imutável"):
            with pglocal.get_conn(esq) as conn, conn.cursor() as cur:
                cur.execute(sql, (e["id"],))
    assert [x["descricao"] for x in ct.historico(REF)] == ["Primeiro contato."]


@pytest.mark.parametrize("dados, trecho", [
    ({"tipo": "xyz", "descricao": "a"}, "Escolha o que"),
    ({"tipo": "contato", "descricao": "   "}, "Descreva"),
    ({"tipo": "contato", "descricao": "x" * 2001}, "2000"),
    ({"tipo": "contato", "canal": "pombo", "descricao": "a"}, "Canal"),
    ({"tipo": "promessa", "descricao": "a"}, "precisa da data prometida"),
    ({"tipo": "contato", "descricao": "a", "promessa_data": "2026-09-20"}, "só valem"),
    ({"tipo": "promessa", "descricao": "a", "promessa_data": "2026-08-01"}, "dias atrás"),
    ({"tipo": "promessa", "descricao": "a", "promessa_data": "2026-09-20",
      "promessa_valor": -5}, "maior que zero"),
    ({"tipo": "promessa", "descricao": "a", "promessa_data": "2026-09-20",
      "promessa_valor": "1.234,56"}, "número"),
    ({"tipo": "promessa", "descricao": "a", "promessa_data": "20/09/2026"}, "não é uma data"),
    ({"tipo": "contato", "descricao": "a", "retorno_em": "2026-09-14"}, "retorno"),
    ({"tipo": "contato", "descricao": "a", "titulos": ["999/1"]}, "não está em aberto"),
    ({"tipo": "contato", "descricao": "a", "titulos": "101/1"}, "títulos"),
])
def test_recusa_legivel_dizendo_o_que_falta(dados, trecho):
    with pytest.raises(ct.Recusa, match=trecho):
        ct.validar(dados, titulos_do_grupo=LINHA["titulos"], hoje=HOJE)


def test_promessa_registrada_depois_de_feita_e_aceita_e_ja_nasce_vencida():
    limpo = ct.validar({"tipo": "promessa", "descricao": "Prometeu ontem, para ontem.",
                        "promessa_data": "2026-09-14"}, titulos_do_grupo=[], hoje=HOJE)
    assert limpo["promessa_data"] == date(2026, 9, 14)


# ═══════════════════════════════════════════════ a situação, calculada ═══

def _ult(tipo="contato", em="2026-09-15T10:00:00-03:00", p=None, r=None):
    return {"tipo": tipo, "em": em, "promessa_data": p, "retorno_em": r}


@pytest.mark.parametrize("ultima, estado", [
    (None, "sem_tratativa"),
    (_ult("promessa", p="2026-09-14"), "promessa_vencida"),
    (_ult("promessa", p="2026-09-15"), "promessa"),          # vence HOJE: ainda não venceu
    (_ult("contato", r="2026-09-14"), "retorno_atrasado"),
    (_ult("contato", em="2026-09-01T10:00:00-03:00"), "parada"),
    (_ult("contato", em="2026-09-08T10:00:00-03:00"), "em_andamento"),   # 7 dias: ainda não
    (_ult("contato", em="2026-09-01T10:00:00-03:00", r="2026-09-20"), "em_andamento"),
    (_ult("juridico", em="2026-07-01T10:00:00-03:00"), "em_andamento"),  # anda em meses
])
def test_a_situacao_e_CALCULADA_contra_hoje(ultima, estado):
    assert ct.situacao(ultima, hoje=HOJE)["estado"] == estado


def test_anexar_escreve_numa_COPIA_e_conta_por_situacao(esq):
    ref_a, ref_b = queries.cobranca_ref("g7"), queries.cobranca_ref("c" + AVULSO)
    ct.registrar(ref_a, {"tipo": "promessa", "descricao": "Paga sexta.",
                         "promessa_data": "2026-09-14"},
                 autor="x@sulista.com.br", linha=LINHA, hoje=date(2026, 9, 10))
    cache = {"clientes": [{"cliente": "A", "ref": ref_a, "vencido": 700.0},
                          {"cliente": "B", "ref": ref_b, "vencido": 460.0}],
             "total_vencido_top": 1160.0}
    foto = json.dumps(cache, sort_keys=True)
    d = ct.anexar(cache, hoje=HOJE)
    assert json.dumps(cache, sort_keys=True) == foto, \
        "o dicionário é o do cache de get_cobranca e não pode ganhar a tratativa"
    a, b = d["clientes"]
    assert (a["tratativa"]["estado"], a["tratativa"]["total"]) == ("promessa_vencida", 1)
    assert a["tratativa"]["vencido_novo"] == 200.0, "o vencido cresceu desde o registro"
    assert b["tratativa"]["estado"] == "sem_tratativa" and b["tratativa"]["ultima"] is None
    t = d["tratativas"]
    assert t["disponivel"] and t["contagem"] == {"sem_tratativa": 1, "promessa_vencida": 1,
                                                 "retorno_atrasado": 0, "parada": 0}
    assert t["valor"]["sem_tratativa"] == 460.0 and t["valor"]["promessa_vencida"] == 700.0
    assert t["tipos"] == ct.TIPOS
    assert AVULSO not in json.dumps(d)


def test_sem_o_banco_da_casa_a_regua_segue_e_DIZ(monkeypatch):
    def quebra(*a, **k):
        raise psycopg.OperationalError("fora do ar")
    monkeypatch.setattr(ct, "ultimas", quebra)
    d = ct.anexar({"clientes": [{"cliente": "A", "ref": REF, "vencido": 1.0}]}, hoje=HOJE)
    assert d["tratativas"]["disponivel"] is False
    assert d["clientes"][0]["tratativa"] is None, \
        "None, nunca 'sem tratativa': ninguém conferiu"


def test_cliente_sem_ref_fica_SEM_resposta_e_fora_das_contagens(monkeypatch):
    """Sem identificação não há como saber se há tratativa: None — "sem
    tratativa" afirmaria que alguém conferiu."""
    monkeypatch.setattr(ct, "ultimas", lambda refs, esquema=None: {})
    d = ct.anexar({"clientes": [{"cliente": "A", "ref": None, "vencido": 9.0}]}, hoje=HOJE)
    assert d["clientes"][0]["tratativa"] is None
    assert d["tratativas"]["contagem"]["sem_tratativa"] == 0


def test_para_hoje_na_ORDEM_da_urgencia_e_so_o_que_pede_acao():
    def cli(nome, vencido, ultima):
        return {"cliente": nome, "vencido": vencido,
                "tratativa": ct._montar(ultima, vencido, HOJE)}
    clientes = [
        cli("retorno atrasado", 900.0, _ult("contato", r="2026-09-12")),
        cli("promessa futura", 800.0, _ult("promessa", p="2026-09-20")),
        cli("retorno hoje", 700.0, _ult("contato", r="2026-09-15")),
        cli("promessa vencida", 600.0, _ult("promessa", p="2026-09-14")),
        cli("promessa hoje pequena", 100.0, _ult("promessa", p="2026-09-15")),
        cli("promessa hoje grande", 500.0, _ult("promessa", p="2026-09-15")),
        cli("sem tratativa", 5000.0, None),
        {"cliente": "sem leitura", "vencido": 1.0, "tratativa": None},
    ]
    r = ct.para_hoje(clientes, hoje=HOJE)
    assert [x["cliente"] for x in r] == ["promessa hoje grande", "promessa hoje pequena",
                                         "promessa vencida", "retorno hoje", "retorno atrasado"]
    assert [x["motivo"] for x in r] == ["promessa_hoje", "promessa_hoje", "promessa_vencida",
                                        "retorno_hoje", "retorno_atrasado"]


# ════════════════════════════════════════ o ref e a Régua viva do ERP ═══

def test_o_ref_e_opaco_estavel_e_confere_com_a_regua_viva(ava, esq):
    r = queries.get_cobranca(None)
    refs = {c["cliente"]: c["ref"] for c in r["clientes"]}
    assert refs["GRUPO FICTICIO"] == queries.cobranca_ref("g7")
    assert refs["INDUSTRIA DE MENTIRA SA"] == queries.cobranca_ref("c" + AVULSO)
    assert all(ct.ref_valido(x) for x in refs.values())
    assert AVULSO not in json.dumps(r, default=str)
    linha = ct.linha_da_regua(refs["INDUSTRIA DE MENTIRA SA"])
    assert linha["vencido"] == pytest.approx(460.0) and len(linha["titulos"]) == 6
    assert ct.linha_da_regua("f" * 16) is None, "quem não deve mais não recebe tratativa"


# ═══════════════════════════════════════════════ as rotas, com sessão ═══

SENHA = "senha-de-teste-123"
URL = "/api/financeiro/cobranca/tratativas"


@pytest.fixture
def cliente(esq, monkeypatch):
    from api.main import app
    monkeypatch.setattr(auth, "ESQUEMA", esq)
    monkeypatch.setattr(ct, "linha_da_regua", lambda ref: dict(LINHA) if ref == REF else None)
    auth.init_db()
    with auth._conn() as c:
        perfil = c.execute(
            "SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()
        c.execute(
            """INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                    deve_trocar_senha, criado_em)
               VALUES('Ana Cobrança','ana@sulista.com.br',%s,%s,1,0,%s)""",
            (auth._ph.hash(SENHA), perfil["id"], auth._agora()))
    cli = TestClient(app)
    r = cli.post("/api/auth/login", json={"email": "ana@sulista.com.br", "senha": SENHA})
    assert r.status_code == 200, r.text
    return cli


def test_a_rota_esta_na_tela_da_regua():
    """Fora de `ROTA_TELAS` o middleware (fail-closed) daria 403 a quem tem a
    tela — e o defeito só apareceria para um usuário não-admin."""
    assert [t for p, t in auth.ROTA_TELAS if URL.startswith(p)][0] == frozenset({"cob"})


def test_sem_sessao_e_401():
    from api.main import app
    c = TestClient(app)
    assert c.get(URL, params={"ref": REF}).status_code == 401
    assert c.post(URL, json={"ref": REF}).status_code == 401


def test_a_rota_registra_audita_e_devolve_a_situacao(cliente, esq):
    retorno = (date.today() + timedelta(days=2)).isoformat()
    r = cliente.post(URL, json={"ref": REF, "tipo": "contato", "canal": "email",
                                "descricao": "Mandei a segunda via.", "retorno_em": retorno})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["entrada"]["autor_nome"] == "Ana Cobrança"
    assert (d["tratativa"]["estado"], d["tratativa"]["total"]) == ("em_andamento", 1)
    h = cliente.get(URL, params={"ref": REF}).json()
    assert [e["descricao"] for e in h["historico"]] == ["Mandei a segunda via."]
    trilha = pglocal.um("SELECT usuario, acao, alvo FROM audit_log"
                        " WHERE acao = 'cobranca_tratativa'", esquema=esq)
    assert trilha == {"usuario": "ana@sulista.com.br", "acao": "cobranca_tratativa",
                      "alvo": REF}


def test_recusa_e_4xx_com_a_mensagem_para_a_tela(cliente):
    """5xx o Cloudflare troca pela página dele e a mensagem nunca chega."""
    fora = cliente.post(URL, json={"ref": "f" * 16, "tipo": "contato", "descricao": "x"})
    assert fora.status_code == 409 and "Régua" in fora.json()["mensagem"]
    ruim = cliente.post(URL, json={"ref": REF, "tipo": "promessa", "descricao": "x"})
    assert ruim.status_code == 409 and "data prometida" in ruim.json()["mensagem"]
    assert cliente.post(URL, json={"ref": "../x", "tipo": "contato",
                                   "descricao": "x"}).status_code == 422
    assert cliente.get(URL, params={"ref": "zz"}).status_code == 422


def test_a_regua_chega_na_tela_com_a_tratativa(cliente, monkeypatch):
    monkeypatch.setattr(queries, "get_cobranca", lambda filial, cliente=None: {
        "clientes": [{"cliente": "A", "ref": REF, "vencido": 500.0}],
        "total_vencido_top": 500.0, "atualizado_em": "2026-09-15T09:00:00"})
    d = cliente.get("/api/financeiro/cobranca").json()
    assert d["clientes"][0]["tratativa"]["estado"] == "sem_tratativa"
    assert d["tratativas"]["tipos"]["promessa"] == "Promessa de pagamento"
