"""Contrato dos endpoints e a permissão da tela."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from api import auth

PERFIS_COM_ACESSO = {"Controladoria", "Diretoria"}


def _base_semeada():
    tmp = Path(tempfile.mkdtemp()) / "auth.db"
    original = auth.DB_PATH
    try:
        auth.DB_PATH = tmp
        auth.init_db()
    finally:
        auth.DB_PATH = original
    c = sqlite3.connect(tmp)
    c.row_factory = sqlite3.Row
    return c


def test_tela_registrada():
    assert auth.TELAS["anrntrc"] == ("RNTRC dos Transportadores", "ANTT")


def test_rotas_mapeadas_para_a_tela():
    for rota in ("/api/operacao/antt/rntrc", "/api/operacao/antt/rntrc/atualizar"):
        achado = [t for p, t in auth.ROTA_TELAS if p == rota]
        assert achado and achado[0] == frozenset({"anrntrc"})


def test_rota_de_atualizar_vem_antes_da_rota_de_leitura():
    """Prefixo mais específico primeiro, senão a de leitura captura o POST."""
    pos = {p: i for i, (p, _) in enumerate(auth.ROTA_TELAS)}
    assert pos["/api/operacao/antt/rntrc/atualizar"] < pos["/api/operacao/antt/rntrc"]


def test_tela_e_restrita_como_a_do_piso():
    c = _base_semeada()
    perfis = {r["nome"] for r in c.execute("""
        SELECT p.nome FROM perfis p JOIN perfil_telas t ON t.perfil_id = p.id
        WHERE t.tela = 'anrntrc'""")}
    assert perfis == PERFIS_COM_ACESSO


def test_endpoints_existem_no_app():
    from api.main import app
    caminhos = {getattr(r, "path", None) for r in app.routes}
    assert "/api/operacao/antt/rntrc" in caminhos
    assert "/api/operacao/antt/rntrc/atualizar" in caminhos
