from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import tomllib
from collections.abc import Iterator, Mapping
from hashlib import sha256
from html import escape
from pathlib import Path
from textwrap import dedent
from typing import Final
from urllib.parse import urlsplit
from urllib.request import urlopen

import certifi
import pytest
import trustme
import yaml
from packaging.utils import canonicalize_name
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response


@pytest.fixture
def github_api(tmp_path: Path) -> Iterator[tuple[HTTPServer, dict[str, str]]]:
    authority = trustme.CA()
    certificate = authority.issue_cert("localhost")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    certificate.configure_cert(context)
    server = HTTPServer(host="localhost", ssl_context=context)
    server.start()
    bundle = tmp_path / "ca.pem"
    authority.cert_pem.write_to_path(bundle)
    bundle.write_bytes(bundle.read_bytes() + Path(certifi.where()).read_bytes())
    yield (
        server,
        {
            "GH_HOST": f"localhost:{server.port}",
            "GH_ENTERPRISE_TOKEN": "test-token",
            "SSL_CERT_FILE": str(bundle),
            "NO_PROXY": "localhost,127.0.0.1",
        },
    )
    server.stop()


@pytest.fixture(scope="session")
def action_scripts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    source = Path(__file__).resolve().parents[1]
    scripts = tmp_path_factory.mktemp("action-steps")
    for action_name in (
        "prepare-towncrier",
        "validate-release-patch",
        "commit-and-tag",
        "render-release-notes",
        "select-previous-tag",
        "validate-news",
        "refresh-release-lock",
        "install-locked-tools",
        "export-build-constraints",
        "build-python-distribution",
        "read-towncrier-config",
        "publish-github-release",
        "reconcile-pypi-artifacts",
        "publish-jetbrains-marketplace",
        "sign-jetbrains-plugin",
        "check-hook-update-cooldown",
        "recheck-hook-update-cooldown",
        "publish-post-release-pr",
    ):
        action = yaml.safe_load((source / action_name / "action.yml").read_text())
        for index, step in enumerate(action["runs"]["steps"]):
            if "run" not in step:
                continue
            path = scripts / f"{action_name}-{index}.sh"
            path.write_text(f"#!/usr/bin/env bash\n{step['run']}")
            path.chmod(0o755)
    return scripts


@pytest.fixture(scope="session")
def test_package_lock(tmp_path_factory: pytest.TempPathFactory, nab_executable: Path) -> Path:
    fixture = tmp_path_factory.mktemp("fixture-lock")
    (fixture / "pyproject.toml").write_text(
        '[project]\nname = "release-fixture"\nversion = "0.1.0"\nrequires-python = ">=3.15,<3.16"\n'
        '[dependency-groups]\nfixture = ["check-wheel-contents>=0.6.3", "hatchling>=1.28", "twine>=7"]\n'
        '[tool.nab]\nmode = "universal"\nbase-group = "project-runtime"\n'
        'default-groups = []\n[tool.nab.matrix]\npython = ">=3.15,<3.16"\nplatforms = ["linux_x86_64"]\n'
    )
    subprocess.run(
        [str(nab_executable), "lock", "--no-cache", "--groups", "fixture", "--output", "pylock.toml"],
        cwd=fixture,
        check=True,
        capture_output=True,
    )
    return fixture / "pylock.toml"


