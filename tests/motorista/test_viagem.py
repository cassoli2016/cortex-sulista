# -*- coding: utf-8 -*-
"""Minha viagem — o escopo, e o que a consulta NÃO tem.

O GUARD PRINCIPAL DESTE ARQUIVO É SOBRE UMA AUSÊNCIA, e por isso ele precisa
existir: `queries.TORRE_TRANSITO_SQL` lê a MESMA viagem e devolve `valorfrete`
e `km`. A consulta do app não devolve — e não porque alguém se lembre de
remover na hora de montar o payload, mas porque a coluna não está no `SELECT`.

Um teste sobre o TEXTO da consulta é exceção na casa (teste afirma
comportamento, não implementação). Aqui ele se justifica porque o
comportamento que se quer garantir é justamente que uma coluna NUNCA apareça:
testar o payload provaria só que ela não veio NESTA linha, e no dia em que
alguém copiasse a query da torre para "reaproveitar", o payload teria a coluna
e nenhum teste ficaria vermelho.
"""
from __future__ import annotations

import pytest

from api import queries
from api.motorista import viagem as mviagem

#: O que não pode estar na consulta do motorista. Cada uma dessas está na
#: consulta da TORRE, que lê a mesma viagem — é de lá que elas viriam.
PROIBIDAS = ("valorfrete", "kmfretecompra", "custo", "margem", "tabelafrete")


@pytest.fixture(autouse=True)
def cache_limpo():
    """O `cached` guarda por (módulo, função, args): sem limpar, o segundo
    teste leria a resposta do primeiro e mediria o cache, não o código."""
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


def test_a_consulta_nao_tem_dinheiro_dentro():
    sql = mviagem.VIAGEM_SQL.lower()
    for proibida in PROIBIDAS:
        assert proibida not in sql, (
            f"`{proibida}` entrou na consulta do app do motorista — "
            "o leitor vê a viagem dele, não o resultado dela")


def test_a_consulta_da_torre_TEM_o_que_esta_proibido_aqui():
    """Sabotagem ao contrário: prova que a lista de proibidas não é uma lista
    de palavras que não existem em lugar nenhum. Verde que nunca ficaria
    vermelho não conferiu nada."""
    torre = queries.TORRE_TRANSITO_SQL.lower()
    assert "valorfrete" in torre and "kmfretecompra" in torre


def test_o_escopo_vem_da_SESSAO_e_nao_do_pedido(monkeypatch):
    """Não há parâmetro de motorista em `minha()`. Se houvesse, a rota poderia
    preenchê-lo com o que veio do navegador, e o app viraria um buscador da
    operação alheia."""
    vistos = []
    monkeypatch.setattr(mviagem, "_consultar",
                        lambda cod: vistos.append(cod) or {"viagem": None})

    mviagem.minha({"motorista_codigo": "MOT-1", "nome": "João"})
    assert vistos == ["MOT-1"]

    import inspect
    assinatura = inspect.signature(mviagem.minha)
    assert list(assinatura.parameters) == ["sessao"], (
        "parâmetro a mais aqui é por onde o escopo deixa de vir da sessão")


def test_a_janela_de_viagem_em_curso_e_finita():
    """Viagem aberta há meses não é 'a sua viagem de hoje' — é fechamento que
    ninguém fez, e mostrá-la seria informação errada com cara de certa."""
    assert 0 < mviagem.DIAS_EM_CURSO <= 60
    assert "%(dias)s" in mviagem.VIAGEM_SQL


def test_o_cast_do_motorista_esta_na_consulta():
    """`programacaoembarque.motorista` é `character varying` HOJE. O cast custa
    0,07 s (medido: 0,143 s contra 0,069 s, mediana de 10) e paga por a tela
    não morrer no `operator does not exist` no dia em que o ERP recriar a
    tabela com outro tipo — que foi o que matou cinco telas em 02/09/2026."""
    assert "cast(p.motorista AS text)" in mviagem.VIAGEM_SQL


# --------------------------------------------------------- a serialização

class _CursorFalso:
    def __init__(self, linha):
        self._linha = linha

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        return None

    def fetchone(self):
        return self._linha


