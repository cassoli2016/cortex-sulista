"""cadastros base + operacional + programação + frota

Revision ID: 0002
Revises: "0001"
"""
from pathlib import Path
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

BLOCK = "0002_cadastros_operacional"

def _sql():
    return (Path(__file__).resolve().parents[2] / "sql" / "blocks" / f"{BLOCK}.sql").read_text()

def upgrade():
    op.execute(_sql())

def downgrade():
    op.execute("""DROP TABLE IF EXISTS op_cargas, op_viagens, prog_alocacao, prog_disponibilidade, prog_cargas, fro_manutencao, fro_pneus, sup_contratos, sup_agregados, sup_fornecedores, op_rotas, fro_veiculos, rh_motoristas, com_clientes CASCADE;""")