@pytest.fixture
def test_package_index(httpserver: HTTPServer, test_package_lock: Path, artifact_cache: dict[str, bytes]) -> str:
    packages = [
        *tomllib.loads((Path(__file__).resolve().parents[1] / "pylock.toml").read_text())["packages"],
        *tomllib.loads(test_package_lock.read_text())["packages"],
    ]
    listings: dict[str, list[str]] = {}
    artifacts: dict[str, tuple[str, str]] = {}
    for package in packages:
        links = listings.setdefault(canonicalize_name(package["name"]), [])
        for artifact in [*package.get("wheels", []), *([package["sdist"]] if "sdist" in package else [])]:
            filename = artifact.get("name") or urlsplit(artifact["url"]).path.rsplit("/", 1)[-1]
            digest = artifact["hashes"]["sha256"]
            artifacts[filename] = artifact["url"], digest
            links.append(
                f'<a href="{escape(httpserver.url_for(f"/files/{filename}"))}#sha256={digest}" '
                f'data-upload-time="{artifact["upload-time"].isoformat()}">{escape(filename)}</a>'
            )
    for name, links in listings.items():
        httpserver.expect_request(f"/simple/{name}/").respond_with_data("\n".join(links), content_type="text/html")
    for filename, (url, digest) in artifacts.items():

        def serve(_request: Request, *, source: str = url, expected: str = digest) -> Response:
            if expected not in artifact_cache:
                with urlopen(source, timeout=30) as stream:
                    artifact_cache[expected] = stream.read()
            content = artifact_cache[expected]
            assert sha256(content).hexdigest() == expected
            return Response(content, mimetype="application/octet-stream")

        httpserver.expect_request(f"/files/{filename}").respond_with_handler(serve)
    return httpserver.url_for("/simple/")


@pytest.fixture(scope="session")
def artifact_cache() -> dict[str, bytes]:
    return {}


@pytest.fixture(scope="session")
def pypi_metadata(tmp_path_factory: pytest.TempPathFactory) -> Path:
    packages = tomllib.loads((Path(__file__).resolve().parents[1] / "pylock.toml").read_text())["packages"]
    listings: dict[str, dict[str, dict[str, str | dict[str, str]]]] = {}
    for package in packages:
        files = listings.setdefault(canonicalize_name(package["name"]), {})
        for artifact in [*package.get("wheels", []), *([package["sdist"]] if "sdist" in package else [])]:
            filename = artifact.get("name") or urlsplit(artifact["url"]).path.rsplit("/", 1)[-1]
            files[filename] = {
                "filename": filename,
                "url": artifact["url"],
                "hashes": artifact["hashes"],
                "upload-time": artifact["upload-time"].isoformat(),
            }
    for filename, url, digest, uploaded in (
        (
            "six-1.16.0-py2.py3-none-any.whl",
            "https://files.pythonhosted.org/packages/d9/5a/e7c31adbe875f2abbb91bd84cf2dc52d792b5a01506781dbcf25c91daf11/six-1.16.0-py2.py3-none-any.whl",
            "8abb2f1d86890a2dfb989f9a77cfcfd3e47c2a354b01111771326f8aa26e0254",
            "2021-05-05T14:18:17.237677+00:00",
        ),
        (
            "example-1.0-py3-none-any.whl",
            "https://files.pythonhosted.org/example-1.0-py3-none-any.whl",
            "0" * 64,
            "2026-10-01T00:00:00+00:00",
        ),
        (
            "example-2.0-py3-none-any.whl",
            "https://files.pythonhosted.org/example-2.0-py3-none-any.whl",
            "1" * 64,
            "2026-10-01T00:00:00+00:00",
        ),
    ):
        name = filename.split("-", 1)[0]
        listings.setdefault(name, {})[filename] = {
            "filename": filename,
            "url": url,
            "hashes": {"sha256": digest},
            "upload-time": uploaded,
        }
    path = tmp_path_factory.mktemp("pypi-metadata") / "listings.json"
    path.write_text(json.dumps({name: list(files.values()) for name, files in listings.items()}))
    return path


