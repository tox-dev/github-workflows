from __future__ import annotations

import os
import ssl
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
import trustme
import yaml
from pytest_httpserver import HTTPServer

_GITHUB_BASH: Final[tuple[str, ...]] = ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")


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
        "validate-news",
        "label-bot-news",
        "resolve-pr-from-run",
        "refresh-release-lock",
        "install-locked-tools",
        "refresh-hook-pins",
        "publish-github-release",
        "reconcile-pypi-artifacts",
        "select-pypi-artifacts",
        "verify-pypi-partitions",
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
def repository(tmp_path: Path) -> Path:
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
        "        language: system\n        pass_filenames: false\n",
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
    return worktree


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
    environment = (
        _safe_environment()
        | {
            "VERSION": version,
            "BUMP": "auto",
            "TAG_PREFIX": "",
            "CHANGELOG_PREFIX": "",
            "CHANGELOG": "CHANGELOG.md",
            "FRAGMENTS": "changelog.d",
            "FORMAT": action_config["inputs"].get("format", {}).get("default", "none"),
            "LINK_FRAGMENTS": "false",
            "NUMBERED_PRS": "false",
            "PATCH": str(tmp_path / "release.patch"),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GITHUB_REPOSITORY": "tox-dev/fixture",
            "GITHUB_SHA": run(repository, "git", "rev-parse", "HEAD").stdout.strip(),
            "EXPECTED_SHA": run(repository, "git", "rev-parse", "HEAD").stdout.strip(),
            "EXPECTED_PATCH_SHA": "",
            "CHECKS": "true",
            "BRANCH": "main",
            "REMOTE": "origin",
            "ANNOTATED": "false",
            "ARTIFACT_URL": "",
            "ARTIFACT_LABEL": "PyPI release",
            "PACKAGE": "",
            "LOCK": "pylock.toml",
            "GENERATED_NOTES": "",
            "ISSUE_ROLE": "issue",
            "MODE": "complete",
            "RUN_ID": "42",
            "WORKFLOW_PATH": ".github/workflows/check.yaml",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[1] / name),
        }
        | extra_env
    )
    environment["REPOSITORY"] = extra_env.get("REPOSITORY", environment["GITHUB_REPOSITORY"])
    environment["PATH"] = f"{Path(sys.executable).parent}:{environment['PATH']}"
    stdout = []
    stderr = []
    steps = action_config["runs"]["steps"]
    command = list(_GITHUB_BASH)
    for index, step in enumerate(steps):
        if step.get("uses") == "$/install-locked-tools":
            groups = environment.get("VALIDATION_GROUP", "release")
            if (
                name in {"build-python-distribution", "reconcile-pypi-artifacts"}
                and environment.get("LOCAL_TOOL_SOURCE") == "true"
            ):
                groups = "release build project-runtime"
            destination = {
                "build-python-distribution": "build-planner",
                "reconcile-pypi-artifacts": "pypi-reconcile",
                "validate-python-distribution": "package-validators",
            }[name]
            for install_index in range(3):
                command = [*_GITHUB_BASH, str(action_scripts / f"install-locked-tools-{install_index}.sh")]
                result = subprocess.run(
                    command,
                    cwd=repository,
                    env=environment
                    | {
                        "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[1] / "install-locked-tools"),
                        "DEPENDENCY_GROUPS": groups,
                        "VENV": str(tmp_path / destination),
                        "PYTHON_VERSION": "3.15"
                        if name == "build-python-distribution"
                        else environment["PYTHON_VERSION"],
                    },
                    text=True,
                    capture_output=True,
                    check=False,
                )
                stdout.append(result.stdout)
                stderr.append(result.stderr)
                if result.returncode:
                    return subprocess.CompletedProcess(command, result.returncode, "".join(stdout), "".join(stderr))
            continue
        if "run" not in step:
            continue
        script = action_scripts / f"{name}-{index}.sh"
        if (condition := step.get("if")) is not None and not _condition(condition, environment):
            continue
        command = [*_GITHUB_BASH, str(script)]
        result = subprocess.run(
            command,
            cwd=repository,
            env=environment
            | {
                variable: _step_value(value, variable, environment, action_config)
                for variable, value in step.get("env", {}).items()
            },
            text=True,
            capture_output=True,
            check=False,
        )
        stdout.append(result.stdout)
        stderr.append(result.stderr)
        if result.returncode:
            return subprocess.CompletedProcess(command, result.returncode, "".join(stdout), "".join(stderr))
        if name == "prepare-towncrier" and script.name == "prepare-towncrier-1.sh":
            environment["VERSION"] = (tmp_path / "output").read_text().split("version=", 1)[1].splitlines()[0]
        if name == "render-release-notes" and script.name == "render-release-notes-0.sh":
            environment["PREVIOUS"] = (tmp_path / "output").read_text().split("previous=", 1)[1].splitlines()[0]
    return subprocess.CompletedProcess(command, 0, "".join(stdout), "".join(stderr))


