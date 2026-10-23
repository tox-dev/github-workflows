from __future__ import annotations

import os
import ssl
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from textwrap import dedent
from typing import Final

import pytest
import trustme
import yaml
from pytest_httpserver import HTTPServer


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
    if system_certs := ssl.get_default_verify_paths().cafile:
        bundle.write_bytes(bundle.read_bytes() + Path(system_certs).read_bytes())
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
        "build-python-distribution",
        "validate-python-distribution",
        "render-release-notes",
        "select-previous-tag",
        "validate-news",
        "label-bot-news",
        "resolve-pr-from-run",
        "refresh-release-lock",
        "install-locked-tools",
        "install-lock-tools",
        "export-build-constraints",
        "read-towncrier-config",
        "refresh-hook-pins",
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
    fragment_commit = run(worktree, "git", "rev-parse", "HEAD").stdout.strip()
    for name in ("fixture", "github-workflows"):
        server.expect_request(
            f"/api/v3/repos/tox-dev/{name}/commits/{fragment_commit}/pulls",
            method="GET",
            query_string="per_page=100",
        ).respond_with_json(
            [{"number": 2, "merge_commit_sha": fragment_commit, "user": {"login": "gaborbernat", "type": "User"}}],
        )
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


def action(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    name: str,
    *,
    version: str,
    **extra_env: str,
) -> subprocess.CompletedProcess[str]:
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
        "EXPECTED_PATCH_SHA": "",
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
            "GITHUB_REPOSITORY": "tox-dev/fixture",
            "GITHUB_SHA": head,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[1] / name),
        }
        | {key: value for key, value in extra_env.items() if key not in input_names}
    )
    if "PATH" not in extra_env:
        environment["PATH"] = _tools_path(environment)
    result, _ = _run_action(repository, action_scripts, name, environment, inputs)
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
    return {
        name: os.environ[name]
        for name in (
            "HOME",
            "LANG",
            "PATH",
            "UV_CACHE_DIR",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "SSL_CERT_FILE",
            "GH_HOST",
            "GH_ENTERPRISE_TOKEN",
        )
        if name in os.environ
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
