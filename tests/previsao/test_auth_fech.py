# tests/previsao/test_auth_fech.py
"""RBAC da tela fech: mapeamentos estaticos (sem banco)."""
from __future__ import annotations

from api import auth


def test_tela_registrada():
    assert auth.TELAS["fech"] == ("Fechamento do Mês", "Controladoria")


def test_rota_mapeada_para_a_tela():
    assert auth._telas_da_rota("/api/controladoria/previsao") == frozenset({"fech"})
    assert auth._telas_da_rota("/api/controladoria/previsao/ajuste") == frozenset({"fech"})
    # e o orcamento continua sendo do orcamento
    assert auth._telas_da_rota("/api/controladoria/orcamento") == frozenset({"orc"})


def test_perfis_modelo_incluem_fech():
    por_nome = {nome: telas for nome, _d, telas in auth._PERFIS_MODELO}
    assert "fech" in por_nome["Controladoria"]
    assert "fech" in por_nome["Diretoria"]
