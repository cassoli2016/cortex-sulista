"""A Premiação sai de Frota e passa a viver em Telemetria."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from api import auth

HTML = Path(__file__).resolve().parent.parent.parent / "api" / "static" / "index.html"
S = HTML.read_text(encoding="utf-8")


def test_grupo_telemetria_existe_no_menu():
    assert 'id="grpTel"' in S
    assert ">Telemetria<" in S


def test_premiacao_esta_dentro_do_grupo_telemetria():
    bloco = S.split('id="subsTel"', 1)[1].split("</div>", 1)[0]
    assert 'data-view="prem"' in bloco


def test_premiacao_saiu_do_grupo_frota():
    bloco = S.split('id="subsFro"', 1)[1].split("</div>", 1)[0]
    assert 'data-view="prem"' not in bloco


def test_gaveta_mobile_tambem_moveu():
    drawer = S.split('<div class="drawer"', 1)[1]
    tel = drawer.split('data-grp="Tel"', 1)[1].split("</div>", 1)[0]
    assert 'href="#prem"' in tel


def test_rbac_move_a_tela_de_grupo():
    assert auth.TELAS["prem"] == ("Premiação de Motoristas", "Telemetria")


def test_quem_ja_via_a_premiacao_continua_vendo():
    """Mudar de grupo no menu não é razão para tirar acesso de ninguém."""
    tmp = Path(tempfile.mkdtemp()) / "auth.db"
    original = auth.DB_PATH
    try:
        auth.DB_PATH = tmp
        auth.init_db()
    finally:
        auth.DB_PATH = original
    c = sqlite3.connect(tmp)
    perfis = {r[0] for r in c.execute("""
        SELECT p.nome FROM perfis p JOIN perfil_telas t ON t.perfil_id = p.id
        WHERE t.tela = 'prem'""")}
    assert {"Frota", "Diretoria"} <= perfis
