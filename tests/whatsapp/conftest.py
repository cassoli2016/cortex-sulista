"""Ambiente dos testes de WhatsApp: credencial falsa, config em tmp, sem rede.

NENHUM teste deste diretório pode sair para a internet nem escrever no
`data/whatsapp_config.json` de verdade — o segundo é o erro que já aconteceu
neste repositório (`test_main_extrato`) e que só apareceu quando alguém notou
a produção mudando sozinha.
"""
from __future__ import annotations

import pytest

from api.whatsapp import cliente, config as cfg

# Credenciais falsas, mas com CARA de credencial: o `_sanitizar` só age em
# segredo com 6+ caracteres, então um "x" de mentira faria o teste de vazamento
# passar sem testar nada.
INSTANCIA = "3D2F8A1C4B6E9077"
TOKEN = "A91B7C5D3E2F4088"
CLIENT_TOKEN = "F4C2E8A6B0D19355"


@pytest.fixture(autouse=True)
def ambiente(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "CAMINHO", tmp_path / "whatsapp_config.json")
    monkeypatch.setattr(cliente, "_cred", lambda nome: {
        "ZAPI_INSTANCIA": INSTANCIA,
        "ZAPI_TOKEN": TOKEN,
        "ZAPI_CLIENT_TOKEN": CLIENT_TOKEN,
    }.get(nome, ""))
    # o estado da conexão tem cache de 60 s: sem limpar, o segundo teste leria
    # a resposta do primeiro e passaria por engano
    cliente.limpar_cache()
    yield
    cliente.limpar_cache()


def gravar_config(**kw) -> dict:
    """Config válida por padrão — cada teste muda só o que está examinando."""
    base = {"ativo": True, "limite_dia": 60, "intervalo_seg": 5,
            "janela_inicio": "00:00", "janela_fim": "23:59", "assinatura": ""}
    base.update(kw)
    return cfg.gravar(base)


def http_falso(*, conectado=True, celular=True, envio_status=200,
               envio_corpo=None, ao_enviar=None):
    """Dublê de `cliente._http`. Guarda as chamadas para o teste inspecionar."""
    chamadas: list[dict] = []

    def _http(url, headers, timeout, dados=None):
        import json as _json
        chamadas.append({"url": url, "headers": headers, "dados": dados})
        if url.endswith("/status"):
            return 200, _json.dumps({"connected": conectado,
                                     "smartphoneConnected": celular}).encode()
        if url.endswith("/send-text"):
            if ao_enviar is not None:
                ao_enviar()
            corpo = envio_corpo if envio_corpo is not None else {
                "zaapId": "3999984263738042930CD6ECDE9VDWSA",
                "messageId": "D241XXXX732339502B68",
                "id": "D241XXXX732339502B68"}
            return envio_status, _json.dumps(corpo).encode()
        raise AssertionError(f"chamada inesperada: {url}")

    _http.chamadas = chamadas
    return _http
