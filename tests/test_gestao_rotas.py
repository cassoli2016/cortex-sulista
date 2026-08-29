"""As rotas de Gestão com sessão de verdade.

O que só se prova aqui, e não nos testes de serviço nem nos de tela:

1. **A recusa é 4xx, nunca 5xx.** "Informe o prazo" é o CÓRTEX funcionando e
   dizendo não, com um motivo que a pessoa precisa LER — e o Cloudflare TROCA o
   corpo das respostas 5xx da origem pela página de erro dele. Uma validação
   devolvida como 500 chegaria à tela como "erro interno da API", com a
   mensagem certa presa do lado de cá do túnel.
2. **Sem sessão é 401.** As telas novas entraram em `ROTA_TELAS`; se alguém
   errar o prefixo, o `AuthMiddleware` (fail-closed) devolve 403 para quem tem
   a tela — e o defeito só apareceria com um usuário não-admin.
3. **A escrita entra no `audit_log`.** É regra de segurança da casa
   (CLAUDE.md §8), e nada no módulo a garante sozinho.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from api import auth
from api.gestao import comum

SENHA = "senha-de-teste-123"


@pytest.fixture
def cliente(esquema_pg, monkeypatch):
    """API de pé com um administrador logado, sobre um schema descartável."""
    from api.main import app
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(comum, "ESQUEMA", esquema_pg)
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


def _amanha() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


# ------------------------------------------------------------------ acesso

@pytest.mark.parametrize("caminho", ["/api/gestao/painel", "/api/gestao/acoes",
                                     "/api/gestao/atas"])
def test_sem_sessao_e_401(caminho):
    from api.main import app
    assert TestClient(app).get(caminho).status_code == 401


# ---------------------------------------------------------------- caminho ok

def test_ciclo_completo_ata_acao_andamento(cliente):
    ata = cliente.post("/api/gestao/atas", json={
        "titulo": "Diretoria — fechamento", "data": "2026-08-31",
        "tipo": "diretoria", "decisoes": "Levantar limites",
        "participantes": [{"nome": "Cristian"}, {"nome": "Contador",
                                                 "presente": 0}]})
    assert ata.status_code == 200, ata.text
    a = ata.json()
    assert a["codigo"] == "ATA-2026-001"
    assert (a["participantes"], a["presentes"]) == (2, 1)

    acao = cliente.post("/api/gestao/acoes", json={
        "o_que": "Ligar para o gerente", "responsavel_nome": "Ana",
        "prazo": _amanha(), "reuniao_id": a["id"], "prioridade": "alta"})
    assert acao.status_code == 200, acao.text
    ac = acao.json()
    assert ac["reuniao_codigo"] == "ATA-2026-001"

    and_ = cliente.post(f"/api/gestao/acoes/{ac['id']}/andamento",
                        json={"texto": "Gerente retorna dia 3.",
                              "status": "em_andamento", "percentual": 40})
    assert and_.status_code == 200, and_.text
    assert and_.json()["percentual"] == 40
    assert and_.json()["andamentos"] == 2

    painel = cliente.get("/api/gestao/painel")
    assert painel.status_code == 200
    p = painel.json()
    assert p["resumo"]["abertas"] == 1
    assert "minhas" in p          # a fila de quem está logado vai junto


def test_lista_traz_o_contador_para_o_hint(cliente):
    """Top-N sem contador vira total falso."""
    for i in range(3):
        cliente.post("/api/gestao/acoes", json={
            "o_que": f"acao {i}", "responsavel_nome": "Ana",
            "prazo": _amanha()})
    d = cliente.get("/api/gestao/acoes").json()
    assert d["total"] == 3 and d["mostrando"] == 3
    assert d["usuarios"] and d["areas"]      # catálogos para o formulário


# --------------------------------------------------------------- recusa 4xx

@pytest.mark.parametrize("payload,trecho", [
    ({"o_que": "x", "prazo": ""}, "prazo"),
    ({"o_que": "", "responsavel_nome": "a", "prazo": "2026-12-01"}, "o que"),
    ({"o_que": "x", "prazo": "2026-12-01"}, "esponsável"),
    ({"o_que": "x", "responsavel_nome": "a", "prazo": "31/02/2026"}, "data"),
    ({"o_que": "x", "responsavel_nome": "a", "prazo": "2026-12-01",
      "quanto": "mil"}, "valor"),
])
def test_validacao_e_422_com_a_frase_que_a_pessoa_le(cliente, payload, trecho):
    """RECUSA NÃO É 5xx: o Cloudflare troca o corpo do 5xx pela página dele e
    a mensagem some antes de chegar à tela."""
    r = cliente.post("/api/gestao/acoes", json=payload)
    assert r.status_code == 422, r.text
    assert trecho in r.json()["mensagem"], r.json()


def test_corpo_que_nao_e_objeto_e_422(cliente):
    assert cliente.post("/api/gestao/acoes", json=[1, 2]).status_code == 422


def test_acao_inexistente_e_404(cliente):
    assert cliente.get("/api/gestao/acoes/999999").status_code == 404
    assert cliente.post("/api/gestao/acoes/999999/excluir").status_code == 404
    assert cliente.get("/api/gestao/atas/999999").status_code == 404


# ---------------------------------------------------------------- auditoria

def _auditoria(acoes: tuple[str, ...]) -> list[dict]:
    with auth._conn() as c:
        return c.execute(
            "SELECT acao, alvo, detalhe FROM audit_log "
            "WHERE acao = ANY(%s) ORDER BY id", (list(acoes),)).fetchall()


def test_toda_escrita_entra_no_audit_log(cliente):
    """Regra de segurança da casa — nada no módulo a garante sozinho."""
    ata = cliente.post("/api/gestao/atas", json={
        "titulo": "Reunião", "data": "2026-08-31"}).json()
    acao = cliente.post("/api/gestao/acoes", json={
        "o_que": "Fazer", "responsavel_nome": "Ana", "prazo": _amanha(),
        "reuniao_id": ata["id"]}).json()
    cliente.post(f"/api/gestao/acoes/{acao['id']}/andamento",
                 json={"texto": "andou"})
    cliente.post(f"/api/gestao/acoes/{acao['id']}/excluir")
    cliente.post(f"/api/gestao/atas/{ata['id']}/excluir")

    linhas = _auditoria(("gestao_ata", "gestao_acao", "gestao_andamento",
                         "gestao_acao_excluir", "gestao_ata_excluir"))
    assert [l["acao"] for l in linhas] == [
        "gestao_ata", "gestao_acao", "gestao_andamento",
        "gestao_acao_excluir", "gestao_ata_excluir"]
    # o alvo é a referência HUMANA, não o id: é por ela que a ata é citada
    assert linhas[0]["alvo"] == "ATA-2026-001"


def test_excluir_ata_registra_quantas_acoes_ficaram_orfas(cliente):
    """A consequência que quem clica não vê — e a que alguém vai querer
    reconstituir depois."""
    ata = cliente.post("/api/gestao/atas", json={
        "titulo": "Reunião", "data": "2026-08-31"}).json()
    cliente.post("/api/gestao/acoes", json={
        "o_que": "Sobrevive", "responsavel_nome": "Ana", "prazo": _amanha(),
        "reuniao_id": ata["id"]})
    r = cliente.post(f"/api/gestao/atas/{ata['id']}/excluir")
    assert r.json()["acoes_orfas"] == 1
    linha = _auditoria(("gestao_ata_excluir",))[0]
    assert "1 ações mantidas sem ata" in linha["detalhe"]
    # e a ação continua lá
    assert cliente.get("/api/gestao/acoes").json()["total"] == 1
