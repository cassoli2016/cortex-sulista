"""A pagina do painel e comprimida UMA vez e revalidada com 304.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR, medido nesta bancada em
06/09/2026 contra a API em producao:

O `index.html` tem 2,5 MB. A rota `/` devolvia um `FileResponse`, e com isso
cada carregamento pagava duas contas:

1. O `GZipMiddleware` recomprimia o arquivo INTEIRO, no nivel 9, a cada
   requisicao — 206 ms contra 19,5 ms sem compressao. No processo unico do
   uvicorn isso e CPU exclusiva: 20 pessoas abrindo o painel juntas levaram
   3,46 s e saturaram 95% de UM nucleo, e `/api/health` (rota trivial, que nem
   toca no arquivo) foi de 60,5 ms para 169,9 ms no mesmo intervalo.

2. O navegador nunca conseguia revalidar. O `FileResponse` EMITE o `ETag`, mas
   quem implementa requisicao condicional no Starlette e o `StaticFiles` — a
   prova e que `/static/vendor/echarts.min.js` devolvia 304 e a pagina, com o
   MESMO ETag de volta em `If-None-Match`, devolvia 200 com 712 KB.

Os dois sao MUDOS: a pagina abre, o numero aparece, ninguem reclama enquanto
houver um usuario. Por isso o guard afirma o comportamento observavel — o
codigo da resposta e o corpo — e nao a forma da implementacao.
"""
from __future__ import annotations

import gzip
import time
from email.utils import formatdate
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import main

# TestClient FORA de `with`: assim o lifespan nao roda. As rotas aqui sao
# publicas e nao tocam em banco, e `_startup_auth` aplicaria migration no
# schema de PRODUCAO (ver memoria `testclient-aplica-migration-em-producao`).
cliente = TestClient(main.app)

ESTATICO = Path(main.STATIC)

PAGINAS = [
    ("/", ESTATICO / "index.html"),
    ("/rastreio", ESTATICO / "rastreio.html"),
    ("/r", ESTATICO / "rastreio.html"),
    ("/sw.js", ESTATICO / "sw.js"),
]


@pytest.fixture(autouse=True)
def _cache_limpo():
    """Cada teste comeca sem bytes guardados de outro."""
    main._PAGINAS.clear()
    yield
    main._PAGINAS.clear()


# --------------------------------------------------------------- revalidacao

@pytest.mark.parametrize("rota,arquivo", PAGINAS, ids=lambda v: str(v))
def test_navegador_que_ja_tem_a_pagina_recebe_304_vazio(rota, arquivo):
    """O F5. Era 200 com o corpo inteiro; tem de ser 304 sem corpo."""
    primeira = cliente.get(rota)
    assert primeira.status_code == 200
    etag = primeira.headers.get("etag")
    assert etag, f"{rota} sem ETag — o navegador nao tem como revalidar"

    segunda = cliente.get(rota, headers={"If-None-Match": etag})
    assert segunda.status_code == 304, (
        f"{rota} devolveu {segunda.status_code} com o proprio ETag de volta — "
        "e o defeito de 06/09/2026, em que todo F5 rebaixava a pagina inteira")
    assert segunda.content == b"", "304 nao leva corpo"


def test_304_tambem_pela_data_quando_o_navegador_manda_if_modified_since():
    r = cliente.get("/")
    depois = formatdate(time.time() + 60, usegmt=True)
    assert cliente.get("/", headers={"If-Modified-Since": depois}).status_code == 304
    # data ANTERIOR ao arquivo: o navegador esta desatualizado, manda o corpo
    antes = formatdate(ESTATICO.joinpath("index.html").stat().st_mtime - 60,
                       usegmt=True)
    assert cliente.get("/", headers={"If-Modified-Since": antes}).status_code == 200
    assert r.status_code == 200


def test_etag_marcado_como_fraco_pelo_cloudflare_tambem_da_304():
    """O Cloudflare devolve `W/"..."` quando mexe na compressao no caminho.
    Comparar com o `W/` junto nunca daria 304 em producao, que e onde importa.
    """
    etag = cliente.get("/").headers["etag"]
    assert cliente.get("/", headers={"If-None-Match": "W/" + etag}).status_code == 304


