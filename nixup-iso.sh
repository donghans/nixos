#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
python3 "$SCRIPT_DIR/core/scripts/nixstrap.lib-repo.py" sync-remote "$SCRIPT_DIR"
exec "$SCRIPT_DIR/core/scripts/nixup.sh" iso "$@"
