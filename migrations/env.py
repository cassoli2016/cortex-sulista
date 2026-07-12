import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config

def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # monta a partir das variáveis do .env
    u = os.environ.get("POSTGRES_USER", "cortex_app")
    p = os.environ.get("POSTGRES_PASSWORD", "")
    h = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "cortex")
    return f"postgresql+psycopg://{u}:{p}@{h}:{port}/{db}"

config.set_main_option("sqlalchemy.url", _db_url())
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = None  # schema gerido por SQL bruto (timescale/RLS fora do ORM)

def run_migrations_offline():
    context.configure(url=_db_url(), literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    cfg = config.get_section(config.config_ini_section)
    cfg["sqlalchemy.url"] = _db_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
