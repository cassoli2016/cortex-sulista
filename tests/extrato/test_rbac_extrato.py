"""RBAC da tela extb: mapeamento de rota e ordem dos prefixos."""
from __future__ import annotations

from api import auth


def test_tela_extb_registrada_no_grupo_financeiro():
    assert auth.TELAS["extb"] == ("Extrato Bancário", "Financeiro")


def test_rotas_do_extrato_mapeadas_para_extb():
    for rota in ("/api/financeiro/extrato",
                 "/api/financeiro/extrato/importar",
                 "/api/financeiro/extrato/contas-erp",
                 "/api/financeiro/extrato/importacao/7"):
        telas = auth._telas_da_rota(rota)
        assert telas == frozenset({"extb"}), rota


def test_prefixo_do_extrato_vem_antes_de_prefixos_genericos():
    # /api/financeiro/extrato NÃO pode ser capturado por uma regra mais curta
    # que venha antes na lista (o casamento é por prefixo, primeira que casa)
    ordem = [p for p, _ in auth.ROTA_TELAS]
    i_ext = ordem.index("/api/financeiro/extrato")
    for p in ordem[:i_ext]:
        assert not "/api/financeiro/extrato".startswith(p) or p == "/api/financeiro/extrato"


def test_perfil_financeiro_modelo_inclui_extb():
    telas = dict((nome, t) for nome, _desc, t in auth._PERFIS_MODELO)
    assert "extb" in telas["Financeiro"]
