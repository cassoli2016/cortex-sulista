"""Cliente mínimo da API do GitHub: sobe anexo e abre issue.

Só o que o report precisa - dois endpoints. Nenhuma dependência nova: `httpx`
já está no projeto.

O token NUNCA aparece em log nem em mensagem devolvida ao navegador. Erro do
GitHub volta como `ErroGitHub` com status e o texto do próprio GitHub, que já
é sanitizado ("Bad credentials", "Not Found") - basta para diagnosticar sem
expor credencial na tela de quem reportou.
"""
from __future__ import annotations

import json
import logging
import os

import httpx

API = "https://api.github.com"
TIMEOUT = 30.0

log = logging.getLogger("cortex.reports")


class ErroGitHub(RuntimeError):
    """Falha ao falar com o GitHub - mensagem já pronta para o usuário."""


class GitHub:
    def __init__(self, token: str, repo: str, http: httpx.Client | None = None):
        self.token = token
        self.repo = repo
        self._http = http

    # -------------------------------------------------------------- interno
    def _cliente(self) -> httpx.Client:
        return self._http or httpx.Client(timeout=TIMEOUT)

    def _cabecalhos(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}

    def _pedir(self, metodo: str, caminho: str, corpo: dict) -> dict:
        http = self._cliente()
        try:
            resp = http.request(metodo, f"{API}{caminho}", json=corpo,
                                headers=self._cabecalhos(), timeout=TIMEOUT)
        except httpx.HTTPError as exc:
            # str(exc) do httpx traz URL, nunca cabeçalho - token não vaza aqui
            log.warning("github inacessivel: %s", exc)
            raise ErroGitHub("Não foi possível falar com o GitHub. Sem internet?") from exc
        finally:
            if self._http is None:
                http.close()
        if resp.status_code >= 400:
            detalhe = ""
            try:
                detalhe = str(resp.json().get("message") or "")
            except (json.JSONDecodeError, ValueError, AttributeError):
                detalhe = ""
            log.warning("github respondeu %s: %s", resp.status_code, detalhe)
            raise ErroGitHub(f"GitHub respondeu {resp.status_code}"
                             + (f": {detalhe}" if detalhe else ""))
        try:
            return resp.json() or {}
        except (json.JSONDecodeError, ValueError):
            return {}

    # --------------------------------------------------------------- público
    def subir_anexo(self, caminho: str, b64: str) -> str:
        """Commita o arquivo no repo (Contents API) e devolve a URL de download.

        A API recebe o conteúdo em base64, que é exatamente o que o navegador
        mandou - o servidor não decodifica nem recodifica.
        """
        dado = self._pedir("PUT", f"/repos/{self.repo}/contents/{caminho}",
                           {"message": f"anexo de report: {caminho.rsplit('/', 1)[-1]}",
                            "content": b64})
        url = (dado.get("content") or {}).get("html_url") or \
            f"https://github.com/{self.repo}/blob/main/{caminho}"
        return f"{url}?raw=1"

    def criar_issue(self, titulo: str, corpo: str, rotulos: list[str]) -> tuple[int, str]:
        """Abre a issue. Label que ainda não existe é criada pela própria API."""
        dado = self._pedir("POST", f"/repos/{self.repo}/issues",
                           {"title": titulo, "body": corpo, "labels": rotulos})
        return int(dado.get("number") or 0), str(dado.get("html_url") or "")

    # ---- o que o módulo de Suporte usa para espelhar a conversa (mão dupla)
    def comentar(self, numero: int, corpo: str) -> int:
        dado = self._pedir("POST", f"/repos/{self.repo}/issues/{int(numero)}/comments", {"body": corpo})
        return int(dado.get("id") or 0)

    def alterar_issue(self, numero: int, *, state: str | None = None, labels: list[str] | None = None,
                      state_reason: str | None = None) -> dict:
        corpo: dict = {}
        if state:
            corpo["state"] = state
        if labels is not None:
            corpo["labels"] = labels
        if state_reason and state == "closed":
            corpo["state_reason"] = state_reason
        return self._pedir("PATCH", f"/repos/{self.repo}/issues/{int(numero)}", corpo)

    def comentarios(self, numero: int, since=None) -> list[dict]:
        """Comentários da issue (até 100), opcionalmente desde um instante."""
        q = "?per_page=100"
        if since is not None:
            s = since.isoformat() if hasattr(since, "isoformat") else str(since)
            q += "&since=" + s.replace("+00:00", "Z")
        dado = self._pedir("GET", f"/repos/{self.repo}/issues/{int(numero)}/comments{q}", None)
        return list(dado) if isinstance(dado, list) else []

    def issue(self, numero: int) -> dict:
        dado = self._pedir("GET", f"/repos/{self.repo}/issues/{int(numero)}", None)
        return dado if isinstance(dado, dict) else {}


# ------------------------------------------------------------------ ambiente

def repo_configurado() -> str:
    return (os.environ.get("REPORT_REPO") or "").strip()


def configurado() -> bool:
    """Sem token ou sem repo o recurso nasce desligado, sem erro.

    Mesmo padrão de GOBRAX e VAPID: o botão simplesmente não aparece no painel.
    """
    return bool((os.environ.get("GITHUB_TOKEN") or "").strip() and repo_configurado())


def do_ambiente() -> GitHub | None:
    if not configurado():
        return None
    return GitHub(os.environ["GITHUB_TOKEN"].strip(), repo_configurado())
