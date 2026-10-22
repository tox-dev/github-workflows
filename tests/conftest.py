from __future__ import annotations

import os
import ssl
import subprocess
from collections.abc import Iterator
from pathlib import Path

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
        "refresh-hook-pins",
        "publish-github-release",
        "reconcile-pypi-artifacts",
        "select-pypi-artifacts",
        "verify-pypi-partitions",
        "publish-jetbrains-marketplace",
        "sign-jetbrains-plugin",
        "check-hook-update-cooldown",
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
    environment = (
        os.environ
        | {
            "VERSION": version,
            "BUMP": "auto",
            "TAG_PREFIX": "",
            "CHANGELOG_PREFIX": "",
            "CHANGELOG": "CHANGELOG.md",
            "FRAGMENTS": "changelog.d",
            "FORMAT": "none",
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
        }
        | extra_env
    )
    environment["REPOSITORY"] = extra_env.get("REPOSITORY", environment["GITHUB_REPOSITORY"])
    if name == "label-bot-news" and environment.get("BOT_AUTHOR") != "true":
        return subprocess.CompletedProcess([], 0, "", "")
    stdout = []
    stderr = []
    scripts = sorted(action_scripts.glob(f"{name}-*.sh"), key=lambda path: int(path.stem.rsplit("-", 1)[1]))
    assert scripts, name
    steps = yaml.safe_load((Path(__file__).resolve().parents[1] / name / "action.yml").read_text())["runs"]["steps"]
    command = ["bash", str(scripts[0])]
    for index, script in enumerate(scripts):
        if steps[index].get("if") == "inputs.checks == 'true'" and environment["CHECKS"] == "false":
            continue
        if steps[index].get("if") == "inputs.format == 'rst'" and environment["FORMAT"] != "rst":
            continue
        if steps[index].get("if") == "endsWith(inputs.changelog, '.rst')" and not environment["CHANGELOG"].endswith(
            ".rst"
        ):
            continue
        command = ["bash", str(script)]
        result = subprocess.run(
            command,
            cwd=repository,
            env=environment,
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
    return subprocess.run(command, cwd=directory, text=True, capture_output=True, check=True)


__all__ = [
    "action",
    "run",
]
