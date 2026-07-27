from __future__ import annotations

import base64
import json

import pytest

from api.premiacao import gobrax
from api.premiacao.gobrax import ClienteGobrax, GobraxIndisponivel


def _http_fabrica(respostas: list, chamadas: list):
    """Stub: cada item de `respostas` é (status, body); registra as chamadas."""
    def http(url, method, headers, body):
        chamadas.append({"url": url, "method": method, "headers": dict(headers), "body": body})
        st, bd = respostas.pop(0)
        return st, bd
    return http


def _fluxo_login():
    sess = {"id": "abc", "identity": {"id": "u1"}}
    tok = base64.b64encode(json.dumps(sess, separators=(",", ":")).encode()).decode()
    return [
        (200, {"methods": {"password": {"config": {"action": "https://v3.gobrax.com.br/login-action", "fields": []}}}}),
        (200, {"session": sess}),
        (200, {"data": {"token": "jwt-cred"}}),
    ], tok


def test_query_mantem_dois_pontos_literal_e_headers_completos():
    respostas, tok = _fluxo_login()
    respostas.append((200, {"ok": True}))
    chamadas = []
    c = ClienteGobrax(email="e@x.com", senha="s3nh4-de-teste", http=_http_fabrica(respostas, chamadas))
    c.get("/web/v2/performance/drivers/analysis",
          {"drivers": "1,2", "startDate": "2026-07-01T00:00:00Z"})
    ultima = chamadas[-1]
    assert "startDate=2026-07-01T00:00:00Z" in ultima["url"]      # ':' literal
    assert "%3A" not in ultima["url"]
    assert ultima["headers"]["Authorization"] == f"Bearer {tok}"
    assert ultima["headers"]["Credentials"] == "jwt-cred"
    assert ultima["headers"]["OriginVersion"] == "WEB 3.1"


def test_401_renova_o_login_uma_vez_e_repete():
    respostas, _ = _fluxo_login()
    respostas.append((401, {}))          # 1ª tentativa
    r2, _ = _fluxo_login()
    respostas += r2                      # relogin
    respostas.append((200, {"ok": 1}))   # repetição
    chamadas = []
    c = ClienteGobrax(email="e@x.com", senha="s", http=_http_fabrica(respostas, chamadas))
    assert c.get("/drivers", {"customers": 1}) == {"ok": 1}
    assert len(chamadas) == 8            # 3 login + 1 falha + 3 relogin + 1 ok


def test_falha_de_login_vira_gobrax_indisponivel():
    c = ClienteGobrax(email="e@x.com", senha="s",
                      http=_http_fabrica([(500, {})], []))
    with pytest.raises(GobraxIndisponivel):
        c.get("/drivers")


def test_sem_credenciais_no_ambiente(monkeypatch):
    monkeypatch.delenv("GOBRAX_EMAIL", raising=False)
    monkeypatch.delenv("GOBRAX_SENHA", raising=False)
    assert gobrax.configurado() is False
    monkeypatch.setenv("GOBRAX_EMAIL", "e@x.com")
    monkeypatch.setenv("GOBRAX_SENHA", "s")
    assert gobrax.configurado() is True
