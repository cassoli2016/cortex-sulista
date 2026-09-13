#!/usr/bin/env bash
# Sobe o MVP do painel financeiro (backend neste Mac).
# PRÉ-REQUISITO: túnel SSH aberto em outra janela:
#   ssh -N -L 15432:<host-do-erp>:5432 <usuario>@<host-de-salto>
#
# Uso: scripts/run_api.sh   → abre em http://127.0.0.1:8000
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Confere se o túnel está de pé antes de subir a API
if ! (exec 3<>/dev/tcp/127.0.0.1/15432) 2>/dev/null; then
  echo "⚠️  Túnel SSH não detectado em 127.0.0.1:15432."
  echo "   Abra em outra janela:"
  echo "   ssh -N -L 15432:<host-do-erp>:5432 <usuario>@<host-de-salto>"
  exit 1
fi
exec 3<&- 3>&- 2>/dev/null || true

echo "→ http://127.0.0.1:8000"
uv run uvicorn api.main:app --port 8000 --host 127.0.0.1 --reload
