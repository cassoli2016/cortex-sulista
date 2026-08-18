"""A tela do piso é restrita, e mesmo assim alcançável por quem usa o sistema.

Duas falhas opostas são possíveis aqui, e as duas já aconteceram no projeto:
conceder amplo demais (expõe risco regulatório a quem não precisa dele) ou
conceder só ao perfil "da área" (a tela nasce invisível, porque esses perfis não
têm usuário — foi o caso de 'extb' na v19).
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from api import auth

PERFIS_COM_ACESSO = {"Controladoria", "Diretoria"}


def _base_semeada() -> sqlite3.Connection:
    """Sobe um auth.db do zero e devolve a conexão já semeada."""
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


def test_tela_e_concedida_a_controladoria_e_diretoria():
    c = _base_semeada()
    perfis = {r["nome"] for r in c.execute("""
        SELECT p.nome FROM perfis p
        JOIN perfil_telas t ON t.perfil_id = p.id
        WHERE t.tela = 'anpiso'""")}
    assert perfis == PERFIS_COM_ACESSO


def test_operacao_e_suprimentos_nao_recebem_a_tela():
    """Quem contrata o agregado no dia a dia não precisa da exposição legal
    para trabalhar; ampliar o acesso amplia a exposição sem ganho."""
    c = _base_semeada()
    perfis = {r["nome"] for r in c.execute("""
        SELECT p.nome FROM perfis p
        JOIN perfil_telas t ON t.perfil_id = p.id
        WHERE t.tela = 'anpiso'""")}
    assert "Operação" not in perfis
    assert "Suprimentos" not in perfis
    assert "Painéis TV" not in perfis


def test_a_tela_nao_nasce_invisivel():
    """Diretoria é o único perfil com usuário real em produção. Sem ela, a tela
    existiria sem ninguém para abrir — o defeito da v19."""
    c = _base_semeada()
    assert c.execute("""
        SELECT 1 FROM perfis p JOIN perfil_telas t ON t.perfil_id = p.id
        WHERE t.tela = 'anpiso' AND p.nome = 'Diretoria'""").fetchone()


def test_perfil_modelo_e_seed_incremental_concordam():
    """O modelo serve base nova; o seed vN serve base existente. Divergir faz a
    permissão depender da idade da instalação."""
    modelo = {nome for nome, _desc, telas in auth._PERFIS_MODELO if "anpiso" in telas}
    assert modelo == PERFIS_COM_ACESSO


def test_rota_do_piso_exige_a_tela():
    achado = [telas for prefixo, telas in auth.ROTA_TELAS
              if prefixo == "/api/operacao/antt/piso"]
    assert achado and achado[0] == frozenset({"anpiso"})
