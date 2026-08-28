"""Envio POR MODELO — a porta que as outras áreas do sistema usam.

Tudo aqui existe por causa de uma frase: a mensagem sai com o número real da
empresa, para um cliente real. Um texto com `{{cliente}}` literal no lugar do
nome não é um defeito cosmético — é a Sulista mandando lixo para quem paga, e
o sistema reportando "enviado com sucesso".

A rede é DUPLA de propósito:

- `enviar_modelo` renderiza estrito e recusa antes de tocar em número nenhum;
- `enviar` recusa qualquer texto que AINDA tenha `{{...}}`, venha de onde vier.

A segunda parece redundante e não é: quem monta mensagem é código de área, e a
chamada errada de uma delas não pode virar mensagem no celular do cliente.
"""
from __future__ import annotations

import json

import pytest

from api.whatsapp import envio, modelos as md, registro
from tests.whatsapp.conftest import gravar_config, http_falso


@pytest.fixture(autouse=True)
def base(esquema_pg, monkeypatch):
    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(md, "ESQUEMA", esquema_pg)
    return esquema_pg


def _modelo(**troca) -> dict:
    base = {"nome": "Cobrança — 1º aviso", "contexto": "cobranca",
            "corpo": "Olá {{cliente}}, o título {{documento}} venceu em "
                     "{{vencimento}}."}
    base.update(troca)
    return md.gravar(base, usuario="ana@sulista")


VALORES = {"cliente": "TUPY", "documento": "123456", "vencimento": "15/08/2026"}


def _texto_enviado(http) -> str:
    return json.loads(http.chamadas[-1]["dados"])["message"]


# ------------------------------------------------------------------- sucesso

def test_texto_sai_montado_e_a_trilha_diz_de_qual_modelo_veio():
    gravar_config()
    m = _modelo()
    http = http_falso()
    r = envio.enviar_modelo("(47) 99999-8888", m["chave"], VALORES,
                            usuario="ana@sulista", http=http)
    assert r["ok"] is True, r["erro"]
    # pelo JSON, e não pelo texto cru: o corpo sai com os acentos escapados
    # (`\\u00e1`), e comparar a string bruta testaria a serialização
    assert _texto_enviado(http) == "Olá TUPY, o título 123456 venceu em 15/08/2026."

    linha = registro.listar(1)[0]
    assert linha["modelo"] == m["chave"]
    assert linha["origem"] == "modelo:" + m["chave"]


def test_mensagem_avulsa_continua_sem_modelo_na_trilha():
    """A coluna serve para separar o texto revisado do texto de improviso —
    marcar tudo tiraria a informação."""
    gravar_config()
    envio.enviar("47999998888", "Bom dia", http=http_falso())
    assert registro.listar(1)[0]["modelo"] == ""


# ------------------------------------------------------------------- recusas

def test_variavel_faltando_recusa_ANTES_de_falar_com_a_z_api():
    gravar_config()
    m = _modelo()
    http = http_falso()
    r = envio.enviar_modelo("47999998888", m["chave"],
                            {"cliente": "TUPY"}, http=http)
    assert r["ok"] is False
    assert "documento" in r["erro"] and "vencimento" in r["erro"]
    assert http.chamadas == []          # nada saiu


def test_recusa_por_chamada_errada_NAO_suja_a_trilha():
    """Nada foi tentado contra número nenhum. Uma linha por chamada errada de
    código encheria a trilha que existe para dizer o que saiu da empresa."""
    gravar_config()
    m = _modelo()
    envio.enviar_modelo("47999998888", m["chave"], {}, http=http_falso())
    envio.enviar_modelo("47999998888", "nao-existe", VALORES, http=http_falso())
    assert registro.listar(10) == []


def test_modelo_inexistente_diz_o_nome_procurado():
    gravar_config()
    r = envio.enviar_modelo("47999998888", "aviso-que-ninguem-criou", {},
                            http=http_falso())
    assert r["ok"] is False and "aviso-que-ninguem-criou" in r["erro"]


def test_modelo_desligado_nao_dispara():
    """Desligar é o jeito de aposentar um texto sem perder o histórico —
    se o envio ignorasse o interruptor, ele não serviria para nada."""
    gravar_config()
    m = _modelo(ativo=0)
    http = http_falso()
    r = envio.enviar_modelo("47999998888", m["chave"], VALORES, http=http)
    assert r["ok"] is False and "desligado" in r["erro"]
    assert http.chamadas == []


def test_texto_com_variavel_solta_e_recusado_mesmo_SEM_modelo():
    """A oitava recusa. Uma área que monte a mensagem por conta própria e
    esqueça de preencher não consegue mandar `{{cliente}}` para o cliente."""
    gravar_config()
    http = http_falso()
    r = envio.enviar("47999998888", "Olá {{cliente}}, tudo bem?", http=http)
    assert r["ok"] is False
    assert "{{cliente}}" in r["erro"]
    assert http.chamadas == []
    # esta recusa É gravada: houve uma tentativa contra um número de verdade
    assert registro.listar(1)[0]["erro"].startswith("A mensagem ainda tem")


def test_chave_de_format_no_texto_nao_e_confundida_com_variavel():
    """`{saldo}` e `{0}` são texto comum e têm de sair como estão — só `{{ }}`
    é variável."""
    gravar_config()
    http = http_falso()
    r = envio.enviar("47999998888", "Saldo {0} de {conta.saldo}", http=http)
    assert r["ok"] is True
    assert _texto_enviado(http) == "Saldo {0} de {conta.saldo}"


def test_varios_destinatarios_com_o_mesmo_modelo():
    gravar_config()
    m = _modelo()
    r = envio.enviar_modelo("(47) 99999-8888, 11 98888-7777", m["chave"],
                            VALORES, http=http_falso())
    assert r["enviados"] == 2 and r["falhas"] == 0
    assert {x["modelo"] for x in registro.listar(5)} == {m["chave"]}


def test_o_freio_do_dia_continua_valendo_para_modelo():
    """O modelo não é um caminho paralelo: passa pelas mesmas sete recusas.
    Um atalho mais frouxo seria justamente o jeito de perder o número."""
    gravar_config(limite_dia=1)
    m = _modelo()
    envio.enviar_modelo("47999998888", m["chave"], VALORES, http=http_falso())
    r = envio.enviar_modelo("11988887777", m["chave"], VALORES, http=http_falso())
    assert r["ok"] is False and "Limite diário" in r["erro"]
    # a recusa entrou na trilha COM a chave do modelo: é assim que se descobre
    # qual disparo bateu no teto
    assert registro.listar(1)[0]["modelo"] == m["chave"]
