#!/usr/bin/env bash
# The Actions' own tools come from PyPI under a cutoff, so they refresh themselves without a shared lock, ignoring the
# repository's uv settings.
set -euo pipefail
venv=$1
shift
unset UV_CONFIG_FILE UV_INDEX UV_INDEX_URL UV_DEFAULT_INDEX UV_EXTRA_INDEX_URL
unset UV_FIND_LINKS UV_EXCLUDE_NEWER UV_EXCLUDE_NEWER_PACKAGE
unset UV_INSECURE_HOST UV_SYSTEM_CERTS SSL_CERT_FILE SSL_CERT_DIR
export UV_NO_CONFIG=1
options=(--exclude-newer "$EXCLUDE_NEWER")
overrides=()
while IFS= read -r line; do
  read -r line <<<"$line"
  if [[ -n "$line" ]]; then
    options+=(--exclude-newer-package "$line")
    overrides+=("$line")
  fi
done <<<"${EXCLUDE_NEWER_PACKAGE:-}"
echo "Installing $* into $venv from PyPI (cutoff $EXCLUDE_NEWER${overrides[*]:+, overrides: ${overrides[*]}})"
uv venv --allow-existing --python 3.15 "$venv"
uv pip install --python "$venv" "${options[@]}" "$@"