@pytest.fixture(autouse=True)
def pypi_metadata_environment(pypi_metadata: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GW_PYPI_METADATA_FILE", str(pypi_metadata))


@pytest.fixture(scope="session")
def nab_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[1]
    environment = tmp_path_factory.mktemp("nab-tools")
    subprocess.run(["uv", "venv", "--python", "3.15", str(environment)], check=True, capture_output=True)
    subprocess.run(
        [
            "uv",
            "pip",
            "sync",
            "--preview-features",
            "pylock",
            "--python",
            str(environment / "bin/python"),
            "--group",
            "lock-tools",
            "--only-binary",
            ":all:",
            "--require-hashes",
            str(root / "pylock.toml"),
        ],
        check=True,
        capture_output=True,
    )
    return environment / "bin/nab"


@pytest.fixture
def repository(tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]], monkeypatch: pytest.MonkeyPatch) -> Path:
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "--bare", str(remote))
    worktree = tmp_path / "worktree"
    run(tmp_path, "git", "init", "-b", "main", str(worktree))
    run(worktree, "git", "config", "user.name", "Release test")
    run(worktree, "git", "config", "user.email", "release@example.org")
    run(worktree, "git", "remote", "add", "origin", str(remote))
    (worktree / "pyproject.toml").write_text(
        '[tool.towncrier]\nname = "fixture"\ndirectory = "changelog.d"\n'
        'filename = "CHANGELOG.md"\ntemplate = "release_creator.fragments:template.jinja2"\n'
        'title_format = false\ntype = [{ directory = "feature", name = "Added", showcontent = true }]\n',
    )
    (worktree / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: release-check\n"
        "        name: release-check\n        entry: bash -c true\n"
        "        language: system\n        pass_filenames: false\n"
        "      - id: mdformat\n        name: mdformat\n        entry: mdformat --wrap 120\n"
        "        language: system\n        types: [markdown]\n",
    )
    (worktree / "CHANGELOG.md").write_text("# Changelog\n\n<!-- towncrier release notes start -->\n")
    (worktree / "changelog.d").mkdir()
    run(worktree, "git", "add", ".")
    run(worktree, "git", "commit", "-m", "Initial files")
    run(worktree, "git", "tag", "0.1.0")
    (worktree / "changelog.d/+feature.feature.md").write_text("Add a new feature.\n")
    run(worktree, "git", "add", ".")
    run(worktree, "git", "commit", "-m", "Add feature (#2)")
    run(worktree, "git", "push", "-u", "origin", "main", "--tags")
    server, environment = github_api
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    def associated_pulls(request: Request) -> Response:
        query = request.get_json()["query"]
        commits = (part.split('"', 1)[0] for part in query.split('object(oid: "')[1:])
        return Response(
            json.dumps(
                {
                    "data": {
                        "repository": {
                            f"c{index}": {
                                "associatedPullRequests": {
                                    "nodes": [
                                        {
                                            "number": int(environment.get("TEST_PULL_NUMBER", "2")),
                                            "mergedAt": "2026-10-22T00:00:00Z",
                                            "mergeCommit": {"oid": commit},
                                            "author": {"login": "gaborbernat", "__typename": "User"},
                                        }
                                    ]
                                }
                            }
                            for index, commit in enumerate(commits)
                        }
                    }
                }
            ),
            mimetype="application/json",
        )

    server.expect_request("/api/graphql", method="POST").respond_with_handler(associated_pulls)
    return worktree


