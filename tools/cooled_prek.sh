#!/usr/bin/env bash
# Hook environments build from PyPI under the seven-day cutoff, ignoring the repository's uv settings.
set -euo pipefail
unset UV_CONFIG_FILE UV_INDEX UV_INDEX_URL UV_DEFAULT_INDEX UV_EXTRA_INDEX_URL
unset UV_FIND_LINKS UV_EXCLUDE_NEWER_PACKAGE
unset UV_INSECURE_HOST UV_SYSTEM_CERTS SSL_CERT_FILE SSL_CERT_DIR
export UV_EXCLUDE_NEWER="7 days" UV_NO_CONFIG=1 UV_NO_SOURCES=1
exec prek --config .pre-commit-config.yaml "$@"
