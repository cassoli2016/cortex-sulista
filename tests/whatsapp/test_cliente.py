"""O cliente HTTP da Z-API — e o vazamento que ele existe para impedir.

A Z-API é a única integração deste sistema em que **o segredo viaja dentro da
URL** (`/instances/{id}/token/{token}/send-text`). Em toda outra — Gobrax,
Monkey, Prolog — o token vai em cabeçalho, e registrar a URL no log era
inofensivo. Aqui a URL É a credencial.

Isso transforma um hábito comum em vazamento: `str(exc)` de `urllib` costuma
trazer a URL, e a mensagem de erro do envio vai para a tela, para o log e para
a trilha no banco. Os testes abaixo são o que impede isso de voltar.
"""
from __future__ import annotations

import urllib.error

import pytest

from api.whatsapp import cliente
from tests.whatsapp.conftest import CLIENT_TOKEN, INSTANCIA, TOKEN, http_falso


def test_a_url_realmente_carrega_o_token():
    """Se um dia a Z-API passar a autenticar por cabeçalho, este teste falha e
    avisa que os cuidados abaixo podem ser revistos. Enquanto ele passar, eles
    são obrigatórios."""
    url = cliente._base()
    assert TOKEN in url and INSTANCIA in url


def test_sanitizar_tira_os_tres_segredos():
    sujo = (f"falhou em https://api.z-api.io/instances/{INSTANCIA}"
            f"/token/{TOKEN}/send-text com Client-Token {CLIENT_TOKEN}")
    limpo = cliente._sanitizar(sujo)
    for segredo in (INSTANCIA, TOKEN, CLIENT_TOKEN):
        assert segredo not in limpo
    assert "***" in limpo


def test_erro_de_rede_nao_devolve_a_excecao_crua():
    """`urllib` levanta com a URL dentro. O cliente tem de traduzir para o
    nome da classe, nunca repassar `str(exc)` — este teste reproduz o caso
    real: a exceção do urllib traz a URL completa."""
    def explode(url, headers, timeout, dados=None):
        raise urllib.error.URLError(f"falha ao abrir {url}")

    with pytest.raises(cliente.ZapiIndisponivel) as exc:
        cliente.Cliente(http=explode).status()
    texto = str(exc.value)
    assert TOKEN not in texto
    assert INSTANCIA not in texto
    assert "URLError" in texto


def test_o_estado_tambem_nao_vaza_quando_da_erro():
    """`estado()` engole a exceção e devolve dicionário — o texto do erro vai
    para a tela de Saúde e para o formulário, então passa pelo mesmo filtro."""
    def explode(url, headers, timeout, dados=None):
        raise OSError(f"conexão recusada: {url}")

    d = cliente.estado(force=True, http=explode)
    assert d["ok"] is False and d["conectado"] is False
    assert TOKEN not in d["erro"] and INSTANCIA not in d["erro"]


def test_client_token_vai_no_cabecalho():
    http = http_falso()
    cliente.Cliente(http=http).status()
    assert http.chamadas[0]["headers"]["Client-Token"] == CLIENT_TOKEN


def test_null_not_allowed_vira_a_instrucao_de_onde_configurar(monkeypatch):
    """O erro mais comum da Z-API é também o mais críptico: quem ativa a
    validação por token no painel e não preenche aqui recebe
    `{"error": "null not allowed"}` — que não diz nada a ninguém."""
    monkeypatch.setattr(cliente, "_cred", lambda nome: {
        "ZAPI_INSTANCIA": INSTANCIA, "ZAPI_TOKEN": TOKEN}.get(nome, ""))
    msg = cliente._erro_legivel(401, {"error": "null not allowed"})
    assert "token de segurança da conta" in msg.lower()
    assert "Segurança" in msg


def test_credencial_recusada_explica_que_os_dois_campos_dao_o_mesmo_erro():
    """Na Z-API o id e o token formam o endereço: errar um dá exatamente o
    mesmo 401 que errar o outro. Dizer isso poupa a busca no campo errado."""
    msg = cliente._erro_legivel(403, {})
    assert "id da instância" in msg and "token da instância" in msg


def test_estado_usa_cache_e_nao_martela_a_zapi():
    """A Saúde do Servidor recarrega a cada 5 s. Sem cache seriam ~17 mil
    chamadas por dia à Z-API só para desenhar um cartão."""
    http = http_falso()
    for _ in range(5):
        cliente.estado(http=http)
    assert len(http.chamadas) == 1


def test_force_ignora_o_cache():
    """É o botão 'testar conexão': quem acabou de trocar a credencial não pode
    esperar um minuto para saber se funcionou."""
    http = http_falso()
    cliente.estado(http=http)
    cliente.estado(force=True, http=http)
    assert len(http.chamadas) == 2


def test_sem_credencial_o_cliente_nao_nasce(monkeypatch):
    monkeypatch.setattr(cliente, "_cred", lambda nome: "")
    with pytest.raises(cliente.ZapiNaoConfigurado):
        cliente.Cliente(http=http_falso())
