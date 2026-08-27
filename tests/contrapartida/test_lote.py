# tests/contrapartida/test_lote.py
"""Emissao em lote — as guardas que so existem no caminho automatico.

Emitir a mao tem um humano lendo o retorno. Uma rotina que assina em nome de
terceiro milhares de vezes por mes nao tem, e os erros dela chegam
multiplicados. Cada teste aqui cobre uma dessas guardas.

Nenhum vai a rede nem ao banco: `db.query`, o cadastro e a transmissao entram
por substituicao.
"""
from __future__ import annotations

import dataclasses

import pytest

from api.contrapartida import lote
from tests.contrapartida.test_documento import ENQ

CHAVES = ["3526...A", "3526...B", "3526...C", "3526...D"]


def _linhas(n=4):
    return [{"chave": CHAVES[i], "dtemissao": "2026-08-20",
             "cnpj": "111", "nome": "AGREGADO", "valor": 100.0 * (i + 1)}
            for i in range(n)]


@pytest.fixture
def base(monkeypatch):
    """Banco com 4 CT-e, um agregado pronto, nada emitido ainda."""
    monkeypatch.setattr(lote.db, "query", lambda *a, **k: _linhas())
    monkeypatch.setattr(lote.cadastro, "mapa",
                        lambda: {"111": {"prontidao": {"pronto": True}}})
    monkeypatch.setattr(lote, "_ja_emitidas", lambda ambiente: set())
    monkeypatch.setattr(lote, "automacao_ativa", lambda: False)


# --- a chave da automacao ---------------------------------------------------

def test_automacao_nasce_DESLIGADA(monkeypatch):
    """Ausencia de registro significa desligado, nunca o contrario: um padrao
    ligado faria a rotina comecar a emitir por causa de um banco novo ou de
    uma restauracao de backup."""
    monkeypatch.setattr(lote, "_conn_config", lambda: _ConnVazia())
    assert lote.automacao_ativa() is False


class _ConnVazia:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a, **k): return _Cursor(None)


class _Cursor:
    def __init__(self, r): self._r = r
    def fetchone(self): return self._r


def test_desassistido_com_automacao_desligada_e_RECUSADO(base):
    """A rotina agendada nao roda se ninguem ligou."""
    with pytest.raises(PermissionError, match="DESLIGADA"):
        lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="rotina",
                            limite=5, desassistido=True)


def test_MANUAL_funciona_com_a_automacao_desligada(base):
    """O ponto do desenho: manual sempre; automatico so se alguem ligar."""
    r = lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="fulano",
                            limite=5, dry_run=True)
    assert r["fila"] == 4 and r["dry_run"] is True


def test_ligar_a_automacao_exige_autor():
    """E a decisao que define quem responde por um documento emitido as tres
    da manha."""
    with pytest.raises(ValueError, match="Informe quem"):
        lote.definir_automacao(True, "")


# --- idempotencia -----------------------------------------------------------

def test_chave_ja_AUTORIZADA_nao_volta_para_a_fila(base, monkeypatch):
    """Documento fiscal duplicado nao se apaga: cancela-se, dentro de prazo,
    com justificativa."""
    monkeypatch.setattr(lote, "_ja_emitidas", lambda ambiente: {CHAVES[0],
                                                                CHAVES[2]})
    fila = lote.pendentes("2026-08-01", "2026-08-27")
    assert [x["chave"] for x in fila] == [CHAVES[1], CHAVES[3]]


def test_so_a_AUTORIZADA_conta_como_feita():
    """Tentativa recusada nao emitiu nada - o CT-e de origem continua
    pendente. A consulta filtra por cStat 100."""
    import inspect
    fonte = inspect.getsource(lote._ja_emitidas)
    assert "cstat='100'" in fonte


def test_agregado_sem_certificado_fica_FORA_da_fila(base, monkeypatch):
    """Fila que inclui quem nao pode emitir promete trabalho que vai falhar."""
    monkeypatch.setattr(lote.cadastro, "mapa",
                        lambda: {"111": {"prontidao": {"pronto": False}}})
    assert lote.pendentes("2026-08-01", "2026-08-27") == []


# --- disjuntor e teto -------------------------------------------------------

def test_o_lote_PARA_depois_de_falhas_seguidas(base, monkeypatch):
    """Falha sistemica rejeita tudo. Sem disjuntor, um lote de mil queima mil
    numeros de serie antes de alguem perceber."""
    def explode(*a, **k):
        raise RuntimeError("SEFAZ fora")

    monkeypatch.setattr(lote.emissao, "transmitir", explode)
    r = lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="x",
                            limite=10)
    assert r["erros"] == lote.MAX_FALHAS_SEGUIDAS
    assert r["interrompido"] and "queimar" in r["interrompido"]
    assert r["restante"] == 4 - lote.MAX_FALHAS_SEGUIDAS


def test_sucesso_no_meio_ZERA_o_contador(base, monkeypatch):
    """Duas recusas separadas por um sucesso nao sao falha sistemica."""
    chamadas = {"n": 0}

    def alterna(chave, enq, **k):
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            return {"autorizado": True, "cStat": "100", "chave": "nova"}
        raise RuntimeError("recusa isolada")

    monkeypatch.setattr(lote.emissao, "transmitir", alterna)
    r = lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="x",
                            limite=10)
    assert r["autorizados"] == 1
    assert r["interrompido"] is None, "o sucesso do meio zerou o contador"


def test_o_teto_e_obrigatorio_e_positivo(base):
    for ruim in (0, -1):
        with pytest.raises(ValueError, match="teto positivo"):
            lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="x",
                                limite=ruim)


def test_o_lote_exige_autor(base):
    with pytest.raises(ValueError, match="Informe quem"):
        lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="",
                            limite=5)


def test_o_teto_absoluto_limita_ate_um_pedido_maior(base):
    """Existe para `limite` vindo de configuracao errada, nao para limitar o
    uso legitimo."""
    assert lote.TETO_ABSOLUTO <= 500
    fila = lote.pendentes("2026-08-01", "2026-08-27", limite=10_000)
    assert len(fila) <= lote.TETO_ABSOLUTO


# --- ensaio -----------------------------------------------------------------

def test_ensaio_NAO_transmite(base, monkeypatch):
    def nao_deveria(*a, **k):
        raise AssertionError("ensaio transmitiu")

    monkeypatch.setattr(lote.emissao, "transmitir", nao_deveria)
    r = lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="x",
                            limite=10, dry_run=True)
    assert r["fila"] == 4
    assert all(i["situacao"] == "ensaio" for i in r["itens"])


def test_o_lote_NAO_escolhe_ambiente(base):
    """Producao continua fechada em `emissao.transmitir`; o lote repassa o
    ambiente e nao tem como contornar."""
    import inspect
    fonte = inspect.getsource(lote)
    assert "PRODUCAO" not in fonte
    assert inspect.signature(
        lote.processar_lote).parameters["ambiente"].default == "2"
