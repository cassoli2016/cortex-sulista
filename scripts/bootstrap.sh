#!/usr/bin/env bash
# Bootstrap do CÓRTEX — rode na raiz do projeto descompactado.
set -euo pipefail

echo "==> git + estrutura"
[ -d .git ] || git init -q
mkdir -p api web integrations/connectors

echo "==> .env"
[ -f .env ] || cp .env.example .env

echo "==> infra local (postgres timescale + redis + ollama)"
docker compose up -d postgres redis ollama
ollama pull gemma2:9b || echo "  (rode 'ollama pull gemma2:9b' quando puder)"

echo "==> deps backend + migrations"
if command -v uv >/dev/null; then
  uv sync
  uv run alembic upgrade head
else
  echo "  uv não encontrado — instale uv ou use: pip install -e . && alembic upgrade head"
fi

echo "==> pronto. Abra o Claude Code na raiz com: claude"
