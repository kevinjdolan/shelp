#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to install shelp." >&2
  exit 1
fi

uv tool install --force --editable "$ROOT_DIR"

BIN_DIR="$(uv tool dir --bin)"

if (($# == 0)); then
  exec "$BIN_DIR/shelp" install --all-shells
fi

exec "$BIN_DIR/shelp" install "$@"
