from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import Path
from textwrap import dedent
from typing import Final

import certifi
import coverage
import pytest
import trustme
import yaml
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

CALLER: Final = Path(__file__).parent / "fixtures/caller"


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


@pytest.fixture
def caller(tmp_path: Path) -> Path:
    root = tmp_path / "caller"
    root.mkdir()
    for name in ("pylock.toml", "pyproject.toml"):
        shutil.copyfile(CALLER / name, root / name)
    return root


@pytest.fixture(scope="session")
def action_scripts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    source = Path(__file__).resolve().parents[1]
    scripts = tmp_path_factory.mktemp("action-steps")
    for action_name in (
        "prepare-towncrier",
        "cooled-prek",
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
def nab_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
    environment = tmp_path_factory.mktemp("nab-tools")
    subprocess.run(
        [str(Path(__file__).resolve().parents[1] / "tools/install_live_tools.sh"), str(environment), "nab>=0.0.22"],
        env=os.environ | {"EXCLUDE_NEWER": "7 days"},
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

    author = {"login": "gaborbernat", "__typename": "User"}

    def graphql(request: Request) -> Response:
        query = request.get_json()["query"]
        if 'object(oid: "' in query:
            commits = (part.split('"', 1)[0] for part in query.split('object(oid: "')[1:])
            data: dict[str, object] = {
                "repository": {
                    f"c{index}": {
                        "associatedPullRequests": {
                            "nodes": [
                                {
                                    "number": int(environment.get("TEST_PULL_NUMBER", "2")),
                                    "mergedAt": "2026-10-22T00:00:00Z",
                                    "mergeCommit": {
                                        "oid": commit,
                                        "authors": {
                                            "nodes": [
                                                {"name": "Release test", "email": "a@example.org", "user": author}
                                            ]
                                        },
                                    },
                                    "author": author,
                                }
                            ]
                        }
                    }
                    for index, commit in enumerate(commits)
                }
            }
        elif "pullRequest(number: " in query:
            numbers = re.findall(r"p(\d+): pullRequest", query)
            data = {
                "repository": {
                    f"p{number}": {"number": int(number), "mergedAt": "2026-10-22T00:00:00Z", "author": author}
                    for number in numbers
                }
            }
        else:
            data = {
                alias: {"issueCount": int(environment.get("TEST_PRIOR_PULLS", "0"))}
                for alias in re.findall(r"(s\d+): search", query)
            }
        return Response(json.dumps({"data": data}), mimetype="application/json")

    server.expect_request("/api/graphql", method="POST").respond_with_handler(graphql)
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
    release_requirement = tomllib.loads((CALLER / "pyproject.toml").read_text())["dependency-groups"]["release-notes"][
        0
    ]
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
    if name == "validate-release-patch" and (prepared := tmp_path / "release.patch").exists():
        (tmp_path / "release-patch").mkdir(exist_ok=True)
        shutil.copyfile(prepared, tmp_path / "release-patch/release.patch")
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
        "CHECKS": "true",
        "BRANCH": "main",
        "ANNOTATED": "false",
        "ARTIFACT_URL": "",
        "ARTIFACT_LABEL": "PyPI release",
        "LOCK": "pylock.toml",
        "MODE": "complete",
    } | extra_env
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
            if used.startswith("actions/upload-artifact@"):
                continue
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
    for operator in (" == ", " != "):
        if operator in expression:
            left, right = expression.split(operator, 1)
            equal = _expression(left, environment, inputs, step_outputs) == right.strip("'")
            return equal if operator == " == " else not equal
    raise ValueError(f"unsupported GitHub step condition: {expression}")  # pragma: no cover - new syntax only


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
        )
        if name in os.environ
    }
    return environment | {
        "PYTHONPATH": str(Path(__file__).parent / "coverage_bootstrap"),
        "GW_COVERAGE_SITE_PACKAGES": str(Path(coverage.__file__).parent.parent),
    }


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
            raise ValueError(f"unterminated GitHub expression: {value}")  # pragma: no cover - new syntax only
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
        return _expression(
            true_value if _condition(condition, environment, inputs, step_outputs) else false_value,
            environment,
            inputs,
            step_outputs,
        )
    if expression.startswith("'") and expression.endswith("'"):
        return expression[1:-1]
    if " == " in expression or " != " in expression:
        return str(_condition(expression, environment, inputs, step_outputs)).lower()
    if expression.startswith("inputs."):
        return inputs[expression.removeprefix("inputs.")]
    if expression.startswith("steps."):
        _, step_id, _, output_name = expression.split(".")
        return step_outputs.get(step_id, {}).get(output_name, "")
    if expression == "github.repository":
        return environment["GITHUB_REPOSITORY"]
    if expression == "github.base_ref":
        return environment.get("BASE_REF", "")
    if expression == "github.token":
        return environment.get("GH_TOKEN", environment.get("GH_ENTERPRISE_TOKEN", ""))
    if expression == "github.event.pull_request.user.type":
        return "Bot" if environment.get("BOT_AUTHOR") == "true" else "User"
    if expression == "contains(github.event.pull_request.labels.*.name, 'skip news')":
        return environment.get("SKIP_NEWS", "false")
    raise ValueError(f"unsupported GitHub step environment: {expression}")  # pragma: no cover - new syntax only


__all__ = [
    "CALLER",
    "action",
    "run",
]
