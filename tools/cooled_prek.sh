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
  # release lock already admits and the exact hook pins are written to one that holds nothing else. A pinned release
  # stays admitted while it is younger than the cutoff, up to its upload time, so the pin installs and newer releases
  # of the package stay blocked; its dependencies stay cooled. PyYAML comes from uv under the same cutoff because the
  # runner's python3 may not have it and the hook manifests are YAML. The snippet runs under -I, which drops the
  # runner's PYTHONPATH and keeps the repository directory off sys.path.
  exceptions=$(
    uv run --no-project --with pyyaml python -I - <<'PY'
import configparser
import datetime
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import tomllib
import urllib.request

import yaml

HOOK_LANGUAGES = {"python", "python_venv"}
NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"
VERSION = r"[A-Za-z0-9][A-Za-z0-9.+!_-]*"
REQUIREMENT = re.compile(rf"\s*({NAME})(?:\[[^\]]*\])?==({VERSION})\s*")
SETUP_PY_INSTALL_REQUIRES = re.compile(r"install_requires\s*=\s*\[((?:[^\[\]]|\[[^\]]*\])*)\]")
QUOTED = re.compile(r"[\"']([^\"']+)[\"']")
SEVEN_DAYS_AGO = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def exact_pins(requirements):
    pins = set()
    for requirement in requirements:
        if match := REQUIREMENT.fullmatch(requirement.split(";")[0]):
            pins.add((normalize(match[1]), match[2]))
    return pins


def setup_py_pins(text):
    match = SETUP_PY_INSTALL_REQUIRES.search(text)
    return exact_pins(QUOTED.findall(match[1])) if match else set()


def setup_cfg_pins(text):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    return exact_pins(parser.get("options", "install_requires", fallback="").splitlines())


def pyproject_pins(text):
    return exact_pins(tomllib.loads(text).get("project", {}).get("dependencies", []))


PACKAGING_READERS = {"setup.py": setup_py_pins, "setup.cfg": setup_cfg_pins, "pyproject.toml": pyproject_pins}


def repo_files(url, rev):
    with tempfile.TemporaryDirectory() as directory:
        git = ["git", "-C", directory]
        try:
            subprocess.run(["git", "init", "-q", directory], capture_output=True, text=True, check=True)
            subprocess.run(
                [*git, "fetch", "-q", "--depth", "1", "--filter=blob:none", url, rev],
                capture_output=True,
                text=True,
                check=True,
            )
            root = subprocess.run(
                [*git, "ls-tree", "--name-only", "FETCH_HEAD"], capture_output=True, text=True, check=True
            ).stdout.split()
            wanted = {".pre-commit-hooks.yaml", *PACKAGING_READERS}
            return {
                name: subprocess.run(
                    [*git, "show", f"FETCH_HEAD:{name}"], capture_output=True, text=True, check=True
                ).stdout
                for name in root
                if name in wanted
            }
        except subprocess.CalledProcessError as error:
            sys.exit(f"cooled-prek: cannot fetch {rev} of {url}: {error.stderr.strip()}")


def hook_pins(url, rev, hooks):
    files = repo_files(url, rev)
    manifest = {
        hook["id"]: hook.get("language") for hook in yaml.safe_load(files.get(".pre-commit-hooks.yaml", "")) or []
    }
    python_hooks = [hook for hook in hooks if (hook.get("language") or manifest.get(hook["id"])) in HOOK_LANGUAGES]
    if not python_hooks:
        return set()
    pins = exact_pins(requirement for hook in python_hooks for requirement in hook.get("additional_dependencies", []))
    for name, reader in PACKAGING_READERS.items():
        if name in files:
            pins |= reader(files[name])
    return pins


def upload_time(url, name, version):
    # Fixed PyPI origin, read with the same request as tools/verify_pypi_files.py.
    request = urllib.request.Request(
        f"https://pypi.org/simple/{name}/",
        headers={"Accept": "application/vnd.pypi.simple.v1+json", "Cache-Control": "no-cache"},
    )
    parts = "[-_.]+".join(re.escape(part) for part in name.split("-"))
    pattern = re.compile(rf"{parts}-{re.escape(version)}(?:-|\.tar\.gz$|\.zip$)", re.IGNORECASE)
    try:
        with urllib.request.urlopen(  # ruff: ignore[suspicious-url-open-usage]  # Fixed PyPI origin.
            request, timeout=30
        ) as response:
            files = json.load(response)["files"]
        times = [
            datetime.datetime.fromisoformat(file["upload-time"]) for file in files if pattern.match(file["filename"])
        ]
    except (OSError, ValueError, KeyError) as error:
        sys.exit(f"cooled-prek: cannot read {name} from PyPI for the hook repository {url}: {error}")
    if not times:
        sys.exit(f"cooled-prek: PyPI has no files for {name}=={version}, pinned by the hook repository {url}")
    return max(times)


def as_datetime(value):
    if isinstance(value, str):
        try:
            value = datetime.datetime.fromisoformat(value)
        except ValueError:
            return None
    return value if isinstance(value, datetime.datetime) and value.tzinfo is not None else None


path = pathlib.Path("pyproject.toml")
packages = tomllib.loads(path.read_text()).get("tool", {}).get("nab", {}).get("packages", {}) if path.is_file() else {}
cutoffs = {
    normalize(name): settings["uploaded-prior-to"]
    for name, settings in packages.items()
    if settings.get("uploaded-prior-to") is not None
}
path = pathlib.Path(".pre-commit-config.yaml")
config = (yaml.safe_load(path.read_text()) if path.is_file() else None) or {}
pins = {}
for repo in config.get("repos", []):
    if repo["repo"] in {"local", "meta"}:
        continue
    for name, version in hook_pins(repo["repo"], repo["rev"], repo.get("hooks", [])):
        cutoff = upload_time(repo["repo"], name, version).replace(microsecond=0) + datetime.timedelta(seconds=1)
        if cutoff > SEVEN_DAYS_AGO:
            pins[name] = max(pins.get(name, cutoff), cutoff)
for name, cutoff in pins.items():
    current = as_datetime(cutoffs.get(name))
    if current is None or current < cutoff:
        cutoffs[name] = cutoff
for name, value in sorted(cutoffs.items()):
    value = value.isoformat().replace("+00:00", "Z") if hasattr(value, "isoformat") else str(value)
    print(f'"{name}" = "{value}"')
PY
  )
  if [[ -n "$exceptions" ]]; then
    config=$(mktemp)
    printf '[exclude-newer-package]\n%s\n' "$exceptions" >"$config"
    export UV_CONFIG_FILE="$config"
    echo "Running prek $* with hook environments built under the 7 days cutoff, repository uv settings ignored," \
      "[tool.nab] exceptions and exact hook pins admitted up to their dates: $(tr '\n' ' ' <<<"$exceptions")"
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