def test_etag_de_outra_versao_nao_da_304():
    """Sem isto o teste acima passaria com um `return 304` incondicional."""
    r = cliente.get("/", headers={"If-None-Match": '"nao-e-a-versao-em-disco"'})
    assert r.status_code == 200
    assert r.content


# -------------------------------------------------------------- compressao

def test_a_pagina_e_comprimida_uma_vez_so(monkeypatch):
    """O nucleo do achado: 20 carregamentos NAO custam 20 compressoes."""
    contador = {"n": 0}
    original = gzip.compress

    def contando(*a, **k):
        contador["n"] += 1
        return original(*a, **k)

    monkeypatch.setattr(gzip, "compress", contando)
    for _ in range(20):
        assert cliente.get("/").status_code == 200
    assert contador["n"] == 1, (
        f"comprimiu {contador['n']} vezes em 20 carregamentos — "
        "era exatamente isso que saturava um nucleo")


def test_o_corpo_comprimido_e_a_pagina_de_verdade():
    """Guarda contra gzip DUPLO: o `GZipMiddleware` tem de deixar passar a
    resposta que ja vem com `Content-Encoding`, e nao comprimir de novo."""
    r = cliente.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    # o httpx descomprime UMA vez; se houvesse duas camadas, sobrariam bytes
    # de gzip aqui em vez do HTML.
    assert r.content == ESTATICO.joinpath("index.html").read_bytes()


def test_quem_nao_aceita_gzip_recebe_o_arquivo_cru():
    r = cliente.get("/", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert "content-encoding" not in r.headers
    assert r.content == ESTATICO.joinpath("index.html").read_bytes()


def test_vary_accept_encoding_para_o_cache_nao_trocar_as_versoes():
    """Sem `Vary`, um cache no caminho serve o corpo comprimido para quem
    pediu cru — e a pagina chega como lixo binario."""
    assert "accept-encoding" in cliente.get("/").headers.get("vary", "").lower()


def test_a_pagina_continua_sendo_revalidada_sempre():
    """`no-cache` e deliberado: o painel muda toda semana. O que mudou foi o
    PRECO de revalidar (um cabecalho), nao a politica."""
    cc = cliente.get("/").headers.get("cache-control", "")
    assert "no-cache" in cc, cc


# ------------------------------------------- a chave e o arquivo, nao o boot

def test_editar_o_arquivo_invalida_os_bytes_guardados(tmp_path):
    """O AutoDeploy reinicia a API a cada deploy, mas o `index.html` e servido
    do DISCO e ja foi editado sem restart aqui. Se a chave fosse o processo, a
    pagina velha ficaria no ar ate alguem reiniciar — calada."""
    arq = tmp_path / "pagina.html"
    arq.write_text("<p>antes</p>", encoding="utf-8")
    primeiro = main._pagina(arq)

    # mtime com resolucao de segundo em alguns sistemas: garante a diferenca
    depois_de = arq.stat().st_mtime_ns
    while arq.stat().st_mtime_ns == depois_de:
        arq.write_text("<p>depois, bem maior</p>", encoding="utf-8")

    segundo = main._pagina(arq)
    assert segundo["etag"] != primeiro["etag"]
    assert gzip.decompress(segundo["gz"]) == b"<p>depois, bem maior</p>"


def test_o_etag_e_do_conteudo_e_nao_do_mtime(tmp_path):
    """`git checkout` mexe no mtime sem mudar um byte. Com ETag de mtime, todo
    deploy que nem toca na pagina reenviaria 712 KB para todo mundo."""
    arq = tmp_path / "pagina.html"
    arq.write_text("<p>mesmo conteudo</p>", encoding="utf-8")
    antes = main._pagina(arq)["etag"]

    import os
    os.utime(arq, (time.time() + 120, time.time() + 120))
    main._PAGINAS.clear()          # como se o processo tivesse reiniciado

    assert main._pagina(arq)["etag"] == antes
