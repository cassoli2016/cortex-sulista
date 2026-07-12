"""séries temporais (hypertables) + agregados + políticas Timescale

Revision ID: 0004
Revises: 0003
"""
from pathlib import Path
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

def _sql():
    return (Path(__file__).resolve().parents[2] / "sql" / "blocks" / "0004_timeseries.sql").read_text()

def upgrade():
    # Timescale: continuous aggregate exige fora de transação -> AUTOCOMMIT
    conn = op.get_bind().execution_options(isolation_level="AUTOCOMMIT")
    conn.exec_driver_sql(_sql())

def downgrade():
    conn = op.get_bind().execution_options(isolation_level="AUTOCOMMIT")
    conn.exec_driver_sql(
        "DROP MATERIALIZED VIEW IF EXISTS vw_consumo_veiculo CASCADE;"
        "DROP TABLE IF EXISTS tel_sinais, tel_dtc, tc_posicoes, tc_ocorrencias, "
        "ts_eventos, ts_scores, jor_eventos, jor_jornadas CASCADE;"
    )
