"""central de integrações + RAG (pgvector)

Revision ID: 0005
Revises: "0004"
"""
from pathlib import Path
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

BLOCK = "0005_integracoes_rag"

def _sql():
    return (Path(__file__).resolve().parents[2] / "sql" / "blocks" / f"{BLOCK}.sql").read_text()

def upgrade():
    op.execute(_sql())

def downgrade():
    op.execute("""DROP TABLE IF EXISTS int_webhook_log, int_dead_letter, int_raw_events, int_sync_state, int_credenciais, int_conectores, kb_documentos CASCADE;""")
