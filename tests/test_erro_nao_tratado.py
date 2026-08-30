"""Exceção que escapa de tudo tem de VIRAR JSON e IR PARA O LOG.

O QUE ISTO CONSERTA (Premiação em 500 por quase dois dias, 30/08/2026)
=====================================================================
Sem handler, exceção não tratada vira o `Internal Server Error` do Starlette:
**500 em `text/plain`**, sem corpo útil. E o traceback ia só para o stdout do
uvicorn — que aqui roda por TAREFA AGENDADA do Windows, cujo stdout não vai a
lugar nenhum. Resultado: a tela dizia "resposta em formato inesperado" e não
havia onde olhar.

Custou três rodadas de tentativa e erro descobrindo QUAL rota falhava. O
`Decimal` encontrado no caminho era real, mas o erro continuou depois de
corrigido — e não havia como saber por quê.

O QUE NÃO PODE VAZAR
====================
`str(exc)` NÃO vai na resposta. É a lição da Z-API: mensagem de exceção
carrega credencial (lá, a URL inteira com o token), e esta resposta vai para o
navegador. O TIPO basta para saber onde olhar; o resto fica no log.
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from api import auth
from api.main import JSONResponse, app

SEGREDO = "token-secreto-que-nao-pode-vazar"


@pytest.fixture(scope="module")
def cliente():
    @app.get("/api/_t_excecao")
    def _excecao():                                   # noqa: ANN202
        raise RuntimeError(SEGREDO)

    @app.get("/api/_t_render")
    def _render():                                    # noqa: ANN202
        class NaoSerializa:
            pass
        # o caso REAL: a rota devolve certo e o estouro acontece no `render()`,
        # depois de todo try/except dela
        return JSONResponse({"x": NaoSerializa()})

    auth._PUBLICAS = tuple(list(getattr(auth, "_PUBLICAS", ()))
                           + ["/api/_t_excecao", "/api/_t_render"])
    return TestClient(app, raise_server_exceptions=False)


def test_excecao_vira_JSON_e_nao_text_plain(cliente):
    """`text/plain` é o que a tela não consegue ler: `respostaJSON()` cai no
    catch e mostra "formato inesperado", que não diz nada."""
    r = cliente.get("/api/_t_excecao")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["erro"] == "erro_interno"


def test_o_ESTOURO_NO_RENDER_tambem_e_capturado(cliente):
    """É o caso que causou o defeito: a rota devolve, o `render()` estoura
    DEPOIS do try/except dela."""
    r = cliente.get("/api/_t_render")
    assert r.status_code == 500
    assert r.json()["tipo"] == "TypeError"


def test_a_resposta_diz_o_TIPO_e_o_CAMINHO(cliente):
    """São os dois dados que cortam o diagnóstico pela metade: sem eles, a
    única saída é testar rota por rota — foi o que aconteceu."""
    d = cliente.get("/api/_t_excecao").json()
    assert d["tipo"] == "RuntimeError"
    assert d["caminho"] == "/api/_t_excecao"


def test_a_mensagem_da_excecao_NAO_VAZA(cliente):
    """A lição da Z-API: `str(exc)` carrega credencial, e esta resposta vai
    para o navegador, para o log do proxy e para qualquer print de tela."""
    assert SEGREDO not in cliente.get("/api/_t_excecao").text


def test_o_traceback_vai_para_o_LOG(cliente, caplog):
    """Sem isto o handler só trocaria um erro mudo por outro: o tipo diz onde
    olhar, o traceback diz o quê."""
    with caplog.at_level(logging.ERROR, logger="cortex.financeiro"):
        cliente.get("/api/_t_excecao")
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "erro nao tratado" in texto
    assert "/api/_t_excecao" in texto
    assert "Traceback" in texto, "sem o traceback, o log não resolve nada"
    # e o log É o lugar do segredo: ele fica no servidor, não no navegador
    assert SEGREDO in texto


def test_o_log_da_API_vai_para_ARQUIVO():
    """A API roda por tarefa agendada: sem handler de arquivo, todo
    `log.warning` deste projeto era escrito no vazio — e foi por isso que não
    houve onde olhar durante dois dias."""
    from pathlib import Path
    raiz = logging.getLogger()
    alvos = [getattr(h, "baseFilename", "") for h in raiz.handlers]
    assert any(str(Path(a).name) == "api.log" for a in alvos if a), \
        "o log da API não está indo para logs/api.log"
