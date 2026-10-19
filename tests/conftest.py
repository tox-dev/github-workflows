from __future__ import annotations

import os
import subprocess  # ruff: ignore[suspicious-subprocess-import]  # Run release scripts in real Git repositories.
from pathlib import Path
from uuid import uuid4

import pytest


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
    (worktree / "changelog.d/feature.feature.md").write_text("Add a new feature.\n")
    run(worktree, "git", "add", ".")
    run(worktree, "git", "commit", "-m", "Add feature")
    run(worktree, "git", "push", "-u", "origin", "main", "--tags")
    return worktree


def action(
    repository: Path, tmp_path: Path, script: str, *, version: str, **extra_env: str
) -> subprocess.CompletedProcess[str]:
    source = Path(__file__).resolve().parents[1]
    environment = (
        os.environ
        | {
            "VERSION": version,
            "BUMP": "auto",
            "CHANGELOG": "CHANGELOG.md",
            "FRAGMENTS": "changelog.d",
            "FORMAT": "none",
            "LINK_FRAGMENTS": "false",
            "PATCH": str(tmp_path / "release.patch"),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GITHUB_REPOSITORY": "tox-dev/fixture",
            "GITHUB_SHA": run(repository, "git", "rev-parse", "HEAD").stdout.strip(),
            "EXPECTED_SHA": run(repository, "git", "rev-parse", "HEAD").stdout.strip(),
            "HEADING_PREFIX": "## ",
            "BRANCH": "main",
            "REMOTE": "origin",
            "ANNOTATED": "false",
        }
        | extra_env
    )
    command = ["bash", str(source / script)]
    if coverage_binary := os.environ.get("KCOV_BIN"):
        Path(os.environ["KCOV_OUTPUT"]).mkdir(parents=True, exist_ok=True)
        command = [
            coverage_binary,
            f"--include-path={source}",
            str(Path(os.environ["KCOV_OUTPUT"]) / uuid4().hex),
            str(source / script),
        ]
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # Use explicit argv.
        command,  # Run the checked-in script.
        cwd=repository,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def run(directory: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # Use explicit argv.
        command, cwd=directory, text=True, capture_output=True, check=True
    )


__all__ = [
    "action",
    "run",
]
