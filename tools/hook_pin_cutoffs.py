"""Print uv cutoff exceptions for exact pins in pre-commit hooks."""

import ast
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
from collections.abc import Callable, Iterable, Mapping
from typing import Final, NotRequired, TypedDict

import yaml


class Hook(TypedDict):
    id: str
    language: NotRequired[str]
    additional_dependencies: NotRequired[list[str]]


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def exact_pins(requirements: Iterable[str]) -> set[tuple[str, str]]:
    name = r"[A-Za-z0-9][A-Za-z0-9._-]*"
    requirement_pattern = re.compile(rf"\s*({name})(?:\[[^\]]*\])?==([A-Za-z0-9][A-Za-z0-9.+!_-]*)\s*")
    pins = set()
    for requirement in requirements:
        if match := requirement_pattern.fullmatch(requirement.split(";")[0]):
            pins.add((normalize(match[1]), match[2]))
    return pins


def setup_py_pins(text: str) -> set[tuple[str, str]]:
    tree = ast.parse(text)
    constants = static_constants(tree)
    pins = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "setup":
            continue
        for keyword in node.keywords:
            if keyword.arg != "install_requires" or not isinstance(keyword.value, (ast.List, ast.Tuple)):
                continue
            for requirement in keyword.value.elts:
                if value := static_requirement(requirement, constants):
                    pins |= exact_pins([value])
    return pins


def static_constants(tree: ast.Module) -> dict[str, str]:
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
    return constants


def static_requirement(requirement: ast.expr, constants: Mapping[str, str]) -> str | None:
    if isinstance(requirement, ast.Constant) and isinstance(requirement.value, str):
        return requirement.value
    if not isinstance(requirement, ast.JoinedStr):
        return None
    parts = []
    for part in requirement.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            parts.append(part.value)
        elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
            value = constants.get(part.value.id)
            if value is None or part.conversion != -1 or part.format_spec is not None:
                return None
            parts.append(value)
        else:
            return None
    return "".join(parts)


def setup_cfg_pins(text: str) -> set[tuple[str, str]]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    return exact_pins(parser.get("options", "install_requires", fallback="").splitlines())


def pyproject_pins(text: str) -> set[tuple[str, str]]:
    return exact_pins(tomllib.loads(text).get("project", {}).get("dependencies", []))


_PACKAGING_READERS: Final[dict[str, Callable[[str], set[tuple[str, str]]]]] = {
    "setup.py": setup_py_pins,
    "setup.cfg": setup_cfg_pins,
    "pyproject.toml": pyproject_pins,
}


def repo_files(url: str, rev: str) -> dict[str, str]:
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
            wanted = {".pre-commit-hooks.yaml", *_PACKAGING_READERS}
            return {
                name: subprocess.run(
                    [*git, "show", f"FETCH_HEAD:{name}"], capture_output=True, text=True, check=True
                ).stdout
                for name in root
                if name in wanted
            }
        except subprocess.CalledProcessError as error:
            sys.exit(f"cooled-prek: cannot fetch {rev} of {url}: {error.stderr.strip()}")


def hook_pins(url: str, rev: str, hooks: list[Hook]) -> set[tuple[str, str]]:
    files = repo_files(url, rev)
    manifest = {
        hook["id"]: hook.get("language") for hook in yaml.safe_load(files.get(".pre-commit-hooks.yaml", "")) or []
    }
    python_hooks = [
        hook for hook in hooks if (hook.get("language") or manifest.get(hook["id"])) in {"python", "python_venv"}
    ]
    if not python_hooks:
        return set()
    pins = exact_pins(requirement for hook in python_hooks for requirement in hook.get("additional_dependencies", []))
    for name, reader in _PACKAGING_READERS.items():
        if name in files:
            pins |= reader(files[name])
    return pins


def upload_time(url: str, name: str, version: str) -> datetime.datetime:
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


def as_datetime(value: str | datetime.datetime | None) -> datetime.datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.datetime.fromisoformat(value)
        except ValueError:
            return None
    return value if isinstance(value, datetime.datetime) and value.tzinfo is not None else None


def main() -> None:
    path = pathlib.Path("pyproject.toml")
    packages = (
        tomllib.loads(path.read_text()).get("tool", {}).get("nab", {}).get("packages", {}) if path.is_file() else {}
    )
    cutoffs = {
        normalize(name): settings["uploaded-prior-to"]
        for name, settings in packages.items()
        if settings.get("uploaded-prior-to") is not None
    }
    path = pathlib.Path(".pre-commit-config.yaml")
    config = (yaml.safe_load(path.read_text()) if path.is_file() else None) or {}
    seven_days_ago = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)
    pins = {}
    for repo in config.get("repos", []):
        if repo["repo"] in {"local", "meta"}:
            continue
        for name, version in hook_pins(repo["repo"], repo["rev"], repo.get("hooks", [])):
            cutoff = upload_time(repo["repo"], name, version).replace(microsecond=0) + datetime.timedelta(seconds=1)
            if cutoff > seven_days_ago:
                pins[name] = max(pins.get(name, cutoff), cutoff)
    for name, cutoff in pins.items():
        if (current := as_datetime(cutoffs.get(name))) is None or current < cutoff:
            cutoffs[name] = cutoff
    for name, value in sorted(cutoffs.items()):
        value = value.isoformat().replace("+00:00", "Z") if hasattr(value, "isoformat") else str(value)
        print(f'"{name}" = "{value}"')


main()
