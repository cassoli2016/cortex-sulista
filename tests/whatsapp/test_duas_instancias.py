"""Duas instâncias da Z-API: o número do dia a dia e o reserva.

O QUE ESTE ARQUIVO PROTEGE, em ordem de quanto custa errar:

1. **O freio é POR NÚMERO.** O limite conta destinatários distintos porque é
   esse o gatilho de banimento que a Z-API documenta — e a reputação é de cada
   linha telefônica. Um contador compartilhado erraria nas duas direções: 60
   envios pelo principal bloqueariam o reserva, que não fez nada; e ignorar a
   separação deixaria passar o dobro do limite achando que é um número só.

2. **Nada de troca automática.** Se o sistema disparasse pelo reserva sozinho
   quando o principal cai, queimaria o segundo número também — e ter reserva é
   justamente para não ficar sem nenhum. A escolha é de quem envia.

3. **A trilha diz por qual número saiu.** Com dois aparelhos, "de onde saiu
   essa mensagem?" é a primeira pergunta, e sem a coluna não há resposta.
"""
from __future__ import annotations

import json

import pytest

from api.whatsapp import cliente, envio, registro
from tests.whatsapp.conftest import gravar_config, http_falso

INSTANCIA2 = "77AA11BB22CC3344"
TOKEN2 = "99DD88EE77FF6655"


@pytest.fixture(autouse=True)
def trilha(esquema_pg, monkeypatch):
    monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
    return esquema_pg


@pytest.fixture
def com_reserva(monkeypatch):
    """Acrescenta a segunda instância ao cofre falso do conftest."""
    from tests.whatsapp.conftest import CLIENT_TOKEN, INSTANCIA, TOKEN
    monkeypatch.setattr(cliente, "_cred", lambda nome: {
        "ZAPI_INSTANCIA": INSTANCIA, "ZAPI_TOKEN": TOKEN,
        "ZAPI_CLIENT_TOKEN": CLIENT_TOKEN,
        "ZAPI2_INSTANCIA": INSTANCIA2, "ZAPI2_TOKEN": TOKEN2,
        "ZAPI2_CLIENT_TOKEN": "",
    }.get(nome, ""))
    cliente.limpar_cache()
    yield
    cliente.limpar_cache()


# ------------------------------------------------------------- configuração

def test_sem_a_segunda_credencial_so_existe_a_principal():
    """Quem não tem reserva não pode ver a tela oferecer um."""
    assert cliente.instancias_configuradas() == ["principal"]
    assert cliente.configurado("backup") is False


def test_com_a_segunda_credencial_as_duas_aparecem(com_reserva):
    assert cliente.instancias_configuradas() == ["principal", "backup"]


def test_cada_instancia_monta_a_propria_url(com_reserva):
    from tests.whatsapp.conftest import INSTANCIA, TOKEN
    assert cliente._base("principal") == \
        f"https://api.z-api.io/instances/{INSTANCIA}/token/{TOKEN}"
    assert cliente._base("backup") == \
        f"https://api.z-api.io/instances/{INSTANCIA2}/token/{TOKEN2}"


def test_nome_de_instancia_desconhecido_cai_na_principal():
    """Vem de HTTP: recusar com exceção faria um parâmetro errado virar 500 no
    meio de um envio."""
    for lixo in ("", None, "terceira", "BACKUP  "):
        assert cliente.qual_valida(lixo) in ("principal", "backup")
    assert cliente.qual_valida("terceira") == "principal"
    assert cliente.qual_valida("BACKUP") == "backup"       # caixa não importa


def test_sanitizar_limpa_os_segredos_das_DUAS(com_reserva):
    """Limpar "só a da vez" é a brecha que ninguém revisaria: com dois pares, o
    mesmo texto passa por caminhos diferentes."""
    from tests.whatsapp.conftest import INSTANCIA, TOKEN
    sujo = f"falhou em {INSTANCIA}/{TOKEN} e em {INSTANCIA2}/{TOKEN2}"
    limpo = cliente._sanitizar(sujo)
    for segredo in (INSTANCIA, TOKEN, INSTANCIA2, TOKEN2):
        assert segredo not in limpo
    assert "***" in limpo


def test_cache_de_estado_e_por_instancia(com_reserva):
    """Com um cache só, perguntar pelo reserva devolveria o do principal
    durante os 60 s do TTL — e a tela mostraria um aparelho no lugar do outro."""
    http_ok = http_falso(conectado=True)
    http_fora = http_falso(conectado=False)
    assert cliente.estado(qual="principal", http=http_ok)["conectado"] is True
    assert cliente.estado(qual="backup", http=http_fora)["conectado"] is False
    # e o cache de cada uma continua valendo o seu
    assert cliente.estado(qual="principal", http=http_fora)["conectado"] is True


# -------------------------------------------------------------------- freio

