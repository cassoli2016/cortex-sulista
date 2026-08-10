"""Cliente da API do GitHub — testado com transporte dublê do httpx.

`httpx.MockTransport` exercita o cliente de verdade (montagem de URL, headers,
corpo, tratamento de status) sem tocar a rede. Mockar o `httpx.Client` inteiro
testaria o mock, não o cliente.
"""
from __future__ import annotations

import httpx
import pytest

from api.reports import github as gh

REPO = "cassoli2016/cortex-sulista-reports"
TOKEN = "ghp_duble_de_teste_123"  # sem acento: cabeçalho HTTP é ASCII


def _cliente(handler) -> gh.GitHub:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return gh.GitHub(TOKEN, REPO, http=http)


def test_subir_anexo_faz_put_no_caminho_do_repo_com_o_conteudo_base64():
    visto = {}

    def handler(req: httpx.Request) -> httpx.Response:
        visto["url"] = str(req.url)
        visto["metodo"] = req.method
        visto["corpo"] = req.read().decode()
        return httpx.Response(201, json={"content": {
            "html_url": f"https://github.com/{REPO}/blob/main/anexos/2026/08/p.png"}})

    url = _cliente(handler).subir_anexo("anexos/2026/08/p.png", "YWJj")

    assert visto["metodo"] == "PUT"
    assert visto["url"] == f"https://api.github.com/repos/{REPO}/contents/anexos/2026/08/p.png"
    assert '"content": "YWJj"' in visto["corpo"] or '"content":"YWJj"' in visto["corpo"]
    assert url.endswith("?raw=1")


def test_subir_anexo_manda_o_token_no_cabecalho():
    visto = {}

    def handler(req: httpx.Request) -> httpx.Response:
        visto["auth"] = req.headers.get("authorization")
        return httpx.Response(201, json={"content": {"html_url": "https://x/y"}})

    _cliente(handler).subir_anexo("anexos/p.png", "YWJj")
    assert visto["auth"] == f"Bearer {TOKEN}"


def test_criar_issue_devolve_numero_e_url():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert str(req.url) == f"https://api.github.com/repos/{REPO}/issues"
        return httpx.Response(201, json={
            "number": 7, "html_url": f"https://github.com/{REPO}/issues/7"})

    numero, url = _cliente(handler).criar_issue("[Bug] x", "corpo", ["bug"])
    assert (numero, url) == (7, f"https://github.com/{REPO}/issues/7")


def test_criar_issue_envia_titulo_corpo_e_rotulos():
    visto = {}

    def handler(req: httpx.Request) -> httpx.Response:
        visto["json"] = req.read().decode()
        return httpx.Response(201, json={"number": 1, "html_url": "https://x/1"})

    _cliente(handler).criar_issue("[Bug] título", "o corpo", ["bug", "tela:fluxo"])
    assert "[Bug] título" in visto["json"]
    assert "o corpo" in visto["json"]
    assert "tela:fluxo" in visto["json"]


def test_erro_do_github_vira_mensagem_legivel_sem_vazar_o_token():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    with pytest.raises(gh.ErroGitHub) as exc:
        _cliente(handler).criar_issue("t", "c", [])
    assert TOKEN not in str(exc.value)
    assert "401" in str(exc.value)


def test_repo_inexistente_diz_o_que_conferir():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    with pytest.raises(gh.ErroGitHub) as exc:
        _cliente(handler).criar_issue("t", "c", [])
    assert "404" in str(exc.value)


# ------------------------------------------------------------------ ambiente

def test_nao_configurado_sem_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("REPORT_REPO", REPO)
    assert gh.configurado() is False
    assert gh.do_ambiente() is None


def test_nao_configurado_sem_repo(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.delenv("REPORT_REPO", raising=False)
    assert gh.configurado() is False


def test_configurado_com_token_e_repo(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("REPORT_REPO", REPO)
    assert gh.configurado() is True
    assert gh.do_ambiente().repo == REPO
