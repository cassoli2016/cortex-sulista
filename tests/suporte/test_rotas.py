"""As rotas com sessão de verdade e TRÊS pessoas: usuário comum sem tela
nenhuma, atendente (perfil com `supfila`) e administrador.

O que só se prova aqui: o middleware fail-closed deixa o usuário comum abrir
e acompanhar o SEU chamado (`/api/suporte/meus`), barra `/atendimento` para
quem não tem a tela (403), e chamado alheio é 404 (não confirma que existe).
Avisos e espelho rodam em BackgroundTasks — no TestClient, antes do retorno.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import auth, pglocal
from api.suporte import avisos, espelho
from tests.suporte.conftest import PAYLOAD, SENHA


@pytest.fixture
def cli(sup, monkeypatch):
    from api.main import app
    # canais e GitHub dublados: nada sai da máquina
    monkeypatch.setattr(avisos, "avisar", lambda *a, **k: [])
    monkeypatch.setattr(espelho, "espelhar_abertura", lambda *a, **k: {"ok": False})
    monkeypatch.setattr(espelho, "espelhar_mensagem", lambda *a, **k: {"ok": False})
    monkeypatch.setattr(espelho, "espelhar_status", lambda *a, **k: {"ok": False})
    monkeypatch.setattr(espelho, "sincronizar", lambda *a, **k: {"pulou": True, "motivo": "dublê"})

    def entrar(email):
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"email": email, "senha": SENHA})
        assert r.status_code == 200, r.text
        return c
    return {"ana": entrar("ana@sulista.local"), "beto": entrar("beto@sulista.local"),
            "chefe": entrar("chefe@sulista.local"), "sup": sup}


def test_sem_sessao_e_401(sup):
    from api.main import app
    c = TestClient(app)
    assert c.get("/api/suporte/meus").status_code == 401
    assert c.post("/api/suporte/meus/chamados", json=PAYLOAD).status_code == 401
    assert c.get("/api/suporte/atendimento/painel").status_code == 401


def test_rbac_dos_prefixos():
    assert auth.rota_sem_tela("/api/suporte/meus/chamados/3/mensagens")
    assert not auth.rota_sem_tela("/api/suporte/atendimento/painel")
    assert not auth.rota_sem_tela("/api/suporte/qualquer")
    assert "sup" in auth.TELAS_FORA_DO_RBAC and "supfila" in auth.TELAS
    assert "sup" in auth.telas_favoritaveis({"id": 1, "admin": False, "telas": []})


def test_usuario_comum_abre_acompanha_responde_e_encerra(cli):
    ana = cli["ana"]
    r = ana.post("/api/suporte/meus/chamados", json={**PAYLOAD, "canais": {"email": True, "whatsapp": False}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["codigo"].startswith("SUP-") and d["url"] == f"#sup?chamado={d['id']}" and d["numero"] == d["codigo"]
    cid = d["id"]
    assert ana.get("/api/suporte/meus").json()["kpis"]["abertos"] == 1
    det = ana.get(f"/api/suporte/meus/chamados/{cid}").json()
    assert det["status"] == "aberto" and det["esperando"] == "suporte" and "avisos" not in det
    assert ana.post(f"/api/suporte/meus/chamados/{cid}/mensagens", json={"texto": "mais um detalhe"}).status_code == 200
    assert ana.post(f"/api/suporte/meus/chamados/{cid}/lido").status_code == 200
    # atendimento é de outra tela: 403 para quem não a tem
    assert ana.get("/api/suporte/atendimento/painel").status_code == 403
    assert ana.get(f"/api/suporte/atendimento/chamados/{cid}").status_code == 403
    # desistir: aberto -> fechado
    r = ana.post(f"/api/suporte/meus/chamados/{cid}/status", json={"status": "fechado"})
    assert r.status_code == 200 and r.json()["status"] == "fechado"
    # encerrado: responder é 409 com frase; reabrir sem texto é 422
    r = ana.post(f"/api/suporte/meus/chamados/{cid}/mensagens", json={"texto": "oi"})
    assert r.status_code == 409 and "reabra" in r.json()["mensagem"].lower()
    r = ana.post(f"/api/suporte/meus/chamados/{cid}/status", json={"status": "aberto"})
    assert r.status_code == 422 and r.json()["mensagem"]
    assert ana.post(f"/api/suporte/meus/chamados/{cid}/status", json={"status": "aberto", "texto": "voltou"}).status_code == 200


def test_chamado_alheio_e_404_nao_403(cli):
    ana, beto = cli["ana"], cli["beto"]
    cid = ana.post("/api/suporte/meus/chamados", json=PAYLOAD).json()["id"]
    assert beto.get(f"/api/suporte/meus/chamados/{cid}").status_code == 404
    assert beto.post(f"/api/suporte/meus/chamados/{cid}/mensagens", json={"texto": "x"}).status_code == 404
    assert beto.post(f"/api/suporte/meus/chamados/{cid}/lido").status_code == 404
    aid = ana.get(f"/api/suporte/meus/chamados/{cid}").json()["anexos"][0]["id"]
    assert beto.get(f"/api/suporte/meus/chamados/{cid}/anexos/{aid}").status_code == 404
    r = ana.get(f"/api/suporte/meus/chamados/{cid}/anexos/{aid}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/png") and "inline" in r.headers["content-disposition"]


def test_atendente_assume_responde_resolve_e_ve_a_trilha(cli):
    ana, beto = cli["ana"], cli["beto"]
    cid = ana.post("/api/suporte/meus/chamados", json=PAYLOAD).json()["id"]
    p = beto.get("/api/suporte/atendimento/painel")
    assert p.status_code == 200 and p.json()["kpis"]["abertos"] == 1 and p.json()["fila"]["mostrando"] == 1
    assert beto.post(f"/api/suporte/atendimento/chamados/{cid}/assumir").status_code == 200
    r = beto.post(f"/api/suporte/atendimento/chamados/{cid}/mensagens", json={"texto": "Anotação", "interna": True})
    assert r.status_code == 200
    det_ana = ana.get(f"/api/suporte/meus/chamados/{cid}").json()
    assert not any(m["interna"] for m in det_ana["mensagens_lista"])
    r = beto.post(f"/api/suporte/atendimento/chamados/{cid}/status", json={"status": "resolvido"})
    assert r.status_code == 422                                          # texto obrigatório
    r = beto.post(f"/api/suporte/atendimento/chamados/{cid}/status", json={"status": "resolvido", "texto": "Feito."})
    assert r.status_code == 200
    det = beto.get(f"/api/suporte/atendimento/chamados/{cid}").json()
    assert det["status"] == "resolvido" and "avisos" in det and det["atribuido_nome"] == "Beto Suporte"
    # dono confirma com avaliação
    r = ana.post(f"/api/suporte/meus/chamados/{cid}/status", json={"status": "fechado", "avaliacao": 4})
    assert r.status_code == 200
    assert beto.get(f"/api/suporte/atendimento/chamados/{cid}").json()["avaliacao"] == 4
    assert beto.get("/api/suporte/atendimento/indicadores?dias=30").json()["avaliacoes"] == 1
    assert beto.get("/api/suporte/atendimento/avisos").status_code == 200
    # toda escrita entrou no audit
    acoes = {r["acao"] for r in pglocal.query("SELECT acao FROM audit_log", esquema=cli["sup"]["esquema"])}
    assert {"sup_abrir", "sup_assumir", "sup_responder", "sup_status"} <= acoes


def test_config_so_admin_grava(cli):
    beto, chefe = cli["beto"], cli["chefe"]
    assert beto.get("/api/suporte/atendimento/config").status_code == 200
    assert beto.post("/api/suporte/atendimento/config", json={"sla_horas_alta": "4"}).status_code == 403
    r = chefe.post("/api/suporte/atendimento/config", json={"sla_horas_alta": "4"})
    assert r.status_code == 200 and r.json()["config"]["sla_horas_alta"] == "4"
    assert chefe.post("/api/suporte/atendimento/config", json={"sla_horas_alta": "abc"}).status_code == 422


def test_validacao_e_tamanho_sao_4xx_com_mensagem(cli):
    ana = cli["ana"]
    r = ana.post("/api/suporte/meus/chamados", json={**PAYLOAD, "tipo": "sugestao"})
    assert r.status_code == 422 and r.json()["mensagem"]
    r = ana.post("/api/suporte/meus/chamados", content=b"nao e json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    r = ana.post("/api/suporte/meus/chamados", content=b"{}", headers={"Content-Type": "application/json",
                                                                       "Content-Length": str(40 * 1024 * 1024)})
    assert r.status_code == 413
    r = ana.post("/api/suporte/meus/chamados", json={**PAYLOAD, "canais": {"whatsapp": True}})
    assert r.status_code == 200                                          # ana tem telefone


def test_alias_do_report_antigo_abre_chamado(cli):
    ana = cli["ana"]
    assert ana.get("/api/report/config").json()["ativo"] is True
    r = ana.post("/api/report", json={k: v for k, v in PAYLOAD.items() if k != "canais"})
    assert r.status_code == 200 and r.json()["numero"].startswith("SUP-")


def test_resposta_e_serializavel_e_o_meu_nao_traz_bytes(cli):
    ana = cli["ana"]
    ana.post("/api/suporte/meus/chamados", json=PAYLOAD)
    corpo = ana.get("/api/suporte/meus").json()
    json.dumps(corpo)
    assert "bytes" not in json.dumps(corpo)


def test_sino_lista_o_chamado_e_dispensar_marca_lido(cli):
    ana, beto = cli["ana"], cli["beto"]
    cid = ana.post("/api/suporte/meus/chamados", json=PAYLOAD).json()["id"]
    beto.post(f"/api/suporte/atendimento/chamados/{cid}/mensagens", json={"texto": "Olá"})
    s = ana.get("/api/notificacoes").json()
    chaves = [i["chave"] for i in s["itens"]]
    assert f"sup:{cid}" in chaves
    r = ana.post("/api/notificacoes/lida", json={"chave": f"sup:{cid}"})
    assert r.status_code == 200
    assert f"sup:{cid}" not in [i["chave"] for i in ana.get("/api/notificacoes").json()["itens"]]