def test_o_limite_de_um_numero_NAO_bloqueia_o_outro(com_reserva):
    """O ponto central do desenho. O WhatsApp não bane o reserva por causa do
    que o principal fez."""
    gravar_config(limite_dia=1)
    r1 = envio.enviar("47999998888", "oi", http=http_falso())
    assert r1["ok"] is True

    # a principal já bateu no teto
    r2 = envio.enviar("11988887777", "oi", http=http_falso())
    assert r2["ok"] is False and "Limite diário" in r2["erro"]

    # o reserva continua com a cota dele inteira
    r3 = envio.enviar("11988887777", "oi", instancia="backup", http=http_falso())
    assert r3["ok"] is True, r3["erro"]


def test_a_recusa_por_limite_diz_de_QUAL_numero(com_reserva):
    """Sem isso, quem lê acha que o sistema inteiro travou — quando o outro
    aparelho está livre."""
    gravar_config(limite_dia=1)
    envio.enviar("47999998888", "oi", instancia="backup", http=http_falso())
    r = envio.enviar("11988887777", "oi", instancia="backup", http=http_falso())
    assert r["ok"] is False
    assert "reserva" in r["erro"].lower()


def test_conversa_aberta_num_numero_nao_abre_conversa_no_outro(com_reserva):
    """Para o cliente, o reserva é um número desconhecido — exatamente o caso
    que o freio existe para conter."""
    gravar_config(limite_dia=1)
    envio.enviar("47999998888", "oi", http=http_falso())
    assert registro.ja_falou_hoje("5547999998888", instancia="principal") is True
    assert registro.ja_falou_hoje("5547999998888", instancia="backup") is False


def test_contador_do_dia_e_separado(com_reserva):
    gravar_config()
    envio.enviar("47999998888", "oi", http=http_falso())
    envio.enviar("11988887777", "oi", instancia="backup", http=http_falso())
    envio.enviar("11955554444", "oi", instancia="backup", http=http_falso())
    assert registro.contar_destinatarios_hoje(instancia="principal") == 1
    assert registro.contar_destinatarios_hoje(instancia="backup") == 2
    assert registro.resumo()["hoje_por_instancia"] == {"principal": 1, "backup": 2}


# -------------------------------------------------------------------- envio

def test_o_envio_pelo_reserva_usa_a_URL_do_reserva(com_reserva):
    gravar_config()
    http = http_falso()
    r = envio.enviar("47999998888", "oi", instancia="backup", http=http)
    assert r["ok"] is True
    assert INSTANCIA2 in http.chamadas[-1]["url"]
    assert TOKEN2 in http.chamadas[-1]["url"]


def test_a_trilha_grava_por_qual_numero_saiu(com_reserva):
    gravar_config()
    envio.enviar("47999998888", "oi", instancia="backup", http=http_falso())
    assert registro.listar(1)[0]["instancia"] == "backup"


def test_envio_sem_escolher_vai_pela_principal(com_reserva):
    gravar_config()
    envio.enviar("47999998888", "oi", http=http_falso())
    assert registro.listar(1)[0]["instancia"] == "principal"


def test_reserva_desconectado_NAO_faz_o_envio_cair_na_principal(com_reserva):
    """Não existe troca automática, de propósito: disparar pelo outro número
    sem ninguém mandar queimaria os dois."""
    gravar_config()
    http = http_falso(conectado=False)
    r = envio.enviar("47999998888", "oi", instancia="backup", http=http)
    assert r["ok"] is False
    assert "reserva" in r["erro"].lower()
    # nada foi enviado por ninguém
    assert not [c for c in http.chamadas if c["url"].endswith("/send-text")]


def test_reserva_nao_configurado_recusa_dizendo_qual():
    """Sem a segunda credencial, pedir o reserva não pode virar envio pela
    principal — seria mandar pelo número errado sem avisar."""
    gravar_config()
    r = envio.enviar("47999998888", "oi", instancia="backup", http=http_falso())
    assert r["ok"] is False
    assert "não configurado" in r["erro"] and "reserva" in r["erro"].lower()


def test_modelo_tambem_respeita_a_instancia_escolhida(com_reserva):
    from api.whatsapp import modelos as md
    md.ESQUEMA = registro.ESQUEMA
    gravar_config()
    m = md.gravar({"nome": "Aviso", "contexto": "livre", "corpo": "Bom dia."},
                  usuario="ana")
    http = http_falso()
    r = envio.enviar_modelo("47999998888", m["chave"], {}, instancia="backup",
                            http=http)
    assert r["ok"] is True, r["erro"]
    linha = registro.listar(1)[0]
    assert linha["instancia"] == "backup" and linha["modelo"] == m["chave"]
    md.ESQUEMA = None


def test_erro_de_credencial_diz_de_qual_instancia(com_reserva):
    """Com dois pares, "a Z-API recusou as credenciais" sem dizer qual manda
    conferir o par errado."""
    def _http(url, headers, timeout, dados=None):
        return 401, json.dumps({"error": "unauthorized"}).encode()

    d = cliente.estado(force=True, qual="backup", http=_http)
    assert d["conectado"] is False
    assert "reserva" in d["erro"].lower()
