"""O que sai do banco local tem de caber num JSON — e o teste RENDERIZA.

O DEFEITO QUE ISTO GUARDA (30/08/2026, tela de Premiação)
=========================================================
`prem_ocorrencia_classe.peso` é `numeric`, o psycopg devolve `Decimal`, e o
`json` da biblioteca padrão não serializa `Decimal`.

O que torna esse defeito traiçoeiro não é o tipo — é ONDE ele estoura:

    try:
        d = config.ler(comp)          # <- passa
    except Exception:
        ...
    d["ocorrencias"] = classificacao.listar()   # <- passa, Decimal entra aqui
    return JSONResponse(d)            # <- ESTOURA, e já saiu do try

`JSONResponse` só serializa quando o Starlette chama `render()`, DEPOIS do
`try/except` da rota. A exceção escapa do tratamento, o FastAPI devolve o
handler padrão e o que chega ao navegador é:

    HTTP 500 · text/plain — Resposta em formato inesperado.

Nenhuma pista apontando para `peso`, para a premiação ou para o banco. E pior:
a tela ficou 500 por quase um dia sem ninguém notar, porque ela mostrava os
números da carga anterior ao lado do aviso.

POR QUE O TESTE RENDERIZA, E NÃO SÓ CHAMA A FUNÇÃO
==================================================
Um teste que afirmasse `isinstance(l["peso"], float)` passaria — e continuaria
passando no dia em que alguém acrescentasse OUTRA coluna `numeric`. O que
reproduz o defeito é a serialização, então é ela que o teste faz.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from api import pglocal

pytestmark = pytest.mark.skipif(
    not pglocal.configurado(),
    reason="banco local não configurado — nada a serializar")


def _nao_serializaveis(obj, caminho="") -> list[str]:
    """Onde estão os valores que o `json` recusa. O CAMINHO importa: sem ele a
    mensagem diria só "tem Decimal em algum lugar" num payload de 18 KB."""
    fora = []
    if isinstance(obj, (str, int, float, bool, type(None))):
        return fora
    if isinstance(obj, dict):
        for k, v in obj.items():
            fora += _nao_serializaveis(v, f"{caminho}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            fora += _nao_serializaveis(v, f"{caminho}[{i}]")
    else:
        fora.append(f"{caminho} = {type(obj).__name__}({obj!r})")
    return fora


def _fontes():
    """As leituras que alimentam rota e viram JSON.

    Cada uma passa por uma tabela do banco local com coluna `numeric` ou
    `timestamp` — que são os dois tipos que o psycopg devolve fora do que o
    `json` aceita.
    """
    from api.gestao import acoes, atas
    from api.premiacao import classificacao, config
    return [
        # prem_ocorrencia_classe.peso -- o defeito de 30/08/2026
        ("premiação · classificação de ocorrências",
         lambda: classificacao.listar()),
        # prem_parametros.valor e prem_eixos.peso
        ("premiação · configuração da competência",
         lambda: config.ler("2026-08")),
        ("premiação · versões", lambda: config.versoes()),
        # ges_acoes.quanto
        ("gestão · ações", lambda: acoes.listar()),
        ("gestão · atas", lambda: atas.listar()),
    ]


@pytest.mark.parametrize("rotulo,ler", _fontes(),
                         ids=[r for r, _ in _fontes()])
def test_a_leitura_do_banco_local_vira_JSON(rotulo, ler):
    try:
        dados = ler()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"{rotulo} não pôde ser lido ({type(exc).__name__})")
    ruins = _nao_serializaveis(dados, rotulo)
    assert not ruins, (
        "valor que o JSON não aceita saindo do banco local: "
        + "; ".join(ruins[:5])
        + ". Converter no LIMITE DO MÓDULO (float(...) / .isoformat()), onde o "
          "tipo do banco para de importar — senão a exceção só aparece dentro "
          "do JSONResponse.render(), depois do try/except da rota, e vira um "
          "500 em text/plain que não aponta para lugar nenhum.")


def test_a_rota_da_premiacao_RENDERIZA():
    """A reprodução exata do defeito: é o `render()` que estourava.

    Chamar a função e olhar o tipo do campo não bastaria — passaria de novo no
    dia em que outra coluna `numeric` entrasse no payload.
    """
    from api.main import premiacao_config
    r = premiacao_config("2026-08")
    assert r.status_code == 200
    corpo = r.body            # `render()` já rodou aqui: é o que estourava
    assert len(corpo) > 100
    d = json.loads(corpo)
    assert "params" in d and "ocorrencias" in d


def test_o_detector_ACHA_um_Decimal_plantado():
    """Sem isto o teste acima poderia estar verde por não detectar nada.
    Teste que não pode falhar não é teste."""
    achados = _nao_serializaveis({"a": [{"peso": Decimal("1.5")}]}, "x")
    assert achados and "Decimal" in achados[0]
    assert not _nao_serializaveis({"a": [{"peso": 1.5}]}, "x")
