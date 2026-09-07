# -*- coding: utf-8 -*-
"""O relógio do aviso de carga, dentro da API.

O QUE ESTES GUARDS PROTEGEM: uma thread que manda WhatsApp sozinha, de dez em
dez minutos, para o telefone de gente que não é usuária do sistema. O modo de
falha caro aqui não é ela parar — é ela mandar demais, ou mandar de
madrugada.
"""
from __future__ import annotations

import pytest

from api.rastreio import agendador

#: A FUNCAO DE VERDADE, capturada no import — antes de a fixture `autouse`
#: trocá-la pelo dublê. Sem isto, o teste que quer exercitar o gate real só
#: alcançaria o `lambda: False` da fixture, e provaria nada.
SOB_TESTE_REAL = agendador.sob_teste


@pytest.fixture(autouse=True)
def _limpo(monkeypatch):
    """Cada teste começa com o agendador não iniciado — ele é idempotente de
    propósito e o estado vaza entre testes.

    E COM O GATE DE PYTEST DESLIGADO, senão nenhum teste de arranque
    exercitaria coisa nenhuma: `iniciar()` sairia na primeira linha e todos
    passariam por vacuidade. Quem testa o gate o religa explicitamente — é o
    `test_sob_pytest_a_thread_NUNCA_sobe`.
    """
    monkeypatch.setattr(agendador, "_iniciado", False)
    monkeypatch.setattr(agendador, "sob_teste", lambda: False)


# --------------------------------------------------------------------------
# o arranque
# --------------------------------------------------------------------------
def test_sob_pytest_a_thread_NUNCA_sobe(monkeypatch):
    """O GUARD QUE VALE UMA MENSAGEM NO CELULAR DE UM CLIENTE.

    `TestClient` dispara o `startup`, o `startup` sobe esta thread, e na
    bancada de produção o WhatsApp está configurado de verdade — o gate de
    credencial não segura nada ali. Passados os 120 s de folga, uma suíte de
    35 minutos mandaria aviso REAL, de dez em dez minutos, para quem está
    esperando carga.

    Não é hipótese: em 06/09/2026 o log da API de produção registrou um
    `RuntimeError` de ciclo cuja causa era o `monkeypatch` de
    `test_o_ciclo_NUNCA_levanta` — a thread de uma rodada de TESTE, viva dentro
    do processo de teste, escrevendo no log da casa.

    Este teste religa o gate de propósito (a fixture o desliga para os demais).
    """
    # A FUNCAO DE VERDADE de volta no lugar: o gate que este teste exercita
    # tem de ser o que roda em producao, nao um dublê que devolve True.
    monkeypatch.setattr(agendador, "sob_teste", SOB_TESTE_REAL)
    subiu = []
    monkeypatch.setattr(agendador.threading, "Thread",
                        lambda **kw: subiu.append(kw) or _FakeThread())
    from api.whatsapp import cliente
    monkeypatch.setattr(cliente, "configurado", lambda qual=None: True)
    agendador.iniciar()
    assert subiu == [], "sob pytest a thread não pode subir"
    assert agendador._iniciado is False


def test_sob_teste_reconhece_a_rodada_de_verdade():
    """Sem dublê nenhum: este processo É pytest, então a função tem de dizer
    que sim. Um `sob_teste()` que devolvesse False aqui seria um gate que só
    funciona nos testes dele mesmo."""
    assert SOB_TESTE_REAL() is True


