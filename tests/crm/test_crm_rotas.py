"""As rotas do CRM com sessão de verdade.

O que só se prova aqui, e não nos testes de serviço nem nos de tela:

1. **Sem sessão é 401, e a tela entrou em `ROTA_TELAS`.** O `AuthMiddleware` é
   fail-closed: rota `/api/*` fora da tabela devolve 403 para quem NÃO é
   administrador — e o defeito só apareceria com um usuário comum, ou seja,
   nunca na bancada de quem testa logado como admin.
2. **Recusa é 4xx, nunca 5xx.** "Escolha o motivo da perda" é o CÓRTEX
   funcionando e dizendo não. O Cloudflare TROCA o corpo das respostas 5xx da
   origem pela página de erro dele, e a mensagem certa ficaria presa do lado de
   cá do túnel — a tela mostraria "erro interno da API".
3. **Toda escrita entra no `audit_log`** (CLAUDE.md §8.2). Nada no módulo de
   serviço garante isso sozinho.
4. **A resposta é SERIALIZÁVEL.** `date` e `Decimal` do psycopg estouram o
   `JSONResponse` com 500 — e os testes de serviço passam, porque nunca
   serializam. Foi assim que a Gestão descobriu o `iso()`.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from api import auth
from api.crm import comum, precificacao

SENHA = "senha-de-teste-123"


@pytest.fixture
def cliente(esquema_pg, monkeypatch):
    """API de pé com um administrador logado, sobre um schema descartável."""
    from api.main import app
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(comum, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(precificacao, "referencia_ckm",
                        lambda *a, **k: {"disponivel": True,
                                         "ckm_marginal": 3.50,
                                         "ckm_cheio": 5.20,
                                         "fonte": "dublê de teste"})
    from api.crm import ava
    monkeypatch.setattr(ava, "agrupamentos", lambda: [{"codigo": 7,
                                                       "nome": "TUPY"}])
    monkeypatch.setattr(ava, "carteira", lambda cods: {})
    auth.init_db()
    with auth._conn() as c:
        perfil = c.execute(
            "SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()
        c.execute(
            """INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                    deve_trocar_senha, criado_em)
               VALUES('Chefe','chefe@sulista.com.br',%s,%s,1,0,%s)""",
            (auth._ph.hash(SENHA), perfil["id"], auth._agora()))
    cli = TestClient(app)
    r = cli.post("/api/auth/login",
                 json={"email": "chefe@sulista.com.br", "senha": SENHA})
    assert r.status_code == 200, r.text
    return cli


def _auditoria(esquema: str, acao: str) -> list[dict]:
    from api import pglocal
    return pglocal.query(
        "SELECT usuario, acao, alvo, detalhe FROM audit_log WHERE acao=%s "
        "ORDER BY id", (acao,), esquema=esquema)


# ------------------------------------------------------------------- acesso

@pytest.mark.parametrize("caminho", [
    "/api/comercial/crm/painel", "/api/comercial/crm/catalogo",
    "/api/comercial/crm/contas", "/api/comercial/crm/oportunidades",
    "/api/comercial/crm/atividades", "/api/comercial/crm/contratos"])
def test_sem_sessao_e_401(caminho):
    from api.main import app
    assert TestClient(app).get(caminho).status_code == 401


def test_rotas_do_crm_estao_na_tabela_de_telas():
    """Sem isto, o `AuthMiddleware` fail-closed devolve 403 para quem não é
    administrador — e o botão aparece para todos funcionando só para um."""
    assert auth._telas_da_rota("/api/comercial/crm/contas") == frozenset({"crm"})
    assert auth._telas_da_rota("/api/comercial/crm/painel") == frozenset({"crm"})
    # e a base do Avacorp, que continua viva na sub-aba, na mesma tela
    assert auth._telas_da_rota("/api/comercial/crm") == frozenset({"crm"})


# -------------------------------------------------------------- caminho ok

def test_ciclo_completo(cliente, esquema_pg):
    conta = cliente.post("/api/comercial/crm/contas", json={
        "nome": "TUPY FUNDIÇÕES", "dono_nome": "Ana Vendas",
        "segmento": "Automotivo", "cnpj": "84.683.374/0001-49", "uf": "SC"})
    assert conta.status_code == 200, conta.text
    c = conta.json()
    assert c["situacao"] == "prospect"
    assert c["cnpj_fmt"] == "84.683.374/0001-49"

    contato = cliente.post("/api/comercial/crm/contatos", json={
        "conta_id": c["id"], "nome": "Carlos Compras", "papel": "comprador",
        "telefone": "(47) 99999-8888", "email": "carlos@tupy.com.br"})
    assert contato.status_code == 200, contato.text
    assert contato.json()["telefone"] == "5547999998888"

    opo = cliente.post("/api/comercial/crm/oportunidades", json={
        "conta_id": c["id"], "titulo": "Contrato 2027", "dono_nome": "Ana",
        "estagio": "proposta", "meses_contrato": 24,
        "previsao_fechamento": (date.today() + timedelta(days=40)).isoformat()})
    assert opo.status_code == 200, opo.text
    o = opo.json()
    assert o["codigo"] == "OPO-2026-001" or o["codigo"].startswith("OPO-")

    lane = cliente.post("/api/comercial/crm/lanes", json={
        "oportunidade_id": o["id"], "origem_cidade": "Joinville",
        "origem_uf": "SC", "destino_cidade": "Betim", "destino_uf": "MG",
        "km": "1.180", "km_vazio": "1.180", "viagens_mes": "22",
        "valor_viagem": "9.800,00", "tipo_veiculo": "Carreta LS (3 eixos)",
        "tipo_carga": "carga_geral"})
    assert lane.status_code == 200, lane.text
    ln = lane.json()
    assert ln["eixos"] == 6
    assert ln["calc"]["rkm"] == pytest.approx(9800 / 1180)
    assert ln["calc"]["piso"]["estado"] == "calculado"

    ficha = cliente.get(f"/api/comercial/crm/oportunidades/{o['id']}")
    assert ficha.status_code == 200
    assert ficha.json()["receita_mes"] == 9800 * 22

    mover = cliente.post(f"/api/comercial/crm/oportunidades/{o['id']}/mover",
                         json={"estagio": "ganha"})
    assert mover.status_code == 200, mover.text
    assert mover.json()["fechada_em"]

    ctr = cliente.post("/api/comercial/crm/contratos", json={
        "conta_id": c["id"], "oportunidade_id": o["id"], "dono_nome": "Ana",
        "objeto": "Transporte FTL eixo sul", "inicio": "2026-01-01",
        "fim": "2027-12-31", "indice_reajuste": "ipca", "mes_reajuste": 1})
    assert ctr.status_code == 200, ctr.text
    t = ctr.json()
    assert t["situacao"] in ("vigente", "a_vencer")
    # a tabela de preço da proposta ganha veio junto, COPIADA
    assert t.get("lanes_copiadas") == 1

    painel = cliente.get("/api/comercial/crm/painel")
    assert painel.status_code == 200, painel.text
    p = painel.json()
    assert p["kpis"]["contas"] == 1
    assert "minhas" in p


def test_toda_escrita_entra_na_auditoria(cliente, esquema_pg):
    c = cliente.post("/api/comercial/crm/contas",
                     json={"nome": "ACME", "dono_nome": "Ana"}).json()
    cliente.post("/api/comercial/crm/oportunidades", json={
        "conta_id": c["id"], "titulo": "Spot março", "dono_nome": "Ana"})
    reg = _auditoria(esquema_pg, "crm_conta")
    assert len(reg) == 1
    assert reg[0]["usuario"] == "chefe@sulista.com.br"
    assert "criada" in reg[0]["detalhe"] and "ACME" in reg[0]["detalhe"]
    assert len(_auditoria(esquema_pg, "crm_oportunidade")) == 1


def test_lane_abaixo_do_piso_vai_para_a_auditoria(cliente, esquema_pg):
    """Cotação abaixo do mínimo legal é exatamente o que alguém vai querer
    reconstituir depois."""
    c = cliente.post("/api/comercial/crm/contas",
                     json={"nome": "ACME", "dono_nome": "Ana"}).json()
    o = cliente.post("/api/comercial/crm/oportunidades", json={
        "conta_id": c["id"], "titulo": "Spot", "dono_nome": "Ana"}).json()
    cliente.post("/api/comercial/crm/lanes", json={
        "oportunidade_id": o["id"], "km": "1000", "viagens_mes": "5",
        "valor_viagem": "300,00", "tipo_veiculo": "Carreta LS (3 eixos)",
        "tipo_carga": "carga_geral"})
    reg = _auditoria(esquema_pg, "crm_lane")
    assert len(reg) == 1
    assert "piso ANTT" in reg[0]["detalhe"]


# ------------------------------------------------------------------- recusas

def test_recusa_e_422_com_a_mensagem_inteira(cliente):
    """5xx faria o Cloudflare trocar o corpo pela página de erro dele."""
    r = cliente.post("/api/comercial/crm/contas", json={"nome": ""})
    assert r.status_code == 422, r.text
    assert "nome" in r.json()["mensagem"].lower()

    c = cliente.post("/api/comercial/crm/contas",
                     json={"nome": "ACME", "dono_nome": "Ana"}).json()
    o = cliente.post("/api/comercial/crm/oportunidades", json={
        "conta_id": c["id"], "titulo": "Spot", "dono_nome": "Ana"}).json()
    r = cliente.post(f"/api/comercial/crm/oportunidades/{o['id']}/mover",
                     json={"estagio": "perdida"})
    assert r.status_code == 422, r.text
    assert "motivo" in r.json()["mensagem"].lower()


def test_conta_inexistente_e_404_e_nao_500(cliente):
    r = cliente.get("/api/comercial/crm/contas/98765")
    assert r.status_code == 404
    assert r.json()["erro"] == "nao_encontrado"


def test_corpo_invalido_e_recusa_e_nao_erro_interno(cliente):
    r = cliente.post("/api/comercial/crm/contas", content=b"nao sou json",
                     headers={"content-type": "application/json"})
    assert r.status_code == 422, r.text
    assert r.json()["erro"] == "parametro_invalido"


# -------------------------------------------------------------- serialização

def test_resposta_e_json_serializavel_de_ponta_a_ponta(cliente):
    """`date` e `Decimal` do psycopg estouram o JSONResponse com 500 — e o
    teste de serviço passa, porque nunca serializa."""
    c = cliente.post("/api/comercial/crm/contas",
                     json={"nome": "ACME", "dono_nome": "Ana"}).json()
    o = cliente.post("/api/comercial/crm/oportunidades", json={
        "conta_id": c["id"], "titulo": "Spot", "dono_nome": "Ana",
        "abertura": "2026-01-15",
        "previsao_fechamento": "2026-12-01"}).json()
    cliente.post("/api/comercial/crm/lanes", json={
        "oportunidade_id": o["id"], "km": "500,5", "viagens_mes": "12,5",
        "valor_viagem": "3.210,99", "pedagio": "180,40"})
    cliente.post("/api/comercial/crm/contratos", json={
        "conta_id": c["id"], "objeto": "FTL", "dono_nome": "Ana",
        "inicio": "2026-02-01", "fim": "2027-02-01",
        "percentual_ultimo": "6,5", "ultimo_reajuste": "2026-02-01"})
    for caminho in ("/api/comercial/crm/painel",
                    "/api/comercial/crm/catalogo",
                    "/api/comercial/crm/contas",
                    f"/api/comercial/crm/contas/{c['id']}",
                    "/api/comercial/crm/oportunidades",
                    f"/api/comercial/crm/oportunidades/{o['id']}",
                    "/api/comercial/crm/contratos",
                    "/api/comercial/crm/atividades",
                    "/api/comercial/crm/interacoes"):
        r = cliente.get(caminho)
        assert r.status_code == 200, f"{caminho}: {r.text}"
        r.json()  # estoura aqui se algo não for serializável


def test_catalogo_de_pe_com_o_erp_fora(cliente, monkeypatch):
    """Sem o ERP ainda dá para cadastrar tudo — só não dá para VINCULAR."""
    from api.crm import ava
    monkeypatch.setattr(ava, "agrupamentos",
                        lambda: (_ for _ in ()).throw(RuntimeError("fora")))
    r = cliente.get("/api/comercial/crm/catalogo")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["agrupamentos"] == []
    assert d["erp_indisponivel"] == "RuntimeError"
    assert d["estagios"] and d["cargas"] and d["veiculos"]


def test_interacao_nao_tem_rota_de_editar_nem_de_excluir():
    """Append-only também na superfície HTTP: uma rota de edição desfaria a
    garantia que o módulo dá."""
    from api.crm.rotas import router
    caminhos = {r.path for r in router.routes}
    assert "/api/comercial/crm/interacoes" in caminhos
    assert not any("interacoes" in p and ("excluir" in p or "editar" in p)
                   for p in caminhos)
