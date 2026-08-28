"""Rota lenta não pode parar o CÓRTEX inteiro.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR, medido nesta bancada:

O FastAPI roda rota `def` num threadpool e rota `async def` NO PRÓPRIO EVENT
LOOP. Como toda rota que recebe corpo precisa de `await req.json()`, elas
nascem `async def` — e aí um `urllib`/`psycopg`/`smtplib` dentro delas trava o
loop, ou seja, o SERVIDOR INTEIRO, pelo tempo da chamada.

Com a Z-API demorando 3 s, o `/api/health` — rota trivial e pública — levava
**5,7 s**. Em produção o envio chega a 30 s por destinatário (10 s de `/status`
mais 20 s de `/send-text`), e `enviar_varios` repete isso EM SÉRIE, um número
por vez: um disparo para cinco clientes deixava o painel fora do ar por
minutos, para todo mundo. O Cloudflare Tunnel, sem resposta da origem,
devolvia **502 Bad Gateway em HTML** — que a tela não conseguia nem ler como
JSON, e por isso o usuário via "erro interno da API" sem mais nada.

O teste sobe o uvicorn DE VERDADE, porque é a única forma de ver isso: o
`TestClient` serializa as chamadas e um event loop travado passa despercebido.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import uuid

import pytest

from api import auth, migracoes, pglocal
from api.whatsapp import cliente as zcli
from api.whatsapp import config as zcfg
from api.whatsapp import modelos as zmod
from api.whatsapp import registro as zreg

SENHA = "senha-de-teste-123"
DEMORA = 2.0          # cada ida à Z-API; a real chega a 20 s
TETO_HEALTH = 1.0     # o health é trivial: acima disso o loop está travado


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def servidor(esquema_pg, monkeypatch, tmp_path):
    """API real, no uvicorn, com a Z-API dublada para demorar."""
    httpx = pytest.importorskip("httpx")
    uvicorn = pytest.importorskip("uvicorn")

    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(zreg, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(zmod, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        p = c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()
        c.execute(
            """INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                    deve_trocar_senha, criado_em)
               VALUES('Chefe','chefe@sulista.com.br',%s,%s,1,0,%s)""",
            (auth._ph.hash(SENHA), p["id"], auth._agora()))

    monkeypatch.setattr(zcli, "_cred", lambda nome: {
        "ZAPI_INSTANCIA": "3D2F8A1C4B6E9077",
        "ZAPI_TOKEN": "A91B7C5D3E2F4088"}.get(nome, ""))
    monkeypatch.setattr(zcfg, "CAMINHO", tmp_path / "whatsapp_config.json")
    zcfg.gravar({"ativo": True, "limite_dia": 60, "intervalo_seg": 5,
                 "janela_inicio": "00:00", "janela_fim": "23:59",
                 "assinatura": ""})

    def _http_lento(url, headers, timeout, dados=None):
        time.sleep(DEMORA)                      # I/O de rede, BLOQUEANTE
        if url.endswith("/status"):
            return 200, json.dumps({
                "connected": True, "smartphoneConnected": True,
                "error": "You are already connected."}).encode()
        return 200, json.dumps({"zaapId": "Z", "messageId": "M", "id": "M"}).encode()

    monkeypatch.setattr(zcli, "_http", _http_lento)
    zcli.limpar_cache()

    from api.main import app
    porta = _porta_livre()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta,
                                        log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    base = f"http://127.0.0.1:{porta}"
    for _ in range(150):                        # espera subir
        try:
            httpx.get(base + "/api/health", timeout=1)
            break
        except Exception:                       # noqa: BLE001
            time.sleep(0.1)
    else:                                       # pragma: no cover
        srv.should_exit = True
        pytest.skip("uvicorn não subiu a tempo")

    yield base, httpx
    srv.should_exit = True
    time.sleep(0.3)
    zcli.limpar_cache()


def test_envio_lento_de_whatsapp_nao_para_o_resto_do_sistema(servidor):
    """O teste que o defeito relatado deixou.

    `/api/health` é pública, trivial e não toca banco. Se ela demora enquanto
    um envio está em curso, o event loop está bloqueado — e nesse estado o
    túnel devolve 502 para qualquer um que esteja usando o painel.
    """
    base, httpx = servidor
    cli = httpx.Client(base_url=base, timeout=120)
    assert cli.post("/api/auth/login", json={
        "email": "chefe@sulista.com.br", "senha": SENHA}).status_code == 200

    envio = {}

    def _enviar():
        r = cli.post("/api/gestao/whatsapp/enviar",
                     json={"telefones": "(47) 99999-8888", "mensagem": "Bom dia"})
        envio["status"] = r.status_code

    th = threading.Thread(target=_enviar)
    th.start()
    time.sleep(0.5)                              # deixa o envio começar

    piores = []
    for _ in range(3):
        ini = time.monotonic()
        assert httpx.get(base + "/api/health", timeout=60).status_code == 200
        piores.append(time.monotonic() - ini)
    th.join()

    assert envio["status"] == 200, envio
    pior = max(piores)
    assert pior < TETO_HEALTH, (
        f"/api/health levou {pior:.2f}s durante o envio — o event loop está "
        f"travado. Toda rota `async def` que faz I/O precisa passar por "
        f"`sem_travar()` (api/main.py).")


def test_recusa_de_envio_NAO_pode_ser_5xx(servidor):
    """O defeito que custou uma manhã inteira de investigação.

    "O envio está DESLIGADO em Gestão › WhatsApp" é o servidor funcionando e
    dizendo NÃO, com um motivo que a pessoa precisa LER. Isso é 4xx. Enquanto
    foi 502, **o Cloudflare trocava o corpo pela página de erro dele** e a
    mensagem nunca cruzava o túnel: a tela dizia "erro interno da API" durante
    horas enquanto o backend respondia certo e a trilha registrava a recusa.

    Medido: um 401 atravessa o túnel intacto (mesmo `content-type`, mesmo
    tamanho); um 502 chega sem JSON nenhum.
    """
    base, httpx = servidor
    from api.whatsapp import config as zcfg
    cli = httpx.Client(base_url=base, timeout=60)
    assert cli.post("/api/auth/login", json={
        "email": "chefe@sulista.com.br", "senha": SENHA}).status_code == 200

    zcfg.gravar({**zcfg.ler(), "ativo": False})     # o interruptor desligado
    r = cli.post("/api/gestao/whatsapp/enviar",
                 json={"telefones": "(47) 99999-8888", "mensagem": "Bom dia"})

    assert r.status_code < 500, (
        f"recusa devolveu {r.status_code}: um proxy tem licença para trocar o "
        f"corpo de 5xx, e a mensagem não chega a quem precisa lê-la")
    assert r.headers["content-type"].startswith("application/json")
    assert "DESLIGADO" in r.json()["mensagem"]