def test_o_gate_vale_FORA_de_um_teste_tambem(monkeypatch):
    """`PYTEST_CURRENT_TEST` só existe DURANTE um teste. Entre eles — na
    coleta, numa fixture de módulo que monta o `TestClient` uma vez para o
    arquivo inteiro — a variável não está lá, e é justamente aí que o
    `startup` costuma rodar.

    Por isso o gate pergunta primeiro por `sys.modules`: pytest importado é um
    fato do PROCESSO e não some entre os testes. Este guard remove a variável
    e exige que a resposta continue sendo sim."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert SOB_TESTE_REAL() is True


def test_sem_whatsapp_configurado_a_thread_NAO_sobe(monkeypatch):
    """Sem credencial não é falha, é instalação incompleta. Uma thread
    acordando de dez em dez minutos para redescobrir isso não ajuda ninguém."""
    subiu = []
    monkeypatch.setattr(agendador.threading, "Thread",
                        lambda **kw: subiu.append(kw) or _FakeThread())
    from api.whatsapp import cliente
    monkeypatch.setattr(cliente, "configurado", lambda qual=None: False)
    agendador.iniciar()
    assert subiu == []
    assert agendador._iniciado is False


def test_com_whatsapp_configurado_sobe_UMA_vez(monkeypatch):
    """Idempotente: o `startup` do FastAPI roda a cada reinício da API, e o
    AutoDeploy reinicia várias vezes por dia. Duas threads dobrariam a
    varredura."""
    subiu = []
    monkeypatch.setattr(agendador.threading, "Thread",
                        lambda **kw: subiu.append(kw) or _FakeThread())
    from api.whatsapp import cliente
    monkeypatch.setattr(cliente, "configurado", lambda qual=None: True)
    agendador.iniciar()
    agendador.iniciar()
    agendador.iniciar()
    assert len(subiu) == 1
    assert subiu[0]["daemon"] is True, "thread não-daemon segura o desligamento"
    assert subiu[0]["name"] == "rastreio-aviso"


def test_falha_ao_conferir_o_whatsapp_NAO_derruba_a_API(monkeypatch):
    """`iniciar()` roda dentro do `startup`. Uma exceção aqui faria a API
    inteira não subir — e sem API não há nem tela de erro para explicar."""
    from api.whatsapp import cliente

    def _explode(qual=None):
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(cliente, "configurado", _explode)
    agendador.iniciar()          # não levanta
    assert agendador._iniciado is False


# --------------------------------------------------------------------------
# o ciclo
# --------------------------------------------------------------------------
def test_o_ciclo_NUNCA_levanta(monkeypatch):
    """Thread que morre por exceção some do radar, e o sintoma dela é idêntico
    ao de 'não havia nada para avisar' — que é o estado que ela deveria
    distinguir."""
    from api.rastreio import aviso

    def _explode():
        raise RuntimeError("ERP fora do ar")

    monkeypatch.setattr(aviso, "rodar", _explode)
    assert agendador._um_ciclo() is None


def test_de_madrugada_o_laco_nao_varre(monkeypatch):
    """A janela já é aplicada no envio; isto é economia de ruído. Sem a
    checagem seriam seis varreduras por hora a noite inteira, cada uma
    terminando em recusa e enchendo o log de aviso que não é problema."""
    from api.whatsapp import config
    monkeypatch.setattr(config, "dentro_da_janela",
                        lambda *a, **k: False)
    assert agendador._fora_da_janela() is True
    monkeypatch.setattr(config, "dentro_da_janela", lambda *a, **k: True)
    assert agendador._fora_da_janela() is False


def test_janela_ilegivel_erra_para_o_lado_de_TENTAR(monkeypatch):
    """Quem recusa de verdade é o envio, com motivo escrito. Calar por não
    conseguir ler a configuração seria a quarta resposta — a que não pode
    existir."""
    from api.whatsapp import config

    def _explode(*a, **k):
        raise RuntimeError("config ilegivel")

    monkeypatch.setattr(config, "dentro_da_janela", _explode)
    assert agendador._fora_da_janela() is False


# --------------------------------------------------------------------------
# a cadência
# --------------------------------------------------------------------------
def test_o_ciclo_e_MENOR_que_o_intervalo_por_telefone():
    """O ciclo é a PRECISÃO da entrega, não a frequência do envio. Se ele
    igualasse ou passasse o intervalo de 60 min, a âncora de 12h38 voltaria a
    ser atendida na hora cheia — que é o defeito que tudo isto corrige."""
    from api.rastreio import assinatura
    assert agendador.CICLO_S < assinatura.INTERVALO_MIN * 60
    assert agendador.CICLO_S <= 180, (
        "o erro do ciclo NAO some: a ancora e o ultimo envio, entao cada "
        "mensagem sai no primeiro ponto da grade depois dos 60 min e ancora a "
        "seguinte ali — o horario de entrega anda para a frente o dia inteiro. "
        "Com 600s medimos mediana de 68 e 70 min contra os 60 prometidos em "
        "06/09/2026, com a entrega caminhando de 06:00 para 16:00")


def test_ha_folga_antes_do_primeiro_ciclo():
    """O AutoDeploy reinicia a API várias vezes por dia. Sem folga, cada
    reinício dispararia uma varredura no primeiro segundo, e um dia de deploys
    agitado viraria uma rajada."""
    assert agendador.ATRASO_INICIAL_S >= 60


class _FakeThread:
    def start(self):
        return None


def test_o_relogio_SOBREVIVE_ao_reinicio_da_API():
    """O AutoDeploy reinicia a API várias vezes por dia, e agora o relógio do
    aviso mora dentro dela. Se a cadência dependesse de estado em MEMÓRIA, cada
    deploy zeraria o intervalo e a pessoa receberia mensagem a cada reinício —
    em silêncio, porque nada erra.

    Ela não depende: a âncora é lida do BANCO a cada ciclo (`desde_min`, que
    `ativas()` calcula em SQL). Este guard prova que o módulo não guarda nada
    entre ciclos além do 'já iniciei' — qualquer estado novo aqui tem de passar
    por esta conversa.
    """
    import types
    guardado = {n: v for n, v in vars(agendador).items()
                if not n.startswith("__") and not callable(v)
                and not isinstance(v, (type, types.ModuleType))
                and n not in ("annotations", "log")}
    assert set(guardado) == {"CICLO_S", "ATRASO_INICIAL_S", "_iniciado"}, (
        "estado novo no agendador: ele morre a cada deploy. Se for cadência, "
        "tem de morar no banco — vide `assinatura.ativas().desde_min`. "
        "Achado: %s" % sorted(guardado))


def test_a_cadencia_e_decidida_no_BANCO_e_nao_no_agendador():
    """Quem decide se manda é o `desde_min` que vem do SQL, não um relógio do
    processo. É isso que faz a cadência sobreviver ao reinício."""
    from pathlib import Path
    fonte = Path(agendador.__file__).read_text(encoding="utf-8")
    assert "time.time()" not in fonte and "datetime" not in fonte, (
        "o agendador não deve ter relógio próprio: a âncora é do banco")
