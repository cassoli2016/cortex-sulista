"""O cartão do túnel ngrok na Saúde do Servidor.

O ngrok é a porta SECUNDÁRIA para a internet, ao lado do túnel Cloudflare. O
que este cartão existe para vigiar NÃO é "está no ar" — é se ela está no ar
COM PORTÃO, porque nessa porta o Cloudflare Access não se aplica: quem tiver a
URL chega no login do CÓRTEX sem passar por MFA nenhum.

Por isso os testes que importam aqui são os que provam que o alarme ACENDE.
Cartão que só sabe ficar verde é enfeite, e esta casa já pagou três vezes por
conferência que passava por vacuidade (o dublê otimista do WhatsApp, o teste
da Visão Geral que "não baixa a biblioteca" e o conferidor que lia campo
inexistente). Cada estado abaixo é sabotado de propósito.

Nada de rede: o cache é preenchido na mão, que é o mesmo ponto por onde
`_servico_ngrok` lê.
"""
from __future__ import annotations

import pytest

from api import servidor as sv

BASE = {"processos": 1, "portao": "usuário e senha",
        "url": "https://exemplo.ngrok-free.app", "inspetor": False}


@pytest.fixture(autouse=True)
def _limpa_cache():
    sv._ngrok_cache = None
    yield
    sv._ngrok_cache = None


def cartao(**kw) -> dict | None:
    """Injeta o estado no cache com um instante absurdo no futuro, para o TTL
    nunca expirar no meio do teste e disparar consulta de verdade."""
    sv._ngrok_cache = (9e9, {**BASE, **kw})
    return sv._servico_ngrok()


def test_no_ar_com_portao_e_sem_inspetor_fica_verde():
    c = cartao()
    assert c["status"] == "ok"
    assert "exemplo.ngrok-free.app" in c["detalhe"]
    assert "usuário e senha" in c["detalhe"]


def test_SEM_PORTAO_acende_alarme():
    """A razão de o cartão existir. Túnel publicado sem `basic_auth`/`oauth`
    deixa o CÓRTEX alcançável da internet com só o login do app na frente."""
    c = cartao(portao="")
    assert c["status"] == "alerta"
    assert "SEM PORTÃO" in c["detalhe"]
    # e diz POR QUE isso é diferente do túnel Cloudflare, senão quem lê não
    # tem como saber que ali não há MFA
    assert "Access" in c["detalhe"]


def test_tunel_no_ar_sem_config_lida_tambem_acende():
    """`portao=None` é "não consegui ler o ngrok.yml". Com o agente publicando,
    isso NÃO pode ser lido como seguro: na dúvida o alarme acende, que é errar
    para o lado de mostrar o risco."""
    assert cartao(portao=None)["status"] == "alerta"


def test_INSPETOR_ligado_acende_alarme():
    """`inspect` vem da API do agente, então aqui é medido e não declarado.
    Ligado, 127.0.0.1:4040 grava corpo de requisição e resposta — faturamento,
    PII de motorista e o cookie de sessão — numa tela sem senha nenhuma."""
    c = cartao(inspetor=True)
    assert c["status"] == "alerta"
    assert "4040" in c["detalhe"]


def test_oauth_tambem_vale_como_portao():
    assert cartao(portao="OAuth")["status"] == "ok"


def test_desligado_e_info_e_NUNCA_erro():
    """A porta é opcional e ficar fechada é o estado NORMAL dela — a mesma
    regra do WhatsApp reserva, pareado e parado. Vermelho aqui ensinaria a
    ignorar o vermelho."""
    c = cartao(processos=0)
    assert c["status"] == "info"
    assert "desligado" in c["detalhe"]


def test_sem_ngrok_nenhum_o_cartao_SOME():
    """Sem processo e sem config não há linha. Cartão que nunca muda ensina a
    pular o cartão, e junto com ele os que decidem algo — é a lição das 8 de 9
    linhas de base migrada que só diziam a mesma frase."""
    assert cartao(processos=0, portao=None) is None


def test_url_ainda_nao_publicada_nao_vira_string_vazia():
    """Agente subindo, sessão ainda não estabelecida: o detalhe tem de dizer
    isso, não deixar um buraco onde deveria haver URL."""
    c = cartao(url=None)
    assert "não publicada" in c["detalhe"]


def test_o_cartao_entra_na_lista_de_servicos(monkeypatch):
    """Sensor que não é montado não vigia nada. Este teste é o que quebra se
    alguém escrever a função e esquecer de acrescentá-la em `_servicos()`."""
    monkeypatch.setattr(sv, "_servico_ngrok",
                        lambda: {"nome": "Túnel ngrok (porta secundária)",
                                 "status": "alerta", "detalhe": "x"})
    nomes = [s["nome"] for s in sv._servicos()]
    assert "Túnel ngrok (porta secundária)" in nomes


def test_a_tarefa_agendada_do_ngrok_e_vigiada():
    """Tarefa que não aparece na Saúde é tarefa que pode morrer em silêncio —
    a coleta da Gobrax ficou cinco dias parada exatamente assim."""
    assert "Cortex Sulista - Ngrok" in sv._TAREFAS
