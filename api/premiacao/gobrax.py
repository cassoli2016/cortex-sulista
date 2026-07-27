"""Cliente mínimo da API Gobrax v3 (stdlib) — login Kratos + 3 headers do gateway.

Credenciais SÓ via GOBRAX_EMAIL/GOBRAX_SENHA (os.environ; o .env é carregado por
api.db no import). Valores nunca aparecem em log ou erro. HTTP com urllib.request
porque o venv não tem requests/httpx (import de requests já derrubou a app).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlencode

GATEWAY = "https://gateway-v3-waf.gobrax.com.br"
KRATOS_LOGIN = "https://v3.gobrax.com.br/safekratos/self-service/login/api"
ORIGIN_VERSION = "WEB 3.1"


class GobraxNaoConfigurado(RuntimeError):
    pass


class GobraxIndisponivel(RuntimeError):
    pass


def configurado() -> bool:
    return bool(os.environ.get("GOBRAX_EMAIL") and os.environ.get("GOBRAX_SENHA"))


def _http_urllib(url: str, method: str, headers: dict, body: dict | None):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = dict(headers)
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            try:
                return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
            except ValueError as e:
                raise GobraxIndisponivel(f"A API Gobrax devolveu uma resposta que não é JSON.") from e
    except urllib.error.HTTPError as e:
        try:
            corpo = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            corpo = {}
        return e.code, corpo
    except urllib.error.URLError as e:
        raise GobraxIndisponivel(f"Sem conexão com a API Gobrax: {e.reason}") from e


class ClienteGobrax:
    def __init__(self, email: str | None = None, senha: str | None = None, http=None):
        self.email = email or os.environ.get("GOBRAX_EMAIL", "")
        self._senha = senha or os.environ.get("GOBRAX_SENHA", "")
        if not (self.email and self._senha):
            raise GobraxNaoConfigurado(
                "Defina GOBRAX_EMAIL e GOBRAX_SENHA no .env para habilitar a coleta.")
        self._http = http or _http_urllib
        self._token: str | None = None
        self._cred: str | None = None

    # -- autenticação ------------------------------------------------------
    def _login(self) -> None:
        st, flow = self._http(KRATOS_LOGIN, "GET", {"Accept": "application/json"}, None)
        if st >= 400:
            raise GobraxIndisponivel(f"Login Gobrax falhou no flow (HTTP {st}).")
        cfg = (flow.get("methods") or {}).get("password", {}).get("config", {})
        action = cfg.get("action")
        if not action:
            raise GobraxIndisponivel(f"Resposta de login do Kratos sem action.")
        payload = {"identifier": self.email, "password": self._senha, "method": "password"}
        csrf = next((f.get("value") for f in (cfg.get("fields") or [])
                     if f.get("name") == "csrf_token" and f.get("value")), None)
        if csrf:
            payload["csrf_token"] = csrf
        st, data = self._http(action, "POST", {"Accept": "application/json"}, payload)
        sess = (data or {}).get("session")
        if st >= 400 or not sess:
            # nunca ecoar a resposta: pode conter dados da conta
            raise GobraxIndisponivel(f"Login Gobrax recusado (HTTP {st}). Confira as credenciais no .env.")
        tok_json = json.dumps(sess, separators=(",", ":"), ensure_ascii=False)
        self._token = base64.b64encode(tok_json.encode("utf-8")).decode("ascii")
        st, user = self._http(f"{GATEWAY}/user/{self.email}", "GET",
                              self._headers(sem_cred=True), None)
        self._cred = ((user or {}).get("data") or {}).get("token")
        if st >= 400 or not self._cred:
            raise GobraxIndisponivel(f"Não obtive o header Credentials (HTTP {st}).")

    def _headers(self, sem_cred: bool = False) -> dict:
        h = {"Accept": "application/json", "Authorization": f"Bearer {self._token}",
             "OriginVersion": ORIGIN_VERSION}
        if not sem_cred and self._cred:
            h["Credentials"] = self._cred
        return h

    # -- chamadas ----------------------------------------------------------
    def get(self, path: str, params: dict | None = None) -> dict:
        if self._token is None:
            self._login()
        url = f"{GATEWAY}{path}"
        if params:
            url += "?" + urlencode(params, safe=":,")   # gateway rejeita %3A
        st, body = self._http(url, "GET", self._headers(), None)
        if st == 401:                                    # token expirou (~24h)
            self._login()
            st, body = self._http(url, "GET", self._headers(), None)
        if st >= 400:
            raise GobraxIndisponivel(f"API Gobrax devolveu HTTP {st} em {path}.")
        return body
