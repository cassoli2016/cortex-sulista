"""Nome do banco nas tabelas, resolvido pela tabela `banco` do ERP."""
from __future__ import annotations

import pytest

from api.extrato import servico
from api.extrato.servico import _bonito, _codigo_do_ident, banco_da_conta


@pytest.fixture(autouse=True)
def _limpa_cache():
    """O cache é de processo e vazaria entre os testes."""
    servico._NOMES = {}
    yield
    servico._NOMES = {}


@pytest.mark.parametrize("cru,esperado", [
    ("BANCO DO BRASIL S.A.", "Banco do Brasil S.A."),
    ("BANCO BRADESCO S.A.", "Banco Bradesco S.A."),
    ("CAIXA ECONOMICA FEDERAL", "Caixa Economica Federal"),
    ("C6 BANK", "C6 Bank"),
    ("BANCO SANTANDER", "Banco Santander"),
    ("PAMCARD", "Pamcard"),
    ("  BANCO   SAFRA   S.A.  ", "Banco Safra S.A."),
    ("", ""),
])
def test_nome_fica_legivel(cru, esperado):
    assert _bonito(cru) == esperado


def test_nao_corta_no_hifen():
    """"NSTECH IP - EFRETE" perderia justamente o "EFRETE", que é o que
    identifica aquela pseudo-conta."""
    assert _bonito("NSTECH IP - EFRETE") == "Nstech IP - Efrete"
    assert _bonito("BANCO COOPERATIVO SICREDI S.A. - BANSICREDI") == (
        "Banco Cooperativo Sicredi S.A. - Bansicredi")


def test_nao_remove_a_palavra_banco():
    """A tentação óbvia: em "BANCO DO BRASIL" sobraria "do Brasil"."""
    assert _bonito("BANCO DO BRASIL S.A.").startswith("Banco")


@pytest.mark.parametrize("ident,esperado", [
    ("0341/?/0098539349", 341),
    ("336/0001/000034988068-9", 336),
    ("033/?/4849130000265", 33),
    ("csv:104/33227/5405", 104),
    ("", None),
    ("nao-numerico/1/2", None),
])
def test_codigo_sai_do_ident(ident, esperado):
    assert _codigo_do_ident(ident) == esperado


def test_conta_sem_vinculo_ainda_mostra_o_banco(monkeypatch):
    """É justamente quando a conta NÃO está vinculada que o usuário precisa
    saber de que banco ela é — para escolher o vínculo certo."""
    monkeypatch.setattr(servico, "nomes_banco", lambda: {341: "Banco Itaú S.A."})
    cod, nome = banco_da_conta({"ident": "0341/?/0098539349", "erp_banco": None})
    assert (cod, nome) == (341, "Banco Itaú S.A.")


def test_vinculo_com_o_erp_tem_precedencia(monkeypatch):
    monkeypatch.setattr(servico, "nomes_banco", lambda: {341: "Itaú", 237: "Bradesco"})
    cod, nome = banco_da_conta({"ident": "0341/?/x", "erp_banco": 237})
    assert (cod, nome) == (237, "Bradesco")


def test_erp_fora_nao_derruba_a_tela(monkeypatch):
    """Sem nome a tela cai no rótulo antigo, que ao menos traz o código —
    sumir com a conta seria pior."""
    def explode(*_a, **_k):
        raise RuntimeError("connection timeout expired")

    monkeypatch.setattr(servico.db, "query", explode)
    assert servico.nomes_banco() == {}
    assert banco_da_conta({"ident": "0341/?/x", "erp_banco": 341}) == (341, None)


def test_o_cache_evita_uma_consulta_por_conta(monkeypatch):
    """A tela resolve o nome para CADA conta a cada carregamento."""
    chamadas = []

    def conta(*_a, **_k):
        chamadas.append(1)
        return [{"codigo": 341, "nome": "BANCO ITAU S.A."}]

    monkeypatch.setattr(servico.db, "query", conta)
    for _ in range(5):
        servico.nomes_banco()
    assert len(chamadas) == 1
