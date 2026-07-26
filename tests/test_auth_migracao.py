"""Testa a migração v17 (tela 'orc' ao perfil Controladoria) sem tocar o
data/auth.db real: usa um SQLite temporário e o mesmo padrão das migrações
anteriores (v3-v16) que acrescentam tela a perfil já existente.
"""
from __future__ import annotations

from api import auth


def _tela_no_perfil(conn, perfil: str, tela: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM perfil_telas pt JOIN perfis p ON p.id = pt.perfil_id "
        "WHERE p.nome=? AND pt.tela=?", (perfil, tela)).fetchone()
    return row is not None


def test_v17_acrescenta_orc_ao_controladoria_ja_existente(tmp_path, monkeypatch):
    """Simula uma base já migrada até v16 (o estado real de produção): o
    perfil Controladoria existe, mas sem a tela 'orc' porque ela nasceu
    depois. init_db() de novo precisa acrescentar a tela sem recriar nada."""
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")

    # 1) init_db() normal deixa a base no estado atual (todas as migrações,
    #    inclusive a v17 que estamos testando, já aplicadas).
    auth.init_db()

    # 2) volta a base para "antes da v17": remove a concessão da tela e o
    #    flag de migração — é exatamente o estado de um auth.db que já
    #    rodou v1..v16 antes de 'orc' existir.
    with auth._conn() as c:
        c.execute("DELETE FROM config WHERE chave='perfis_modelo_v17'")
        c.execute("""
            DELETE FROM perfil_telas WHERE tela='orc' AND perfil_id = (
                SELECT id FROM perfis WHERE nome='Controladoria')
        """)

    with auth._conn() as c:
        assert not _tela_no_perfil(c, "Controladoria", "orc")

    # 3) roda a migração de novo: a v17 deve rodar e conceder a tela.
    auth.init_db()

    with auth._conn() as c:
        assert _tela_no_perfil(c, "Controladoria", "orc")
        n = c.execute("""
            SELECT count(*) AS n FROM perfil_telas pt
            JOIN perfis p ON p.id = pt.perfil_id
            WHERE p.nome='Controladoria' AND pt.tela='orc'
        """).fetchone()["n"]
        assert n == 1  # nada duplicado nessa primeira reaplicação

    # 4) idempotência: rodar de novo (com o flag já setado) não duplica a
    #    linha em perfil_telas nem falha por violar a PK composta.
    auth.init_db()
    auth.init_db()

    with auth._conn() as c:
        n = c.execute("""
            SELECT count(*) AS n FROM perfil_telas pt
            JOIN perfis p ON p.id = pt.perfil_id
            WHERE p.nome='Controladoria' AND pt.tela='orc'
        """).fetchone()["n"]
        assert n == 1
        flag = c.execute(
            "SELECT valor FROM config WHERE chave='perfis_modelo_v17'").fetchone()
        assert flag["valor"] == "1"
