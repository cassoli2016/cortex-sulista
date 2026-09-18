# -*- coding: utf-8 -*-
"""As rotas da régua nova, com sessão de verdade e duas pessoas.

O que só se prova aqui:

- o middleware é FAIL-CLOSED: quem não tem a tela `prem` leva 403 em tudo,
  inclusive nas rotas que ainda nem existiam quando o perfil foi criado;
- a régua nova entra sob a tela ANTIGA (`prem`): id novo faria a premiação
  sumir do menu de quem já tem acesso hoje;
- recusa legível é 409 e não 500 — o Cloudflare troca o corpo dos 5xx pela
  página dele, e a mensagem nunca chega a quem precisa dela;
- a tela fala por CÓDIGO DO CADASTRO nos dois sentidos: o CPF não sai no
  payload e não é aceito na entrada;
- toda escrita deixa linha na trilha.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import auth, pglocal
from api.premiacao import (config, fechamento, identidade, parametros, premio,
                           ranking)

SENHA = "senha-de-teste-123"
CICLO = "2026-09"


@pytest.fixture
def cli(esquema_pg, monkeypatch):
    for mod in (premio, parametros, config, identidade, fechamento):
        monkeypatch.setattr(mod, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        adm = c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id"
                        " LIMIT 1").fetchone()
        c.execute("INSERT INTO perfis(nome, descricao, admin, criado_em)"
                  " VALUES('Comum','sem telas',0,%s)", (auth._agora(),))
        comum = c.execute("SELECT id FROM perfis WHERE nome='Comum'").fetchone()["id"]
        c.execute("INSERT INTO perfis(nome, descricao, admin, criado_em)"
                  " VALUES('GMA Teste','premiacao',0,%s)", (auth._agora(),))
        frota = c.execute("SELECT id FROM perfis WHERE nome='GMA Teste'").fetchone()["id"]
        c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,'prem')",
                  (frota,))
        for nome, email, perfil in (("Ana Comum", "ana@sulista.local", comum),
                                    ("Beto Frota", "beto@sulista.local", frota),
                                    ("Chefe", "chefe@sulista.local", adm["id"])):
            c.execute(
                "INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,"
                " deve_trocar_senha, criado_em) VALUES(%s,%s,%s,%s,1,0,%s)",
                (nome, email, auth._ph.hash(SENHA), perfil, auth._agora()))
    pglocal.executar(
        "INSERT INTO prm_motorista(cpf, nome, cadastro_codigo, tipo,"
        " tipo_origem, filial, filial_origem, admissao, ativo)"
        " VALUES('11111111111','MOTORISTA UM','111','RODOVIARIO','sugerido',"
        "'SBC','folha','2020-01',1)", esquema=esquema_pg)
    monkeypatch.setattr(ranking, "montar", lambda c=None, dir_snapshots=None: {
        "ciclo": CICLO, "rotulo": "16/08 a 15/09 de 2026",
        "linhas": [{"motorista": "111", "nome": "MOTORISTA UM",
                    "tipo": "RODOVIARIO", "filial": "SBC", "admissao": "2020-01",
                    "gobrax": None, "conduta": 90.0, "gr": None, "nota": 90.0,
                    "status": "BOM", "categoria": "OURO", "medida": None,
                    "desvios": [], "pilares": ["conduta"], "ausentes": []}],
        "kpis": {"motoristas": 1}, "fontes": {}, "pendencias": {}})

    from api.main import app

    def entrar(email):
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"email": email, "senha": SENHA})
        assert r.status_code == 200, r.text
        return c
    return {"ana": entrar("ana@sulista.local"),
            "beto": entrar("beto@sulista.local"),
            "chefe": entrar("chefe@sulista.local"), "esquema": esquema_pg}


ROTAS_GET = ["/api/premiacao/gma/ciclo", "/api/premiacao/gma/pagamento",
             "/api/premiacao/gma/catalogo", "/api/premiacao/gma/valores",
             "/api/premiacao/gma/motoristas"]


def test_sem_sessao_e_401(cli):
    from api.main import app
    c = TestClient(app)
    for rota in ROTAS_GET:
        assert c.get(rota).status_code == 401, rota


@pytest.mark.parametrize("rota", ROTAS_GET)
def test_quem_nao_tem_a_tela_leva_403(cli, rota):
    """Fail-closed: rota nova que ninguém mapeasse seria 403 também, e é assim
    que se quer — o padrão é negar."""
    assert cli["ana"].get(rota).status_code == 403


def test_a_regua_nova_entra_sob_a_tela_ANTIGA(cli):
    """Id novo faria a premiação sumir do menu de quem já tem acesso hoje."""
    assert auth._telas_da_rota("/api/premiacao/gma/ciclo") == frozenset({"prem"})
    assert auth._telas_da_rota("/api/premiacao/config") == frozenset({"prem"})


@pytest.mark.parametrize("rota", ROTAS_GET)
def test_quem_tem_a_tela_le(cli, rota):
    assert cli["beto"].get(rota).status_code == 200, rota


def test_o_ciclo_invalido_e_RECUSA_legivel_e_nao_erro_do_servidor(cli):
    r = cli["beto"].get("/api/premiacao/gma/pagamento?ciclo=setembro")
    assert r.status_code == 409 and "Ciclo inválido" in r.json()["mensagem"]


def test_salvar_parametro_com_peso_que_nao_soma_100_e_409(cli):
    r = cli["beto"].post("/api/premiacao/gma/parametros", json={
        "ciclo": CICLO, "grupo": "RODOVIARIO",
        "valores": {"peso_gobrax": 50, "peso_conduta": 30, "peso_gr": 10}})
    assert r.status_code == 409 and "somam" in r.json()["mensagem"]


def test_salvar_valores_e_ler_de_volta(cli):
    r = cli["beto"].post("/api/premiacao/gma/valores", json={
        "ciclo": CICLO, "grupo": "RODOVIARIO",
        "filiais": {"SBC": {"valor": 1000}}})
    assert r.status_code == 200, r.text
    tab = cli["beto"].get(f"/api/premiacao/gma/valores?ciclo={CICLO}").json()
    assert tab["base"]["RODOVIARIO"]["SBC"]["valor"] == 1000


def test_o_ajuste_entra_por_CODIGO_e_o_CPF_nao_volta(cli):
    r = cli["beto"].post("/api/premiacao/gma/ajuste", json={
        "ciclo": CICLO, "motorista": "111", "valor": 500,
        "motivo": "acordo de transição"})
    assert r.status_code == 200, r.text
    assert r.json()["motorista"] == "111" and "cpf" not in r.json()
    assert "11111111111" not in r.text


def test_o_ajuste_de_quem_nao_esta_no_cadastro_e_recusado(cli):
    r = cli["beto"].post("/api/premiacao/gma/ajuste", json={
        "ciclo": CICLO, "motorista": "999", "valor": 500, "motivo": "x"})
    assert r.status_code == 409 and "fora do cadastro" in r.json()["mensagem"]


def test_o_ajuste_sem_motivo_e_recusado(cli):
    r = cli["beto"].post("/api/premiacao/gma/ajuste", json={
        "ciclo": CICLO, "motorista": "111", "valor": 500, "motivo": " "})
    assert r.status_code == 409 and "motivo" in r.json()["mensagem"]


def test_limpar_o_ajuste_e_o_valor_AUSENTE(cli):
    cli["beto"].post("/api/premiacao/gma/ajuste", json={
        "ciclo": CICLO, "motorista": "111", "valor": 500, "motivo": "x"})
    r = cli["beto"].post("/api/premiacao/gma/ajuste", json={
        "ciclo": CICLO, "motorista": "111"})
    assert r.status_code == 200 and r.json()["valor"] is None
    assert premio.ajustes(CICLO) == {}


def test_fechar_um_ciclo_em_curso_e_recusa_com_o_motivo_na_mensagem(cli,
                                                                    monkeypatch):
    from datetime import date

    class Hoje(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 10)
    monkeypatch.setattr(fechamento, "date", Hoje)
    r = cli["beto"].post("/api/premiacao/gma/fechar", json={"ciclo": CICLO})
    assert r.status_code == 409 and "só termina em 15/09" in r.json()["mensagem"]


def test_fechar_reabrir_e_a_trilha(cli):
    from datetime import date

    cli["beto"].post("/api/premiacao/gma/valores", json={
        "ciclo": CICLO, "grupo": "RODOVIARIO", "filiais": {"SBC": {"valor": 1000}}})
    r = cli["beto"].post("/api/premiacao/gma/fechar",
                         json={"ciclo": CICLO, "nota": "folha de setembro"}) \
        if date.today() >= date(2026, 9, 16) else None
    if r is None:                       # a suíte roda antes do fim do ciclo
        r = cli["beto"].post("/api/premiacao/gma/fechar",
                             json={"ciclo": CICLO, "forcar": True,
                                   "nota": "fechamento de ensaio"})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 900.0
    assert cli["beto"].post("/api/premiacao/gma/reabrir",
                            json={"ciclo": CICLO, "motivo": "ocorrência atrasada"}
                            ).status_code == 200
    assert cli["beto"].post("/api/premiacao/gma/reabrir",
                            json={"ciclo": CICLO}).status_code == 409
    acoes = [r["acao"] for r in pglocal.query(
        "SELECT acao FROM audit_log ORDER BY id", esquema=cli["esquema"])]
    assert "gma_fechar" in acoes and "gma_reabrir" in acoes


def test_o_depara_aceita_D_M_e_IGNORAR_e_recusa_o_resto(cli):
    for alvo in ("D01", "M07", "IGNORAR"):
        assert cli["beto"].post("/api/premiacao/gma/depara",
                                json={"codigo": 79, "alvo": alvo}
                                ).status_code == 200, alvo
    r = cli["beto"].post("/api/premiacao/gma/depara",
                         json={"codigo": 79, "alvo": "D99"})
    assert r.status_code == 409 and "Alvo inválido" in r.json()["mensagem"]
    assert parametros.depara()[79] == "IGNORAR"


def test_decidir_o_tipo_do_motorista_vira_manual(cli):
    r = cli["beto"].post("/api/premiacao/gma/motorista",
                         json={"motorista": "111", "tipo": "MANOBRA"})
    assert r.status_code == 200, r.text
    linha = identidade.listar()[0]
    assert linha["tipo"] == "MANOBRA" and linha["tipo_origem"] == "manual"


def test_tipo_invalido_e_recusa_legivel(cli):
    r = cli["beto"].post("/api/premiacao/gma/motorista",
                         json={"motorista": "111", "tipo": "PILOTO"})
    assert r.status_code == 409 and "Tipo inválido" in r.json()["mensagem"]


def test_o_catalogo_traz_a_regua_e_o_de_para_para_a_tela(cli):
    d = cli["beto"].get(f"/api/premiacao/gma/catalogo?ciclo={CICLO}").json()
    assert d["ciclo"] == CICLO and d["rotulo"] == "16/08 a 15/09 de 2026"
    assert len(d["ciclos"]) == 13 and d["ciclos"][0] == CICLO
    assert d["parametros_do_ciclo"]["RODOVIARIO"]["valores"]["peso_gobrax"] == 40
    assert len(d["desvios"]) == 14 and len(d["meritos"]) == 10
    assert d["cadastro"]["ativos"] == 1


def test_o_cadastro_de_motoristas_nao_traz_CPF_para_a_tela(cli):
    """`identidade.listar` guarda o CPF para quem monta o ciclo; a ROTA é o
    limite em que ele para. Quem tem a tela da premiação não precisa do CPF
    para decidir tipo e filial — precisa do código do cadastro."""
    r = cli["beto"].get("/api/premiacao/gma/motoristas")
    assert r.status_code == 200 and "11111111111" not in r.text
    assert r.json()["linhas"][0]["cadastro_codigo"] == "111"
