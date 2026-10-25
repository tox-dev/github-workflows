#!/usr/bin/env bash
# The Actions' own tools come from PyPI under a cutoff, so they refresh themselves without a shared lock.
set -euo pipefail
venv=$1
shift
unset UV_EXCLUDE_NEWER UV_EXCLUDE_NEWER_PACKAGE
options=(--exclude-newer "$EXCLUDE_NEWER")
while IFS= read -r line; do
  read -r line <<<"$line"
  if [[ -n "$line" ]]; then options+=(--exclude-newer-package "$line"); fi
done <<<"${EXCLUDE_NEWER_PACKAGE:-}"
uv venv --allow-existing --python 3.15 "$venv"
uv pip install --python "$venv" "${options[@]}" "$@"