class _ConnFalsa:
    def __init__(self, linha):
        self._linha = linha

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _CursorFalso(self._linha)


def _com_linha(monkeypatch, linha):
    monkeypatch.setattr(mviagem.db, "get_conn", lambda: _ConnFalsa(linha))


LINHA = {
    # `numero` vem INTEIRO do ERP, e Decimal/date estouram no `render()` do
    # JSONResponse — DEPOIS do try/except da rota, virando 500 em text/plain
    # sem pista nenhuma. A conversão é no LIMITE do módulo.
    "numero": 178010, "placa": "NYP3J22", "carreta1": "JOK3011", "carreta2": "",
    "cliente": "CLIENTE X", "cidade_origem": "CRUZEIRO", "uf_origem": "SP",
    "cidade_destino": "SETE LAGOAS", "uf_destino": "MG",
    "saida": "2026-09-05 22:47", "previsao_chegada": "2026-09-08 06:00",
    "vazio": False,
}


def test_payload_e_montado_por_lista_explicita(monkeypatch):
    """Nunca uma cópia do registro do ERP: uma coluna nova do fornecedor
    viraria vazamento sozinha, sem ninguém rever nada."""
    _com_linha(monkeypatch, {**LINHA, "valorfrete": 9999.0})
    v = mviagem._consultar("MOT-1")["viagem"]
    assert "valorfrete" not in v
    assert set(v) == {"numero", "placa", "carretas", "cliente", "origem",
                      "destino", "saida", "previsao_chegada", "vazio"}


def test_numero_sai_como_texto_e_a_carreta_vazia_nao_entra(monkeypatch):
    _com_linha(monkeypatch, LINHA)
    v = mviagem._consultar("MOT-1")["viagem"]
    assert v["numero"] == "178010" and isinstance(v["numero"], str)
    assert v["carretas"] == ["JOK3011"]
    assert v["origem"] == "CRUZEIRO/SP" and v["destino"] == "SETE LAGOAS/MG"


def test_sem_viagem_devolve_None_e_nao_estoura(monkeypatch):
    _com_linha(monkeypatch, None)
    assert mviagem._consultar("MOT-1") == {"viagem": None}


def test_cidade_sem_uf_nao_vira_barra_solta():
    assert mviagem._cidade("JOINVILLE", "") == "JOINVILLE"
    assert mviagem._cidade("", "SC") == "SC"
    assert mviagem._cidade("", "") == ""


# ------------------------------------------------- a rede da leitura velha

def test_a_janela_e_a_DA_CASA_e_nao_uma_escolhida_aqui():
    """A janela era 6 h neste arquivo, escolhida sozinha antes de a casa ter
    uma. Uma viagem pode começar e terminar dentro de seis horas — e duas
    janelas diferentes para a mesma rede é como uma delas envelhece sem que
    ninguém perceba que envelheceu."""
    import inspect
    fonte = inspect.getsource(mviagem)
    assert "@cached(ttl=60, velha_ate=VELHA_ATE)" in fonte
    assert queries.VELHA_ATE == 2 * 3600


def test_minha_viagem_NAO_e_tela_de_tempo_real_e_isso_esta_escrito():
    """O critério de quem pode receber a rede é a RESOLUÇÃO da tela, não o
    grupo do menu (`tests/test_leitura_velha.py::TEMPO_REAL`).

    Esta tela publica a IDENTIDADE de uma viagem — cliente, origem, destino,
    placa, saída, previsão —, que muda quando uma viagem começa ou termina, não
    de minuto em minuto. No dia em que ela passar a publicar POSIÇÃO ("onde
    estou agora"), a rede tem de sair junto, e este teste é o lembrete de que a
    decisão foi tomada e por quê.
    """
    import inspect
    fonte = inspect.getsource(mviagem)
    for proibida in ("latitude", "longitude", "posicao", "ultima_posicao"):
        assert proibida not in fonte.lower(), (
            f"`{proibida}` entrou: se a tela passou a publicar posição, ela "
            "virou tela de tempo real e não pode servir leitura velha")
