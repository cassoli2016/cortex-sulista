"""A tela do piso é restrita, e mesmo assim alcançável por quem usa o sistema.

Duas falhas opostas são possíveis aqui, e as duas já aconteceram no projeto:
conceder amplo demais (expõe risco regulatório a quem não precisa dele) ou
conceder só ao perfil "da área" (a tela nasce invisível, porque esses perfis não
têm usuário — foi o caso de 'extb' na v19).
"""
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


def test_tela_e_concedida_a_controladoria_e_diretoria(esquema_pg):
    perfis = _perfis_com(esquema_pg, "anpiso")
    assert perfis == PERFIS_COM_ACESSO


def test_operacao_e_suprimentos_nao_recebem_a_tela(esquema_pg):
    """Quem contrata o agregado no dia a dia não precisa da exposição legal
    para trabalhar; ampliar o acesso amplia a exposição sem ganho."""
    perfis = _perfis_com(esquema_pg, "anpiso")
    assert "Operação" not in perfis
    assert "Suprimentos" not in perfis
    assert "Painéis TV" not in perfis


def test_a_tela_nao_nasce_invisivel(esquema_pg):
    """Diretoria é o único perfil com usuário real em produção. Sem ela, a tela
    existiria sem ninguém para abrir — o defeito da v19."""
    assert "Diretoria" in _perfis_com(esquema_pg, "anpiso")


def test_perfil_modelo_e_seed_incremental_concordam(esquema_pg):
    """O modelo serve base nova; o seed vN serve base existente. Divergir faz a
    permissão depender da idade da instalação."""
    modelo = {nome for nome, _desc, telas in auth._PERFIS_MODELO if "anpiso" in telas}
    assert modelo == PERFIS_COM_ACESSO


def test_rota_do_piso_exige_a_tela(esquema_pg):
    achado = [telas for prefixo, telas in auth.ROTA_TELAS
              if prefixo == "/api/operacao/antt/piso"]
    assert achado and achado[0] == frozenset({"anpiso"})