def run(directory: Path, *command: str) -> subprocess.CompletedProcess[str]:
    environment = _safe_environment()
    return subprocess.run(
        command,
        cwd=directory,
        env=environment | {"PATH": f"{Path(sys.executable).parent}:{environment['PATH']}"},
        text=True,
        capture_output=True,
        check=True,
    )


def _condition(expression: str, environment: dict[str, str]) -> bool:
    conditions = {
        "inputs.local-tool-source == 'true'": environment.get("LOCAL_TOOL_SOURCE") == "true",
        "inputs.bot-author == 'true' || github.event.pull_request.user.type == 'Bot'": environment.get("BOT_AUTHOR")
        == "true",
        "inputs.checks == 'true'": environment["CHECKS"] == "true",
        "inputs.format == 'rst'": environment["FORMAT"] == "rst",
        "endsWith(inputs.changelog, '.rst')": environment["CHANGELOG"].endswith(".rst"),
        "inputs.keep-uv-lock == 'true'": environment.get("KEEP_UV_LOCK") == "true",
        "inputs.build-constraints != ''": bool(environment.get("BUILD_CONSTRAINTS")),
        "inputs.mode == 'stage'": environment.get("MODE") == "stage",
        "inputs.mode == 'verify'": environment.get("MODE") == "verify",
        "steps.identity.outputs.bot == 'true'": environment.get("BOT_AUTHOR") == "true",
        "steps.identity.outputs.bot == 'true' && steps.identity.outputs.cooled != 'true'": environment.get("BOT_AUTHOR")
        == "true"
        and environment.get("COOLED") != "true",
    }
    if expression not in conditions:
        msg = f"unsupported GitHub step condition: {expression}"
        raise ValueError(msg)
    return conditions[expression]


def _safe_environment() -> dict[str, str]:
    return {
        name: os.environ[name]
        for name in ("HOME", "LANG", "PATH", "UV_CACHE_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE")
        if name in os.environ
    }


def _step_value(value: str, variable: str, environment: dict[str, str], action_config: dict[str, object]) -> str:
    if not value.startswith("${{ ") or not value.endswith(" }}"):
        return value
    for expression in value[4:-3].split(" || "):
        if expression.startswith("inputs."):
            defaults = action_config["inputs"]
            assert isinstance(defaults, dict)
            selected = defaults[expression[7:]]
            assert isinstance(selected, dict)
            resolved = environment.get(variable, str(selected.get("default", "")))
        elif expression == "github.repository":
            resolved = environment["GITHUB_REPOSITORY"]
        elif expression == "github.base_ref":
            resolved = environment.get("BASE_REF", "")
        elif expression == "github.token":
            resolved = environment.get("GH_TOKEN", environment.get("GH_ENTERPRISE_TOKEN", ""))
        elif expression == "contains(github.event.pull_request.labels.*.name, 'skip news')":
            resolved = environment.get("SKIP_NEWS", "false")
        elif expression == "github.event.pull_request.user.type == 'Bot'":
            resolved = environment.get("BOT_AUTHOR", "false")
        elif expression.startswith("steps."):
            resolved = environment.get(variable, "")
        else:
            msg = f"unsupported GitHub step environment: {expression}"
            raise ValueError(msg)
        if resolved:
            return resolved
    return ""


__all__ = [
    "action",
    "run",
]