@pytest.fixture
def source_project(repository: Path) -> Path:
    project = repository / "pyproject.toml"
    project.write_text(
        project.read_text()
        + dedent(
            """
            [project]
            name = "fixture"
            version = "0.2.0"
            requires-python = ">=3.15"

            [build-system]
            requires = ["hatchling"]
            build-backend = "hatchling.build"
            """,
        ),
    )
    package = repository / "src/fixture"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Fixture package."""\n')
    return repository


@pytest.fixture
def build_repository(source_project: Path, nab_executable: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    project = source_project / "pyproject.toml"
    release_requirement = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())[
        "dependency-groups"
    ]["release-notes"][0]
    project.write_text(
        project.read_text()
        + f"\n[dependency-groups]\nrelease-notes = [{json.dumps(release_requirement)}]\n"
        + '\n[tool.nab]\nbase-group = "project-runtime"\nbuild-group = "build"\n'
    )
    run(
        source_project,
        str(nab_executable),
        "lock",
        "--no-cache",
        "--groups",
        "release-notes",
        "--output",
        "pylock.toml",
    )
    run(source_project, "git", "add", ".")
    run(source_project, "git", "commit", "-m", "Add package source")
    run(source_project, "git", "push", "origin", "main")
    return source_project


def action(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    name: str,
    captured_outputs: dict[str, str] | None = None,
    /,
    *,
    version: str,
    **extra_env: str,
) -> subprocess.CompletedProcess[str]:
    if (
        name in {"install-locked-tools", "export-build-constraints"}
        and (repository / "pylock.toml").exists()
        and not (repository / "pyproject.toml").exists()
    ):
        (repository / "pyproject.toml").write_text('[tool.nab]\nuploaded-prior-to = "P7D"\n')
    action_config = yaml.safe_load((Path(__file__).resolve().parents[1] / name / "action.yml").read_text())
    head = run(repository, "git", "rev-parse", "HEAD").stdout.strip() if (repository / ".git").exists() else "0" * 40
    input_values = {
        "VERSION": version,
        "BUMP": "auto",
        "TAG_PREFIX": "",
        "CHANGELOG_PREFIX": "",
        "CHANGELOG": "CHANGELOG.md",
        "FRAGMENTS": "changelog.d",
        "FORMAT": action_config.get("inputs", {}).get("format", {}).get("default", "none"),
        "PATCH": str(tmp_path / "release.patch"),
        "EXPECTED_SHA": head,
        "CHECKS": "true",
        "BRANCH": "main",
        "REMOTE": "origin",
        "ANNOTATED": "false",
        "ARTIFACT_URL": "",
        "ARTIFACT_LABEL": "PyPI release",
        "LOCK": "pylock.toml",
        "GENERATED_NOTES": "",
        "MODE": "complete",
        "RUN_ID": "42",
        "WORKFLOW_PATH": ".github/workflows/check.yaml",
    } | extra_env
    input_values["REPOSITORY"] = extra_env.get("REPOSITORY", "tox-dev/fixture")
    inputs = _inputs(action_config, input_values)
    input_names = {input_name.replace("-", "_").upper() for input_name in action_config.get("inputs", {})}
    environment: dict[str, str] = (
        _safe_environment()
        | {
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GITHUB_PATH": str(tmp_path / "github-path"),
            "GITHUB_REPOSITORY": "tox-dev/fixture",
            "GITHUB_SHA": head,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[1] / name),
        }
        | {key: value for key, value in extra_env.items() if key not in input_names}
    )
    if "PATH" not in extra_env:
        environment["PATH"] = _tools_path(environment)
    result, outputs = _run_action(repository, action_scripts, name, environment, inputs)
    if captured_outputs is not None:
        captured_outputs.update(outputs)
    return result


def _run_action(
    repository: Path,
    action_scripts: Path,
    name: str,
    environment: dict[str, str],
    inputs: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    source = Path(__file__).resolve().parents[1]
    action_config = yaml.safe_load((source / name / "action.yml").read_text())
    stdout: list[str] = []
    stderr: list[str] = []
    action_steps = action_config["runs"]["steps"]
    step_outputs: dict[str, dict[str, str]] = {}
    github_bash: Final[tuple[str, ...]] = ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")
    command = list(github_bash)
    for index, step in enumerate(action_steps):
        if (condition := step.get("if")) is not None and not _condition(condition, environment, inputs, step_outputs):
            continue
        if (used := step.get("uses")) is not None:
            if used.startswith("astral-sh/setup-uv@"):
                continue
            if not used.startswith("$/"):
                msg = f"unsupported nested action: {used}"
                raise ValueError(msg)
            nested_name = used.removeprefix("$/")
            nested_config = yaml.safe_load((source / nested_name / "action.yml").read_text())
            nested_inputs = {
                input_name: _step_value(
                    str(step.get("with", {}).get(input_name, definition.get("default", ""))),
                    environment,
                    inputs,
                    step_outputs,
                )
                for input_name, definition in nested_config.get("inputs", {}).items()
            }
            result, outputs = _run_action(
                repository,
                action_scripts,
                nested_name,
                environment
                | {
                    "GITHUB_ACTION_PATH": str(source / nested_name),
                    "GITHUB_OUTPUT": str(Path(environment["RUNNER_TEMP"]) / f"nested-{name}-{index}-output"),
                },
                nested_inputs,
            )
            stdout.append(result.stdout)
            stderr.append(result.stderr)
            if result.returncode:
                return subprocess.CompletedProcess(result.args, result.returncode, "".join(stdout), "".join(stderr)), {}
            if step_id := step.get("id"):
                step_outputs[step_id] = outputs
            continue
        if "run" not in step:
            continue
        script = action_scripts / f"{name}-{index}.sh"
        command = [*github_bash, str(script)]
        output_path = Path(environment["GITHUB_OUTPUT"])
        prior_output = output_path.read_text() if output_path.exists() else ""
        step_environment: dict[str, str] = environment | {
            variable: _step_value(str(value), environment, inputs, step_outputs)
            for variable, value in (step.get("env") or {}).items()
        }
        result = subprocess.run(
            command,
            cwd=repository / _step_value(str(step.get("working-directory", ".")), environment, inputs, step_outputs),
            env=step_environment,
            text=True,
            capture_output=True,
            check=False,
        )
        stdout.append(result.stdout)
        stderr.append(result.stderr)
        if result.returncode:
            return subprocess.CompletedProcess(command, result.returncode, "".join(stdout), "".join(stderr)), {}
        if step_id := step.get("id"):
            current_output = output_path.read_text() if output_path.exists() else ""
            assert current_output.startswith(prior_output)
            step_outputs[step_id] = dict(
                line.split("=", 1) for line in current_output[len(prior_output) :].splitlines()
            )
    outputs: dict[str, str] = {
        output_name: _step_value(definition["value"], environment, inputs, step_outputs)
        for output_name, definition in action_config.get("outputs", {}).items()
    }
    return subprocess.CompletedProcess(command, 0, "".join(stdout), "".join(stderr)), outputs


def run(directory: Path, *command: str) -> subprocess.CompletedProcess[str]:
    environment = _safe_environment()
    result = subprocess.run(
        command,
        cwd=directory,
        env=environment | {"PATH": _tools_path(environment)},
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        msg = f"{' '.join(command)} failed with exit code {result.returncode}:\n{result.stderr}"
        raise AssertionError(msg)
    return result


def _tools_path(environment: dict[str, str]) -> str:
    return f"{Path(__file__).resolve().parents[1] / '.release-tools/bin'}:{Path(sys.executable).parent}:{environment['PATH']}"


def _condition(
    expression: str,
    environment: dict[str, str],
    inputs: dict[str, str],
    step_outputs: dict[str, dict[str, str]],
) -> bool:
    if " || " in expression:
        return any(_condition(part, environment, inputs, step_outputs) for part in expression.split(" || "))
    if " && " in expression:
        return all(_condition(part, environment, inputs, step_outputs) for part in expression.split(" && "))
    if expression.startswith("endsWith(") and expression.endswith(")"):
        arguments = expression.removeprefix("endsWith(").removesuffix(")").split(", ", 1)
        return _expression(arguments[0], environment, inputs, step_outputs).endswith(arguments[1].strip("'"))
    for operator in (" == ", " != "):
        if operator in expression:
            left, right = expression.split(operator, 1)
            equal = _expression(left, environment, inputs, step_outputs) == right.strip("'")
            return equal if operator == " == " else not equal
    msg = f"unsupported GitHub step condition: {expression}"
    raise ValueError(msg)


def _safe_environment() -> dict[str, str]:
    environment = {
        name: os.environ[name]
        for name in (
            "HOME",
            "LANG",
            "PATH",
            "UV_CACHE_DIR",
            "UV_INDEX_URL",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "SSL_CERT_FILE",
            "GH_HOST",
            "GH_ENTERPRISE_TOKEN",
            "COVERAGE_PROCESS_START",
            "COVERAGE_PROCESS_CONFIG",
            "GW_PYPI_METADATA_FILE",
        )
        if name in os.environ
    }
    if "GW_PYPI_METADATA_FILE" in environment:
        environment["PYTHONPATH"] = str(Path(__file__).parent / "coverage_bootstrap")
    if "COVERAGE_PROCESS_CONFIG" in environment or "COVERAGE_PROCESS_START" in environment:
        import coverage

        environment["GW_COVERAGE_SITE_PACKAGES"] = str(Path(coverage.__file__).parent.parent)
    return environment


def _inputs(
    configuration: Mapping[str, Mapping[str, Mapping[str, str | bool]]], environment: dict[str, str]
) -> dict[str, str]:
    return {
        name: environment.get(name.replace("-", "_").upper(), _input_default(definition.get("default", "")))
        for name, definition in configuration.get("inputs", {}).items()
    }


def _input_default(value: str | bool) -> str:
    return str(value).lower() if isinstance(value, bool) else value


def _step_value(
    value: str,
    environment: dict[str, str],
    inputs: dict[str, str],
    step_outputs: dict[str, dict[str, str]],
) -> str:
    parts: list[str] = []
    remainder = value
    while (start := remainder.find("${{")) != -1:
        end = remainder.find("}}", start + 3)
        if end == -1:
            msg = f"unterminated GitHub expression: {value}"
            raise ValueError(msg)
        parts.append(remainder[:start])
        parts.append(_expression(remainder[start + 3 : end].strip(), environment, inputs, step_outputs))
        remainder = remainder[end + 2 :]
    return "".join([*parts, remainder])


def _expression(
    expression: str,
    environment: dict[str, str],
    inputs: dict[str, str],
    step_outputs: dict[str, dict[str, str]],
) -> str:
    if " && " in expression and " || " in expression:
        condition, alternatives = expression.split(" && ", 1)
        true_value, false_value = alternatives.split(" || ", 1)
        return (true_value if _condition(condition, environment, inputs, step_outputs) else false_value).strip("'")
    if " == " in expression or " != " in expression:
        return str(_condition(expression, environment, inputs, step_outputs)).lower()
    if " || " in expression:
        return next(
            (
                value
                for part in expression.split(" || ")
                if (value := _expression(part, environment, inputs, step_outputs))
            ),
            "",
        )
    if expression.startswith("inputs."):
        return inputs[expression.removeprefix("inputs.")]
    if expression.startswith("steps."):
        _, step_id, _, output_name = expression.split(".")
        return step_outputs.get(step_id, {}).get(output_name, "")
    if expression == "runner.temp":
        return environment["RUNNER_TEMP"]
    if expression == "github.repository":
        return environment["GITHUB_REPOSITORY"]
    if expression == "github.base_ref":
        return environment.get("BASE_REF", "")
    if expression == "github.event.pull_request.number":
        return environment.get("GITHUB_EVENT_PULL_REQUEST_NUMBER", "")
    if expression == "github.token":
        return environment.get("GH_TOKEN", environment.get("GH_ENTERPRISE_TOKEN", ""))
    if expression == "github.event.pull_request.user.type":
        return "Bot" if environment.get("BOT_AUTHOR") == "true" else "User"
    if expression == "contains(github.event.pull_request.labels.*.name, 'skip news')":
        return environment.get("SKIP_NEWS", "false")
    msg = f"unsupported GitHub step environment: {expression}"
    raise ValueError(msg)


__all__ = [
    "action",
    "run",
]
