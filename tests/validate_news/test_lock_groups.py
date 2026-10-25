from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from tools.lock_groups import validate_workspace_sources

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def _producer(lock: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOLS / "lock_groups.py"), str(lock)], capture_output=True, text=True, check=False
    )


def test_lock_groups_accepts_release_creator_lock(tmp_path: Path) -> None:
    lock = tmp_path / "pylock.toml"
    lock.write_text("[tool.release-creator]\ncreated-at = 2026-10-24T00:00:00Z\n")

    result = _producer(lock)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param('[tool.nab]\ncommand-line = ["nab", "lock"]\n', "must come from release-creator locks", id="nab"),
        pytest.param('lock-version = "1.0"\n', "no recognized producer", id="unknown"),
    ],
)
def test_lock_groups_rejects_other_producer(tmp_path: Path, content: str, message: str) -> None:
    lock = tmp_path / "pylock.toml"
    lock.write_text(content)

    result = _producer(lock)

    assert result.returncode != 0
    assert message in result.stderr


def test_lock_groups_import_has_no_cli_side_effect(capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(str(TOOLS / "lock_groups.py"), run_name="lock_groups")

    assert capsys.readouterr() == ("", "")


def test_workspace_sources_accept_declared_member(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "bare"\n[tool.uv.workspace]\nmembers = ["packages/*"]\nexclude = ["packages/unused"]\n'
    )
    for name in ("meta", "other", "unused"):
        member = tmp_path / "packages" / name
        member.mkdir(parents=True)
        (member / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\n'
            + ("[tool.uv.sources]\nbare = { workspace = true }\n" if name == "meta" else "")
            + ("[tool.uv.sources]\nmissing = { workspace = true }\n" if name == "unused" else "")
        )
    (tmp_path / "packages" / "notes.txt").write_text("not a project")

    validate_workspace_sources(tmp_path / "pyproject.toml")


def test_workspace_sources_reject_invalid_patterns(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.uv.workspace]\nmembers = [1]\n")

    with pytest.raises(ValueError, match="workspace patterns must be strings"):
        validate_workspace_sources(tmp_path / "pyproject.toml")


def test_workspace_sources_reject_member_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["external"]\n')
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "pyproject.toml").write_text("[dependency-groups]\nrelease-hidden = []\n")
    (project / "external").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="workspace members must be inside the project"):
        validate_workspace_sources(project / "pyproject.toml")


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("missing = { workspace = true }", id="undeclared-member"),
        pytest.param('bare = { git = "https://example.org/bare" }', id="git-source"),
        pytest.param('bare = { workspace = true, git = "https://example.org/bare" }', id="mixed-source"),
    ],
)
def test_lock_check_rejects_unapproved_workspace_sources(tmp_path: Path, source: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "bare"\nrequires-python = ">=3.15"\n'
        '[tool.uv.workspace]\nmembers = ["meta"]\n[dependency-groups]\nrelease-news = []\n'
    )
    member = tmp_path / "meta"
    member.mkdir()
    (member / "pyproject.toml").write_text(
        f'[project]\nname = "meta"\nrequires-python = ">=3.15"\n[tool.uv.sources]\n{source}\n'
    )
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'lock-version = "1.0"\ncreated-by = "release-creator"\nrequires-python = ">=3.15"\n'
        'dependency-groups = ["project-runtime", "release-news"]\n'
        "default-groups = []\npackages = []\n[tool.release-creator]\ncreated-at = 2026-10-20T00:00:00Z\n"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "check_lock_groups.py"),
            str(lock),
            "release-news",
            "--project",
            str(tmp_path / "pyproject.toml"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "uv source must name a workspace project" in result.stderr
