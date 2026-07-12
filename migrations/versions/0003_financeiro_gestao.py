"""financeiro + gestão (metas/okr/atas/ações)

Revision ID: 0003
Revises: "0002"
"""
from pathlib import Path
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

BLOCK = "0003_financeiro_gestao"

def _sql():
    return (Path(__file__).resolve().parents[2] / "sql" / "blocks" / f"{BLOCK}.sql").read_text()

def upgrade():
    op.execute(_sql())

def downgrade():
    op.execute("""DROP TABLE IF EXISTS fin_titulos, fin_adiantamentos, fin_lancamentos, fin_dre, ges_acoes, ges_atas, ges_okr, ges_metas CASCADE;""")
