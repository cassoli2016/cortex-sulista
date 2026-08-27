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
    monkeypatch.setattr(lote.emissao, "config_lida", lambda chave: None)
    assert lote.automacao_ativa() is False


def test_valor_desconhecido_tambem_conta_como_DESLIGADO(monkeypatch):
    """So a string "1" liga. Lixo na configuracao nao pode virar autorizacao
    para emitir sozinho."""
    monkeypatch.setattr(lote.emissao, "config_lida",
                        lambda chave: {"valor": "talvez"})
    assert lote.automacao_ativa() is False


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


def test_o_lote_NAO_DECIDE_o_ambiente(base):
    """Ele atende os dois, mas quem recusa producao nao liberada e
    `emissao.transmitir`. O lote repassa - e o padrao segue homologacao."""
    import inspect
    assert inspect.signature(
        lote.processar_lote).parameters["ambiente"].default == "2"
    fonte = inspect.getsource(lote.processar_lote)
    assert "liberar_producao" not in fonte, (
        "o lote nao pode destravar producao por conta propria")


def test_producao_tem_teto_MENOR_que_homologacao():
    """Lote errado em homologacao custa tempo; em producao custa cancelamento
    e retificacao, documento a documento."""
    assert lote.teto_do(lote.emissao.PRODUCAO) < lote.teto_do("2")
    assert lote.teto_do(lote.emissao.PRODUCAO) == lote.TETO_ABSOLUTO_PRODUCAO


def test_a_fila_de_producao_respeita_o_teto_menor(base):
    fila = lote.pendentes("2026-08-01", "2026-08-27",
                          ambiente=lote.emissao.PRODUCAO, limite=10_000)
    assert len(fila) <= lote.TETO_ABSOLUTO_PRODUCAO


# --- os dois ambientes ------------------------------------------------------

def test_producao_nasce_TRAVADA(monkeypatch):
    """Nasce assim e nao destrava sozinha."""
    monkeypatch.setattr(lote.emissao, "config_lida", lambda chave: None)
    assert lote.emissao.producao_liberada() is False


def test_liberar_producao_EXIGE_a_frase_de_confirmacao():
    """`--producao` numa linha de comando e facil demais de digitar por
    engano, e o engano aqui custa cancelamento e retificacao."""
    with pytest.raises(PermissionError, match="confirme com a frase"):
        lote.emissao.liberar_producao(True, "fulano", confirmacao="sim")
    with pytest.raises(PermissionError):
        lote.emissao.liberar_producao(True, "fulano", confirmacao="")


def test_DESLIGAR_producao_nao_pede_frase(monkeypatch):
    """Desligar e sempre seguro e nao pode depender de lembrar de uma frase no
    meio de um problema."""
    vistos = {}
    monkeypatch.setattr(lote.emissao, "config_grava",
                        lambda c, a, q, acao: vistos.update(ativa=a, quem=q))
    lote.emissao.liberar_producao(False, "fulano")
    assert vistos == {"ativa": False, "quem": "fulano"}


def test_transmitir_em_producao_TRAVADA_e_recusado(monkeypatch):
    monkeypatch.setattr(lote.emissao, "producao_liberada", lambda: False)
    with pytest.raises(PermissionError, match="PRODUÇÃO está travada"):
        lote.emissao._guardas("111", {"emit_cnpj": "111"},
                              lote.emissao.PRODUCAO)


def test_ambiente_inexistente_e_recusado():
    with pytest.raises(ValueError, match="não existe"):
        lote.emissao._guardas("111", {"emit_cnpj": "111"}, "9")
