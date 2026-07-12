"""extensões + governança/acesso

Revision ID: 0001
Revises: None
"""
from pathlib import Path
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

BLOCK = "0001_extensions_governance"

def _sql():
    return (Path(__file__).resolve().parents[2] / "sql" / "blocks" / f"{BLOCK}.sql").read_text()

def upgrade():
    op.execute(_sql())

def downgrade():
    op.execute("""DROP TABLE IF EXISTS audit_log, papel_modulo, usuario_filial, usuario_papel, papeis, usuarios, filiais CASCADE;""")
