#!/usr/bin/env bash
# Hook environments build from PyPI under the seven-day cutoff, ignoring the repository's uv settings. A run then
# executes the hooks with the caller's environment, so a system hook that calls uv resolves the project as usual.
set -euo pipefail
cooled() (
  unset UV_CONFIG_FILE UV_INDEX UV_INDEX_URL UV_DEFAULT_INDEX UV_EXTRA_INDEX_URL
  unset UV_FIND_LINKS UV_EXCLUDE_NEWER_PACKAGE
  unset UV_INSECURE_HOST UV_SYSTEM_CERTS SSL_CERT_FILE SSL_CERT_DIR
  export UV_EXCLUDE_NEWER="7 days" UV_NO_CONFIG=1 UV_NO_SOURCES=1
  # uv pip, which prek calls, reads per-package cutoffs only from a config file, so the [tool.nab] exceptions the
  # release lock already admits are written to one that holds nothing else.
  exceptions=$(
    python3 -I - <<'PY'
import pathlib
import tomllib

path = pathlib.Path("pyproject.toml")
packages = tomllib.loads(path.read_text()).get("tool", {}).get("nab", {}).get("packages", {}) if path.is_file() else {}
for name, settings in sorted(packages.items()):
    if (cutoff := settings.get("uploaded-prior-to")) is not None:
        value = cutoff.isoformat().replace("+00:00", "Z") if hasattr(cutoff, "isoformat") else str(cutoff)
        print(f'"{name}" = "{value}"')
PY
  )
  if [[ -n "$exceptions" ]]; then
    config=$(mktemp)
    printf '[exclude-newer-package]\n%s\n' "$exceptions" >"$config"
    export UV_CONFIG_FILE="$config"
    echo "Running prek $* with hook environments built under the 7 days cutoff, repository uv settings ignored," \
      "[tool.nab] cutoff exceptions admitted: $(tr '\n' ' ' <<<"$exceptions")"
  else
    echo "Running prek $* with hook environments built under the 7 days cutoff, repository uv settings ignored"
  fi
  exec prek --config .pre-commit-config.yaml "$@"
)
if [[ "${1:-}" != run ]]; then
  cooled "$@"
  exit
fi
# The hook IDs a run names come before its first option; none means every hook.
hooks=()
for argument in "${@:2}"; do
  [[ "$argument" == -* ]] && break
  hooks+=("$argument")
done
cooled install-hooks ${hooks[@]+"${hooks[@]}"}
echo "Running prek $* with the caller's environment"
exec prek --config .pre-commit-config.yaml "$@"
