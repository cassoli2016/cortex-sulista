"""Contrato dos endpoints e a permissão da tela."""
from __future__ import annotations

import tempfile
from pathlib import Path

from api import auth

PERFIS_COM_ACESSO = {"Controladoria", "Diretoria"}


def _perfis_com(esquema: str, tela: str) -> set[str]:
    """Nomes dos perfis que enxergam uma tela, lidos do banco JÁ SEMEADO.

    Era um `auth.db` em pasta temporária aberto com sqlite3; virou o schema do
    teste no PostgreSQL. A pergunta é a mesma — quem enxerga o quê —, só mudou
    a língua.
    """
    from api import pglocal
    original = auth.ESQUEMA
    try:
        auth.ESQUEMA = esquema
        auth.init_db()
    finally:
        auth.ESQUEMA = original
    return {r["nome"] for r in pglocal.query(
        "SELECT p.nome FROM perfis p JOIN perfil_telas t ON t.perfil_id = p.id"
        " WHERE t.tela = %s", (tela,), esquema=esquema)}


def test_tela_registrada(esquema_pg):
    assert auth.TELAS["anrntrc"] == ("RNTRC dos Transportadores", "ANTT")


def test_rotas_mapeadas_para_a_tela(esquema_pg):
    for rota in ("/api/operacao/antt/rntrc", "/api/operacao/antt/rntrc/atualizar"):
        achado = [t for p, t in auth.ROTA_TELAS if p == rota]
        assert achado and achado[0] == frozenset({"anrntrc"})


def test_rota_de_atualizar_vem_antes_da_rota_de_leitura(esquema_pg):
    """Prefixo mais específico primeiro, senão a de leitura captura o POST."""
    pos = {p: i for i, (p, _) in enumerate(auth.ROTA_TELAS)}
    assert pos["/api/operacao/antt/rntrc/atualizar"] < pos["/api/operacao/antt/rntrc"]


def test_tela_e_restrita_como_a_do_piso(esquema_pg):
    assert _perfis_com(esquema_pg, "anrntrc") == PERFIS_COM_ACESSO


def test_endpoints_existem_no_app(esquema_pg):
    from api.main import app
    caminhos = {getattr(r, "path", None) for r in app.routes}
    assert "/api/operacao/antt/rntrc" in caminhos
    assert "/api/operacao/antt/rntrc/atualizar" in caminhos
