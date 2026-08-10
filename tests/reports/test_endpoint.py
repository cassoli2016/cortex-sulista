"""Endpoints do report e o RBAC deles.

O miolo do POST mora em `_report_responder`, função síncrona que recebe o
corpo já lido e o usuário da sessão: assim dá para testar o mapeamento de erro
→ status sem harness de sessão, no mesmo espírito de `tests/frontend/test_versao.py`.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import auth
from api.main import _report_responder, app, report_config
from api.reports.github import ErroGitHub

USUARIO = {"nome": "Fulano", "email": "fulano@sulista.com.br", "perfil": "Operação",
           "admin": False}


def _payload(**troca) -> dict:
    base = {"tipo": "melhoria", "gravidade": "media", "titulo": "Filtro de filial",
            "descricao": "Queria filtrar por filial nesta tela.",
            "contexto": {"tela": "com"}, "anexos": []}
    base.update(troca)
    return base


class ClienteFalso:
    def __init__(self, erro: Exception | None = None):
        self.erro = erro

    def subir_anexo(self, caminho, b64):  # pragma: no cover - sem anexo nos testes
        return "https://x"

    def criar_issue(self, titulo, corpo, rotulos):
        if self.erro:
            raise self.erro
        return 42, "https://github.com/o/r/issues/42"


@pytest.fixture(autouse=True)
def _sem_audit(monkeypatch):
    """O audit grava em SQLite; aqui só interessa que o endpoint o chame."""
    chamadas = []
    monkeypatch.setattr(auth, "audit", lambda *a, **k: chamadas.append(a))
    return chamadas


# ---------------------------------------------------------------------- RBAC

def test_endpoints_exigem_sessao():
    cli = TestClient(app)
    assert cli.get("/api/report/config").status_code == 401
    assert cli.post("/api/report", json=_payload()).status_code == 401


def test_report_nao_e_privilegio_de_tela():
    """Reportar tem de valer para QUALQUER usuário logado.

    O middleware é fail-closed: rota /api/* que não esteja em ROTA_TELAS nem na
    lista de exceções devolve 403 para não-admin. Sem esta liberação, só o
    administrador conseguiria mandar report — e ninguém perceberia, porque o
    botão aparece para todo mundo.
    """
    assert auth._telas_da_rota("/api/report") is None
    assert auth.rota_sem_tela("/api/report") is True
    assert auth.rota_sem_tela("/api/report/config") is True
    assert auth.rota_sem_tela("/api/comercial/clientes") is False


# -------------------------------------------------------------------- config

def test_config_desligada_sem_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    corpo = json.loads(report_config().body)
    assert corpo["ativo"] is False


def test_config_ligada_com_token_e_repo(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("REPORT_REPO", "o/r")
    corpo = json.loads(report_config().body)
    assert corpo == {"ativo": True, "repo": "o/r"}


# ---------------------------------------------------------------------- POST

def _responder(payload, cliente=None, monkeypatch=None):
    bruto = json.dumps(payload).encode()
    return _report_responder(bruto, USUARIO, cliente or ClienteFalso())


def test_report_valido_devolve_numero_da_issue():
    resp = _responder(_payload())
    assert resp.status_code == 200
    assert json.loads(resp.body) == {"numero": 42,
                                     "url": "https://github.com/o/r/issues/42"}


def test_report_valido_entra_no_audit(_sem_audit):
    _responder(_payload())
    assert _sem_audit, "toda escrita entra no audit_log"
    assert "report" in _sem_audit[0][1]


def test_corpo_que_nao_e_json_devolve_422():
    resp = _report_responder(b"nao sou json", USUARIO, ClienteFalso())
    assert resp.status_code == 422


def test_payload_invalido_devolve_422_com_a_mensagem():
    resp = _responder(_payload(titulo=""))
    assert resp.status_code == 422
    assert json.loads(resp.body)["mensagem"] == "Escreva um título."


def test_sem_configuracao_devolve_503():
    resp = _report_responder(json.dumps(_payload()).encode(), USUARIO, None)
    assert resp.status_code == 503
    assert json.loads(resp.body)["erro"] == "nao_configurado"


def test_falha_do_github_devolve_502_com_o_motivo():
    resp = _responder(_payload(), ClienteFalso(ErroGitHub("GitHub respondeu 401")))
    assert resp.status_code == 502
    assert "401" in json.loads(resp.body)["mensagem"]


def test_erro_inesperado_nao_vaza_detalhe_interno():
    resp = _responder(_payload(), ClienteFalso(RuntimeError("token ghp_segredo invalido")))
    assert resp.status_code == 500
    assert "ghp_segredo" not in resp.body.decode()
