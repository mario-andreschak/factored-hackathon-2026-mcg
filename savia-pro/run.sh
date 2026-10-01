#!/usr/bin/env bash
# Savia Pro - one command from a clean checkout to a running portal.
#
#   ./run.sh              build everything that is missing, then serve
#   ./run.sh --rebuild    force the serving database to be rebuilt
#   ./run.sh --api-only   skip the web build (useful on a machine without Node)
#
set -euo pipefail
cd "$(dirname "$0")"

PORT="${SAVIA_PORT:-43950}"
SERVING="${SAVIA_SERVING:-var/serving.duckdb}"
REBUILD=0
API_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --rebuild)  REBUILD=1 ;;
    --api-only) API_ONLY=1 ;;
    *) ;;
  esac
done

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "1/4  Python dependencies"
python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt

say "2/4  Serving database"
if [[ "$REBUILD" == "1" || ! -f "$SERVING" ]]; then
  python3 tools/build_serving.py --verify
else
  echo "     $SERVING already present (use --rebuild to refresh)"
fi

if [[ "$API_ONLY" == "0" ]]; then
  say "3/4  Web client"
  if command -v npm >/dev/null 2>&1; then
    ( cd web; if [[ ! -d node_modules ]]; then npm ci --no-audit --no-fund; fi )
    ( cd web && npm run build )
  else
    echo "     npm not found - the API will serve without a bundled client."
    echo "     Install Node 20+ or run with --api-only."
  fi
else
  say "3/4  Web client  (skipped)"
fi

say "4/4  Serving on http://127.0.0.1:${PORT}/"
exec python3 -m server.main --port "$PORT"
