#!/bin/bash
# SessionStart hook: install the package + test deps so pytest works in
# Claude Code on the web sessions. Runs only in the remote environment.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Editable install with dev extras (pytest) pulls runtime deps (psycopg,
# psycopg-pool) too. Idempotent and benefits from container-state caching.
# Retry with --break-system-packages for PEP 668 externally-managed envs.
python3 -m pip install --quiet -e ".[dev]" \
  || python3 -m pip install --quiet --break-system-packages -e ".[dev]"
