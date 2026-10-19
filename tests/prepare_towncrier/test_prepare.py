from __future__ import annotations

import os
from datetime import date
lazy from pathlib import Path

import pytest
from conftest import action, run


def test_prepare_builds_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0")
    assert result.returncode == 0, result.stderr
    assert "version=0.2.0" in (tmp_path / "output").read_text()
    assert "0.2.0" in (tmp_path / "release.patch").read_text()


def test_prepare_custom_changelog_and_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    project = repository / "pyproject.toml"
    project.write_text(project.read_text().replace("CHANGELOG.md", "HISTORY.md"))
    (repository / "CHANGELOG.md").rename(repository / "HISTORY.md")
    run(repository, "git", "add", "-A")
    run(repository, "git", "commit", "-m", "Use a custom changelog")
    run(repository, "git", "push", "origin", "main")
    patch = tmp_path / "custom.patch"
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="0.2.0",
        CHANGELOG="HISTORY.md",
        PATCH=str(patch),
    )
    assert result.returncode == 0, result.stderr
    assert "0.2.0" in (repository / "HISTORY.md").read_text()
    assert "HISTORY.md" in patch.read_text()


def test_prepare_custom_fragment_directory(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    project = repository / "pyproject.toml"
    project.write_text(project.read_text().replace('directory = "changelog.d"', 'directory = "docs/changelog.d"'))
    (repository / "docs").mkdir()
    (repository / "changelog.d").rename(repository / "docs/changelog.d")
    run(repository, "git", "add", "-A")
    run(repository, "git", "commit", "-m", "Move release fragments")
    run(repository, "git", "push", "origin", "main")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="",
        FRAGMENTS="docs/changelog.d",
        LINK_FRAGMENTS="true",
    )
    assert result.returncode == 0, result.stderr
    assert "version=0.2.0" in (tmp_path / "output").read_text()
    assert "Add a new feature." in (repository / "CHANGELOG.md").read_text()
    assert "docs/changelog.d/feature.feature.md" in (tmp_path / "release.patch").read_text()


def test_prepare_renders_github_notes(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    result = run(
        repository,
        "release-creator",
        "notes",
        "--changelog",
        "CHANGELOG.md",
        "--tag",
        "0.2.0",
        "--repository",
        "tox-dev/fixture",
    )
    assert "### Features" in result.stdout


def test_prepare_rejects_dirty_checkout(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "CHANGELOG.md").write_text("changed\n")
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0")
    assert result.returncode != 0
    assert "clean checkout" in result.stderr


@pytest.mark.parametrize(
    ("option", "value", "error"),
    [
        pytest.param("FORMAT", "rst", "format must be markdown or none", id="format"),
        pytest.param(
            "LINK_FRAGMENTS",
            "maybe",
            "link-fragments must be true or false",
            id="fragment-linking",
        ),
    ],
)
def test_prepare_rejects_invalid_option(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    option: str,
    value: str,
    error: str,
) -> None:
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="0.2.0",
        **{option: value},
    )
    assert result.returncode != 0
    assert error in result.stderr


@pytest.mark.parametrize(
    ("bump", "expected"),
    [
        pytest.param("auto", "0.2.0", id="auto"),
        pytest.param("major", "1.0.0", id="major"),
        pytest.param("minor", "0.2.0", id="minor"),
        pytest.param("patch", "0.1.1", id="patch"),
        pytest.param("calver", f"{date.today().year}.{date.today().month}.0", id="calver"),
    ],
)
def test_prepare_selects_version(
    repository: Path, tmp_path: Path, action_scripts: Path, bump: str, expected: str
) -> None:
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version="", BUMP=bump)
    assert result.returncode == 0, result.stderr
    assert f"version={expected}" in (tmp_path / "output").read_text()


@pytest.mark.parametrize("version", [pytest.param("0.1.0", id="existing"), pytest.param("0.0.1", id="older")])
def test_prepare_rejects_reused_version(repository: Path, tmp_path: Path, action_scripts: Path, version: str) -> None:
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version=version)
    assert result.returncode != 0
    assert "must be newer" in result.stderr
    assert not (tmp_path / "release.patch").exists()


def test_prepare_links_named_fragments(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="0.2.0",
        LINK_FRAGMENTS="true",
    )
    assert result.returncode == 0, result.stderr
    assert "Add a new feature." in (repository / "CHANGELOG.md").read_text()


def test_prepare_rejects_untracked_output(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: release-check\n"
        "        name: release-check\n        entry: bash -c 'touch extra-output'\n"
        "        language: system\n        pass_filenames: false\n",
    )
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Write untracked output")
    run(repository, "git", "push", "origin", "main")
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0")
    assert result.returncode != 0
    assert "created untracked files" in result.stderr


def test_prepare_rejects_empty_release(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "changelog.d/feature.feature.md").unlink()
    run(repository, "git", "add", "-u")
    run(repository, "git", "commit", "-m", "Remove unused fragment")
    run(repository, "git", "push", "origin", "main")
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0")
    assert result.returncode != 0
    assert "has no release notes" in result.stderr


def test_prepare_rejects_empty_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "CHANGELOG.md").write_text(
        "# Changelog\n\n<!-- towncrier release notes start -->\n\n"
        '<a name="release-0-2-0"></a>\n\n## 0.2.0 (2026-10-19)\n\n### Added\n\n- Add a feature.\n',
    )
    run(repository, "git", "add", "CHANGELOG.md")
    run(repository, "git", "commit", "-m", "Record existing notes")
    run(repository, "git", "push", "origin", "main")
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "towncrier").symlink_to("/usr/bin/true")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="0.2.0",
        PATH=f"{tools}:{os.environ['PATH']}",
    )
    assert result.returncode != 0
    assert "produced no patch" in result.stderr


def test_prepare_formats_markdown(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: mdformat\n"
        "        name: mdformat\n        entry: mdformat --wrap 120\n"
        "        language: system\n        types: [markdown]\n",
    )
    (repository / "changelog.d/feature.feature.md").write_text("Add " + "a long sentence " * 15 + ".\n")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Set markdown hook")
    run(repository, "git", "push", "origin", "main")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="0.2.0",
        FORMAT="markdown",
    )
    assert result.returncode == 0, result.stderr
    changelog_lines = (repository / "CHANGELOG.md").read_text().splitlines()
    assert max(map(len, changelog_lines)) <= 120  # ruff: ignore[magic-value-comparison]  # Changelog width.
