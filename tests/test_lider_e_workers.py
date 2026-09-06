"""Com varios processos, SO UM roda os agendadores — e os pools cabem no banco.

O QUE ESTE ARQUIVO IMPEDE, medido nesta bancada em 06/09/2026 com um app
isolado e `--workers 4`:

    volta 1: o startup rodou 4 vezes
    volta 2: o startup rodou 6 vezes  (dois workers morreram com WinError 10022
                                       e o uvicorn respawnou)
    volta 3: o startup rodou 4 vezes

O `@app.on_event("startup")` roda em CADA worker. Um deles sobe o relogio do
aviso de carga, que manda WhatsApp REAL para quem esta esperando carga: com
quatro workers, quatro mensagens iguais para o mesmo cliente. E os pools sao
por processo — 4 x 20 = 80 conexoes contra o `max_connections=100` do
PostgreSQL local, que num boot com respawn viraria 120.

Nada disso aparece com um processo so, que e como a producao roda hoje. Por
isso o guard: o dia em que alguem ligar `--workers` nao pode ser o dia em que
o cliente recebe quatro mensagens.
"""
from __future__ import annotations

import multiprocessing
import os

import pytest

from api import lider, processos


# ------------------------------------------------------- dimensionamento

def test_um_processo_usa_o_pool_inteiro(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    assert processos.workers() == 1
    assert processos.fatia_do_pool(20) == 20
    assert processos.fatia_do_pool(16) == 16


def test_o_pool_e_dividido_entre_os_processos(monkeypatch):
    """4 x 20 = 80 contra um teto de 100 com 9 em uso: nao cabe."""
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    assert processos.workers() == 4
    assert processos.fatia_do_pool(20) < 20, "nao dividiu"
    assert processos.fatia_do_pool(20) * 4 + 9 <= 100, "estoura o max_connections"


@pytest.mark.parametrize("quantos", [1, 2, 4, 8, 16])
def test_o_pool_nunca_fica_menor_que_o_maior_leque(monkeypatch, quantos):
    """O PISO NAO E CONFORTO. A Visao Geral abre 5 conexoes de uma vez, todas
    do MESMO processo: um pool menor que isso faz uma requisicao sozinha
    esperar por si mesma ate o `timeout` — o `PoolTimeout` de 04/09/2026.

    Foi exatamente isto que o `test_o_pool_cabe_o_maior_leque_da_casa` pegou:
    o piso tinha nascido 4, abaixo do leque de 5.
    """
    monkeypatch.setenv("WEB_CONCURRENCY", str(quantos))
    for total in (16, 20):
        assert processos.fatia_do_pool(total) > processos.LEQUE_MAXIMO


def test_valor_invalido_nao_derruba_a_aplicacao(monkeypatch):
    for lixo in ("", "abc", "0", "-3"):
        monkeypatch.setenv("WEB_CONCURRENCY", lixo)
        assert processos.workers() == 1, f"{lixo!r} devia cair no padrao"


# ------------------------------------------------------------- a eleicao

def _candidato(fila, esquema_env):
    """Roda em processo SEPARADO: e a unica forma de provar a exclusao, porque
    a trava do PostgreSQL e por SESSAO e uma thread compartilharia a conexao."""
    import os as _os
    _os.environ.pop("PYTEST_CURRENT_TEST", None)
    import sys as _sys
    _sys.modules.pop("pytest", None)          # o gate de teste barraria todos
    for k, v in esquema_env.items():
        _os.environ[k] = v
    from api import lider as _l
    fila.put((_os.getpid(), _l.sou_o_agendador()))
    if _l._CONEXAO is not None:
        import time as _t
        _t.sleep(2)                            # segura a lideranca
        _l.largar()


@pytest.mark.parametrize("quantos", [4, 6])
def test_so_um_processo_vira_o_agendador(pg_disponivel, quantos):
    """4 workers e o caso de 6 (o boot ruim com respawn, medido de verdade)."""
    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    env = {k: v for k, v in os.environ.items() if k.startswith("CORTEX_PG_")}
    fila = multiprocessing.Queue()
    procs = [multiprocessing.Process(target=_candidato, args=(fila, env))
             for _ in range(quantos)]
    for p in procs:
        p.start()
    respostas = [fila.get(timeout=40) for _ in range(quantos)]
    for p in procs:
        p.join(timeout=40)
    lideres = [pid for pid, venceu in respostas if venceu]
    assert len(lideres) == 1, (
        f"{len(lideres)} lideres entre {quantos} processos — "
        "cada um subiria o relogio do aviso de carga")


def test_a_lideranca_e_liberada_quando_o_processo_morre(pg_disponivel):
    """Sem isto, um worker que caísse levaria a liderança para o túmulo e
    NENHUM aviso sairia — a falha oposta, e igualmente muda."""
    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    env = {k: v for k, v in os.environ.items() if k.startswith("CORTEX_PG_")}
    fila = multiprocessing.Queue()
    primeiro = multiprocessing.Process(target=_candidato, args=(fila, env))
    primeiro.start()
    pid1, venceu1 = fila.get(timeout=40)
    assert venceu1, "o primeiro tinha de vencer sozinho"
    primeiro.join(timeout=40)                 # morre e solta a trava

    segundo = multiprocessing.Process(target=_candidato, args=(fila, env))
    segundo.start()
    pid2, venceu2 = fila.get(timeout=40)
    segundo.join(timeout=40)
    assert venceu2, "a lideranca ficou presa depois que o lider morreu"
    assert pid1 != pid2


def test_sob_teste_ninguem_e_lider():
    """A suite NAO pode virar agendadora: e o mesmo caminho pelo qual ela quase
    mandou WhatsApp real em 06/09/2026 (ver `api/sob_teste.py`)."""
    assert lider.sou_o_agendador() is False
    assert lider._CONEXAO is None


def test_sem_banco_um_processo_ainda_agenda(monkeypatch):
    """Instalacao sem banco local hoje LIGA os agendadores. Negar por causa da
    eleicao seria regressao silenciosa — mas so vale com UM processo."""
    def sem_banco(*a, **kw):
        raise RuntimeError("banco fora do ar")
    monkeypatch.setattr(lider.psycopg, "connect", sem_banco)
    monkeypatch.setattr(lider, "sob_teste", lambda: False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    assert lider.sou_o_agendador() is True

    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    assert lider.sou_o_agendador() is False, (
        "com varios processos e sem eleicao possivel, deixar todos passarem e "
        "exatamente o defeito que este modulo existe para impedir")


# ------------------------------------- a fiacao: o main.py USA a eleicao?

def test_o_relogio_do_aviso_de_carga_so_sobe_no_lider(monkeypatch):
    """Os testes acima provam que a ELEICAO funciona. Este prova que ela esta
    LIGADA — sem ele, apagar a linha do `main.py` passaria despercebido, e o
    defeito so apareceria no celular do cliente."""
    from api import main
    subiu = []
    from api.rastreio import agendador
    monkeypatch.setattr(agendador, "iniciar", lambda: subiu.append(1))

    monkeypatch.setattr(main.lider, "sou_o_agendador", lambda: False)
    main._startup_aviso_carga()
    assert subiu == [], "subiu o relogio num processo que NAO e o lider"

    monkeypatch.setattr(main.lider, "sou_o_agendador", lambda: True)
    main._startup_aviso_carga()
    assert subiu == [1], "o lider tem de subir o relogio"


def test_o_digest_do_push_so_sobe_no_lider(monkeypatch):
    from api import main
    subiu = []
    monkeypatch.setattr(main.push, "iniciar_scheduler", lambda: subiu.append(1))

    monkeypatch.setattr(main.lider, "sou_o_agendador", lambda: False)
    main._startup_push()
    assert subiu == []

    monkeypatch.setattr(main.lider, "sou_o_agendador", lambda: True)
    main._startup_push()
    assert subiu == [1]


def test_o_pool_do_banco_da_casa_respeita_o_numero_de_processos(pg_disponivel, monkeypatch):
    """Prova que o `pglocal` USA o dimensionamento, e nao so que a conta existe."""
    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    from api import pglocal
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    pglocal.fechar_pool()
    try:
        p = pglocal._get_pool()
        assert p.max_size == processos.fatia_do_pool(20), "o pool ignorou a divisao"
        assert p.max_size < 20, "com 4 workers nao pode ficar nos 20 de um processo so"
        assert p.max_size > processos.LEQUE_MAXIMO, "menor que o leque da Visao Geral"
    finally:
        pglocal.fechar_pool()
