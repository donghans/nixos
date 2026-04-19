#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
NIXOS_REPO_PATH="$SCRIPT_DIR" sudo -E "$SCRIPT_DIR/core/scripts/nixstrap.sh"
