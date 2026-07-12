"""row-level security + views analíticas

Revision ID: 0006
Revises: "0005"
"""
from pathlib import Path
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

BLOCK = "0006_rls_views"

def _sql():
    return (Path(__file__).resolve().parents[2] / "sql" / "blocks" / f"{BLOCK}.sql").read_text()

def upgrade():
    op.execute(_sql())

def downgrade():
    op.execute("""DROP VIEW IF EXISTS vw_viagens_ativas CASCADE; DROP MATERIALIZED VIEW IF EXISTS vw_rkm_cliente, vw_ckm_viagem, vw_resultado_viagem, vw_fluxo_caixa, vw_dre_mensal, vw_compliance_jornada, vw_sinistralidade CASCADE; DROP FUNCTION IF EXISTS app_filiais() CASCADE;""")
