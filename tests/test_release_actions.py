from __future__ import annotations

import os
import subprocess  # ruff: ignore[suspicious-subprocess-import]  # Exercise the release scripts in real Git repositories.
from pathlib import Path

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
        'filename = "docs/changelog.md"\ntemplate = "release_creator.fragments:template.jinja2"\n'
        'title_format = false\ntype = [{ directory = "feature", name = "Added", showcontent = true }]\n',
    )
    (worktree / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: release-check\n"
        "        name: release-check\n        entry: bash -c true\n"
        "        language: system\n        pass_filenames: false\n",
    )
    (worktree / "docs").mkdir()
    (worktree / "docs/changelog.md").write_text("# Changelog\n\n<!-- towncrier release notes start -->\n")
    (worktree / "changelog.d").mkdir()
    run(worktree, "git", "add", ".")
    run(worktree, "git", "commit", "-m", "Initial files")
    run(worktree, "git", "tag", "0.1.0")
    (worktree / "changelog.d/feature.feature.md").write_text("Add a new feature.\n")
    run(worktree, "git", "add", ".")
    run(worktree, "git", "commit", "-m", "Add feature")
    run(worktree, "git", "push", "-u", "origin", "main", "--tags")
    return worktree


def test_prepare_builds_patch(repository: Path, tmp_path: Path) -> None:
    result = action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0")
    assert result.returncode == 0, result.stderr
    assert "version=0.2.0" in (tmp_path / "output").read_text()
    assert "0.2.0" in (tmp_path / "release.patch").read_text()


def test_prepare_renders_github_notes(repository: Path, tmp_path: Path) -> None:
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    result = run(
        repository,
        "release-creator",
        "notes",
        "--changelog",
        "docs/changelog.md",
        "--tag",
        "0.2.0",
        "--repository",
        "tox-dev/fixture",
    )
    assert "### Features" in result.stdout


def test_prepare_rejects_dirty_checkout(repository: Path, tmp_path: Path) -> None:
    (repository / "docs/changelog.md").write_text("changed\n")
    result = action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0")
    assert result.returncode != 0
    assert "clean checkout" in result.stderr


def test_prepare_selects_minor_from_feature(repository: Path, tmp_path: Path) -> None:
    result = action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="")
    assert result.returncode == 0, result.stderr
    assert "version=0.2.0" in (tmp_path / "output").read_text()


def test_prepare_formats_markdown(repository: Path, tmp_path: Path) -> None:
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: mdformat\n"
        "        name: mdformat\n        entry: mdformat --wrap 120\n"
        "        language: system\n        types: [markdown]\n",
    )
    (repository / "changelog.d/feature.feature.md").write_text("Add " + "a long sentence " * 15 + ".\n")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Set markdown hook")
    run(repository, "git", "push", "origin", "main")
    result = action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0", FORMAT="markdown")
    assert result.returncode == 0, result.stderr
    assert max(map(len, (repository / "docs/changelog.md").read_text().splitlines())) <= 120  # ruff: ignore[magic-value-comparison]  # Contract width.


def test_validate_applies_patch(repository: Path, tmp_path: Path) -> None:
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0")
    assert result.returncode == 0, result.stderr
    assert "0.2.0" in (repository / "docs/changelog.md").read_text()
    assert run(repository, "git", "diff", "--cached", "--name-only").stdout.strip()


def test_validate_rejects_stale_branch(repository: Path, tmp_path: Path) -> None:
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository,
        tmp_path,
        "validate-release-patch/validate.sh",
        version="0.2.0",
        EXPECTED_SHA="0000000000000000000000000000000000000000",
    )
    assert result.returncode != 0
    assert "changed during release preparation" in result.stderr


def test_validate_rejects_unexpected_path(repository: Path, tmp_path: Path) -> None:
    (repository / "pyproject.toml").write_text((repository / "pyproject.toml").read_text() + "\n# changed\n")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "--binary").stdout)
    run(repository, "git", "restore", ".")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0")
    assert result.returncode != 0
    assert "unexpected release path" in result.stderr


def test_validate_rejects_missing_heading(repository: Path, tmp_path: Path) -> None:
    (repository / "docs/changelog.md").write_text("# Changelog\n\nOther notes.\n")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "--binary").stdout)
    run(repository, "git", "restore", ".")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0")
    assert result.returncode != 0
    assert "has no section" in result.stderr


def test_validate_rejects_embedded_heading(repository: Path, tmp_path: Path) -> None:
    (repository / "docs/changelog.md").write_text("# Changelog\n\n- Link to ## 0.2.0 (2026-10-19)\n")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "--binary").stdout)
    run(repository, "git", "restore", ".")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0")
    assert result.returncode != 0
    assert "has no section" in result.stderr


def test_validate_rejects_prek_changes(repository: Path, tmp_path: Path) -> None:
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: release-check\n"
        "        name: release-check\n"
        "        entry: bash -c 'if [[ $VALIDATE_REHEARSAL == 1 ]]; then printf changed >> docs/changelog.md; fi'\n"
        "        language: system\n        pass_filenames: false\n",
    )
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Check release tree")
    run(repository, "git", "push", "origin", "main")
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0", VALIDATE_REHEARSAL="1")
    assert result.returncode != 0
    assert "prek failed" in result.stderr


@pytest.mark.parametrize("annotated", [pytest.param("false", id="lightweight"), pytest.param("true", id="annotated")])
def test_commit_and_tag_pushes_atomically(repository: Path, tmp_path: Path, annotated: str) -> None:
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    assert action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0").returncode == 0
    gh = tmp_path / "gh"
    gh.write_text('#!/usr/bin/env bash\nif [[ "$1" == api ]]; then echo 123; fi\n')
    gh.chmod(0o755)
    result = action(
        repository,
        tmp_path,
        "commit-and-tag/commit.sh",
        version="0.2.0",
        APP_SLUG="release-test",
        GH_TOKEN="test-token",  # ruff: ignore[hardcoded-password-func-arg]  # Local Git fixture never sends this token.
        MESSAGE="release 0.2.0",
        ANNOTATED=annotated,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
    )
    assert result.returncode == 0, result.stderr
    assert run(repository, "git", "ls-remote", "origin", "refs/tags/0.2.0").stdout.strip()
    assert run(repository, "git", "cat-file", "-t", "refs/tags/0.2.0").stdout.strip() == (
        "tag" if annotated == "true" else "commit"
    )


def test_commit_and_tag_rejects_invalid_tag(repository: Path, tmp_path: Path) -> None:
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    run(repository, "git", "add", "docs/changelog.md")
    original_head = run(repository, "git", "rev-parse", "HEAD").stdout
    result = action(repository, tmp_path, "commit-and-tag/commit.sh", version="bad tag")
    assert result.returncode != 0
    assert "invalid release tag" in result.stderr
    assert run(repository, "git", "rev-parse", "HEAD").stdout == original_head


def action(
    repository: Path, tmp_path: Path, script: str, *, version: str, **extra_env: str
) -> subprocess.CompletedProcess[str]:
    source = Path(__file__).resolve().parents[1]
    environment = (
        os.environ
        | {
            "VERSION": version,
            "BUMP": "auto",
            "CHANGELOG": "docs/changelog.md",
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
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # The script path and environment come from this test.
        ["bash", str(source / script)],  # ruff: ignore[start-process-with-partial-path]  # Bash runs the checked-in release script.
        cwd=repository,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def run(directory: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # All commands are supplied by these tests.
        command, cwd=directory, text=True, capture_output=True, check=True
    )
