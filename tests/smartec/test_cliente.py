"""O cliente da Smartec — as três armadilhas que custaram tempo de verdade.

Cada teste aqui existe porque o defeito correspondente ACONTECEU nesta bancada,
não porque parecia uma boa ideia testar.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from api.smartec import cliente


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setenv("SMARTEC_TOKEN", "TOKEN-DE-TESTE-123")
    # o cofre vence o ambiente; garante que o teste não dependa do arquivo real
    monkeypatch.setattr(cliente.credenciais, "ler",
                        lambda nome: "TOKEN-DE-TESTE-123"
                        if nome == "SMARTEC_TOKEN" else None)
    yield


def _resposta(payload, status=200):
    """Dublê de urlopen com o corpo REAL do fornecedor.

    Copiar o corpo real, campos "inúteis" inclusive, é regra da casa: foi um
    dublê otimista demais que deixou a suíte do WhatsApp verde com a produção
    quebrada.
    """
    class _R:
        def read(self):
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return _R()


def test_o_user_agent_vai_na_requisicao(monkeypatch):
    """SEM `User-Agent` a API devolve 403.

    O `curl` passa e o `urllib` não, porque o urllib se anuncia como
    `Python-urllib/3.13`. O sintoma é a mesma chamada funcionar no terminal e
    falhar no código — que manda procurar defeito no código.
    """
    visto = {}

    def _fake(req, timeout=None, context=None):
        visto["headers"] = dict(req.headers)
        return _resposta([])

    monkeypatch.setattr(cliente.urllib.request, "urlopen", _fake)
    cliente.chamar("veiculos")
    # urllib capitaliza os nomes de cabeçalho
    chaves = {k.lower(): v for k, v in visto["headers"].items()}
    assert chaves.get("User-agent".lower()), "sem User-Agent a Smartec dá 403"


def test_o_token_vai_no_CORPO_e_nao_em_cabecalho(monkeypatch):
    """A Smartec autentica pelo corpo. Mandar em header não autentica nada."""
    visto = {}

    def _fake(req, timeout=None, context=None):
        visto["body"] = json.loads(req.data.decode("utf-8"))
        return _resposta([])

    monkeypatch.setattr(cliente.urllib.request, "urlopen", _fake)
    cliente.chamar("multas", Renavam="123")
    assert visto["body"]["Token"] == "TOKEN-DE-TESTE-123"
    assert visto["body"]["Tipo"] == "MULTAS SNE DETRAN"
    assert visto["body"]["Renavam"] == "123"


def test_nenhum_dado_encontrado_e_VAZIO_e_nao_erro(monkeypatch):
    """`IdErro 2000` chega como HTTP 400 e significa AUSÊNCIA DE DADO.

    Foi assim que CIV, EMTU e RNTRC responderam nesta conta, que não usa esses
    produtos. Tratar como falha faria o painel acusar integração quebrada em
    três recursos perfeitos — a mesma família do `error` descritivo da Z-API.
    """
    corpo = json.dumps([{"IdErro": 2000, "Message": "NENHUM DADO ENCONTRADO"}])

    def _fake(req, timeout=None, context=None):
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {},
            io.BytesIO(corpo.encode("utf-8")))

    monkeypatch.setattr(cliente.urllib.request, "urlopen", _fake)
    assert cliente.chamar("licencas", Pagina="0") == []


def test_recusa_de_verdade_continua_sendo_recusa(monkeypatch):
    """Um IdErro que NÃO é o 2000 tem de subir, senão o vazio engole tudo."""
    corpo = json.dumps([{"IdErro": 1200, "Message": "RENAVAM INVÁLIDO"}])

    def _fake(req, timeout=None, context=None):
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {},
            io.BytesIO(corpo.encode("utf-8")))

    monkeypatch.setattr(cliente.urllib.request, "urlopen", _fake)
    with pytest.raises(cliente.SmartecRecusa) as e:
        cliente.chamar("multas", Renavam="x")
    assert "RENAVAM" in str(e.value)


def test_o_token_nunca_aparece_na_mensagem_de_erro(monkeypatch):
    """O token vai no corpo, e o corpo é a primeira coisa que se loga."""
    corpo = json.dumps([{"IdErro": 1, "Message":
                         "falhou com TOKEN-DE-TESTE-123 dentro"}])

    def _fake(req, timeout=None, context=None):
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {},
            io.BytesIO(corpo.encode("utf-8")))

    monkeypatch.setattr(cliente.urllib.request, "urlopen", _fake)
    with pytest.raises(cliente.SmartecErro) as e:
        cliente.chamar("multas", Renavam="x")
    assert "TOKEN-DE-TESTE-123" not in str(e.value)
    assert "***" in str(e.value)


def test_operacao_de_ESCRITA_e_recusada(monkeypatch):
    """Indicar condutor atinge o órgão autuador e o prontuário de uma pessoa.

    O conector é somente leitura, e a recusa é do CLIENTE — não depende de
    ninguém lembrar de não chamar.
    """
    chamou = {"n": 0}

    def _fake(req, timeout=None, context=None):
        chamou["n"] += 1
        return _resposta([])

    monkeypatch.setattr(cliente.urllib.request, "urlopen", _fake)
    for op in ("indicar_condutor", "excluir_indicacao", "cadastrar_veiculo"):
        with pytest.raises(cliente.SmartecRecusa):
            cliente.chamar(op)
    assert chamou["n"] == 0, "nenhuma escrita pode chegar à rede"


def test_paginar_entende_os_DOIS_envelopes(monkeypatch):
    """`Licencas` devolve HaMais como TEXTO ("NÃO") e `Antt` como BOOLEANO.

    Assumir um formato só faria metade dos recursos parar na primeira página,
    em silêncio e com número plausível.
    """
    paginas = [
        {"HaMais": "SIM", "Quantidade": 2, "Valores": [{"a": 1}, {"a": 2}]},
        {"HaMais": "NÃO", "Quantidade": 1, "Valores": [{"a": 3}]},
    ]
    seq = iter(paginas)
    monkeypatch.setattr(cliente.urllib.request, "urlopen",
                        lambda req, timeout=None, context=None:
                        _resposta(next(seq)))
    assert len(cliente.paginar("licencas")) == 3

    seq2 = iter([{"HaMais": False, "Contagem": 2, "Tabela": [{"b": 1}, {"b": 2}]}])
    monkeypatch.setattr(cliente.urllib.request, "urlopen",
                        lambda req, timeout=None, context=None:
                        _resposta(next(seq2)))
    assert len(cliente.paginar("antt", DataEmissao="01/01/2026")) == 2


def test_sem_token_e_instalacao_incompleta_nao_falha(monkeypatch):
    monkeypatch.setattr(cliente.credenciais, "ler", lambda nome: None)
    monkeypatch.delenv("SMARTEC_TOKEN", raising=False)
    assert cliente.configurado() is False
    with pytest.raises(cliente.SmartecNaoConfigurado):
        cliente.chamar("veiculos")
