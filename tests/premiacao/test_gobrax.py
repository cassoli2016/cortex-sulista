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


def test_resposta_nao_json_em_sucesso_vira_gobrax_indisponivel():
    """Testa que corpo não-JSON em status 2xx lança GobraxIndisponivel, não JSONDecodeError."""
    from unittest.mock import patch, MagicMock
    import io

    # Simula resposta 200 com corpo não-JSON (desafio HTML do WAF)
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b"<html>Challenge</html>"
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=None)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        c = ClienteGobrax(email="e@x.com", senha="s")
        with pytest.raises(GobraxIndisponivel):
            c.get("/drivers")


def test_corpo_vazio_em_sucesso_retorna_dict_vazio():
    """Testa que corpo vazio ("") em status 2xx retorna {} via _http_urllib (não stub)."""
    from unittest.mock import patch, MagicMock
    from api.premiacao.gobrax import _http_urllib

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b""
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=None)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        st, body = _http_urllib("https://example.com/test", "GET", {}, None)
        assert st == 200
        assert body == {}


def test_fields_null_nao_quebra():
    """Testa que fields: null no Kratos não quebra (usa [] como default)."""
    respostas = [
        (200, {"methods": {"password": {"config": {"action": "https://v3.gobrax.com.br/login-action", "fields": None}}}}),
        (200, {"session": {"id": "abc", "identity": {"id": "u1"}}}),
        (200, {"data": {"token": "jwt-cred"}}),
    ]
    chamadas = []
    c = ClienteGobrax(email="e@x.com", senha="s", http=_http_fabrica(respostas, chamadas))
    # Deve chamar login sem erro
    c._login()
    assert c._token is not None
    assert c._cred == "jwt-cred"


def test_action_faltando_vira_gobrax_indisponivel():
    """Testa que falta de 'action' no Kratos lança GobraxIndisponivel, não ValueError."""
    respostas = [
        (200, {"methods": {"password": {"config": {"fields": []}}}}),  # sem action
    ]
    chamadas = []
    c = ClienteGobrax(email="e@x.com", senha="s", http=_http_fabrica(respostas, chamadas))
    with pytest.raises(GobraxIndisponivel):
        c.get("/drivers")
