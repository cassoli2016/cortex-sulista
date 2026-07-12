#!/usr/bin/env bash
# Helper de acesso ao Postgres do CÓRTEX via Tailscale.
# Lê credenciais do .env; a senha NUNCA é impressa (fica só em PGPASSWORD).
#
# Uso:
#   scripts/db.sh ping                 # testa conexão (superuser)
#   scripts/db.sh psql                 # abre shell psql interativo (superuser)
#   scripts/db.sh file scripts/scan_financeiro.sql   # roda um .sql
#   scripts/db.sh app psql             # conecta como cortex_app (sujeito a RLS)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/.env" ] || { echo "ERRO: $ROOT/.env não existe."; exit 1; }
set -a; . "$ROOT/.env"; set +a

# Localiza psql (libpq via brew é keg-only, não entra no PATH sozinho)
PSQL="psql"
if ! command -v psql >/dev/null 2>&1; then
  for p in "$(brew --prefix libpq 2>/dev/null)/bin/psql" \
           /opt/homebrew/opt/libpq/bin/psql /usr/local/opt/libpq/bin/psql; do
    [ -x "$p" ] && PSQL="$p" && break
  done
fi

# Escolhe usuário: superuser (default, bypassa RLS) ou app
ROLE="super"
if [ "${1:-}" = "app" ]; then ROLE="app"; shift; fi

if [ "$ROLE" = "app" ]; then
  export PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD"
else
  export PGUSER="$POSTGRES_SUPERUSER" PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD"
fi
export PGHOST="$POSTGRES_HOST" PGPORT="$POSTGRES_PORT" PGDATABASE="$POSTGRES_DB"
export PGCONNECT_TIMEOUT=8

cmd="${1:-ping}"; shift || true
case "$cmd" in
  ping)  "$PSQL" -c "SELECT current_user, current_database(), version();" ;;
  psql)  "$PSQL" "$@" ;;
  file)  "$PSQL" -v ON_ERROR_STOP=off -f "$1" ;;
  *)     echo "Comando desconhecido: $cmd (use: ping | psql | file <arquivo.sql> | app <cmd>)"; exit 2 ;;
esac
