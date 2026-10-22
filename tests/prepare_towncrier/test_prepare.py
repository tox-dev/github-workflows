from __future__ import annotations

import os
import subprocess
from datetime import date
from textwrap import dedent
lazy from pathlib import Path

import pytest
import yaml
from conftest import action, run
from pytest_httpserver import HTTPServer


def test_prepare_builds_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0")
    assert result.returncode == 0, result.stderr
    assert "version=0.2.0" in (tmp_path / "output").read_text()
    assert "0.2.0" in (tmp_path / "release.patch").read_text()


def test_prepare_workflow_preserves_unformatted_default() -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert workflow["on"]["workflow_call"]["inputs"]["format"]["default"] == "none"


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


def test_prepare_custom_fragment_directory(
    repository: Path, tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    project = repository / "pyproject.toml"
    project.write_text(project.read_text().replace('directory = "changelog.d"', 'directory = "docs/changelog.d"'))
    (repository / "docs").mkdir()
    (repository / "changelog.d").rename(repository / "docs/changelog.d")
    run(repository, "git", "add", "-A")
    run(repository, "git", "commit", "-m", "Move release fragments (#2)")
    run(repository, "git", "push", "origin", "main")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="",
        FRAGMENTS="docs/changelog.d",
        LINK_FRAGMENTS="true",
        REPOSITORY="tox-dev/github-workflows",
        **_author_lookup(github_api, 2),
    )
    assert result.returncode == 0, result.stderr
    assert "version=0.2.0" in (tmp_path / "output").read_text()
    assert (
        "Add a new feature ([#2](https://github.com/tox-dev/github-workflows/pull/2)) "
        "by [@gaborbernat](https://github.com/gaborbernat)."
    ) in (repository / "CHANGELOG.md").read_text()
    assert "docs/changelog.d/+feature.feature.md" in (tmp_path / "release.patch").read_text()


def test_prepare_renders_github_notes(
    repository: Path, tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="0.2.0",
        LINK_FRAGMENTS="true",
        GITHUB_REPOSITORY="tox-dev/github-workflows",
        **_author_lookup(github_api, 2),
    )
    assert result.returncode == 0, result.stderr
    result = run(
        repository,
        "release-creator",
        "notes",
        "--changelog",
        "CHANGELOG.md",
        "--tag",
        "0.2.0",
        "--repository",
        "tox-dev/github-workflows",
        "--previous",
        "0.1.0",
    )
    assert result.stdout == dedent(
        """\
        <a name="release-0-2-0-added"></a>

        ### Features

        - Add a new feature ([#2](https://github.com/tox-dev/github-workflows/pull/2)) by @gaborbernat.

        **Full Changelog**: https://github.com/tox-dev/github-workflows/compare/0.1.0...0.2.0
        """,
    )


def test_prepare_rejects_dirty_checkout(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "CHANGELOG.md").write_text("changed\n")
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0")
    assert result.returncode != 0
    assert "clean checkout" in result.stderr


@pytest.mark.parametrize(
    ("option", "value", "error"),
    [
        pytest.param("FORMAT", "yaml", "format must be markdown, rst, or none", id="format"),
        pytest.param(
            "LINK_FRAGMENTS",
            "maybe",
            "link-fragments must be true or false",
            id="fragment-linking",
        ),
        pytest.param("NUMBERED_PRS", "maybe", "numbered-prs must be true or false", id="numbered-prs"),
        pytest.param("CHANGELOG_PREFIX", "x", "changelog-prefix must be empty or v", id="changelog-prefix"),
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


def test_prepare_selects_prefixed_version(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version="", TAG_PREFIX="v")
    assert result.returncode == 0, result.stderr
    assert "version=v0.2.0" in (tmp_path / "output").read_text()
    assert "## 0.2.0 (" in (repository / "CHANGELOG.md").read_text()


def test_prepare_preserves_prefixed_changelog_heading(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(
        repository, tmp_path, action_scripts, "prepare-towncrier", version="", TAG_PREFIX="v", CHANGELOG_PREFIX="v"
    )
    assert result.returncode == 0, result.stderr
    assert "version=v0.2.0" in (tmp_path / "output").read_text()
    assert "## v0.2.0 (" in (repository / "CHANGELOG.md").read_text()


@pytest.mark.parametrize("version", [pytest.param("0.1.0", id="existing"), pytest.param("0.0.1", id="older")])
def test_prepare_rejects_reused_version(repository: Path, tmp_path: Path, action_scripts: Path, version: str) -> None:
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version=version)
    assert result.returncode != 0
    assert "must be newer" in result.stderr
    assert not (tmp_path / "release.patch").exists()


def test_prepare_links_named_fragments(
    repository: Path, tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="0.2.0",
        LINK_FRAGMENTS="true",
        GITHUB_REPOSITORY="tox-dev/github-workflows",
        **_author_lookup(github_api, 2),
    )
    assert result.returncode == 0, result.stderr
    assert (
        "Add a new feature ([#2](https://github.com/tox-dev/github-workflows/pull/2)) "
        "by [@gaborbernat](https://github.com/gaborbernat)."
    ) in (repository / "CHANGELOG.md").read_text()


def test_prepare_links_numbered_pull_requests(
    repository: Path, tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    run(repository, "git", "mv", "changelog.d/+feature.feature.md", "changelog.d/2.feature.md")
    run(repository, "git", "commit", "-m", "Use an original PR fragment")
    run(repository, "git", "push", "origin", "main")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="0.2.0",
        LINK_FRAGMENTS="true",
        NUMBERED_PRS="true",
        GITHUB_REPOSITORY="tox-dev/github-workflows",
        **_author_lookup(github_api, 2),
    )
    assert result.returncode == 0, result.stderr
    assert "[#2](https://github.com/tox-dev/github-workflows/pull/2)" in (repository / "CHANGELOG.md").read_text()


def test_prepare_keeps_default_numbered_issue(
    repository: Path, tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    run(repository, "git", "mv", "changelog.d/+feature.feature.md", "changelog.d/2.feature.md")
    run(repository, "git", "commit", "-m", "Backfill an earlier fragment (#3)")
    run(repository, "git", "push", "origin", "main")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="0.2.0",
        LINK_FRAGMENTS="true",
        GITHUB_REPOSITORY="tox-dev/github-workflows",
        **_author_lookup(github_api, 3),
    )
    assert result.returncode == 0, result.stderr
    assert "[#3](https://github.com/tox-dev/github-workflows/pull/3)" in (repository / "CHANGELOG.md").read_text()


@pytest.mark.parametrize("version", [pytest.param("", id="automatic"), pytest.param("0.2.0", id="explicit")])
def test_prepare_rejects_unlinked_fragment_name(
    repository: Path, tmp_path: Path, action_scripts: Path, version: str
) -> None:
    run(repository, "git", "mv", "changelog.d/+feature.feature.md", "changelog.d/feature.feature.md")
    run(repository, "git", "commit", "-m", "Use a bare fragment name")
    run(repository, "git", "push", "origin", "main")
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version=version, LINK_FRAGMENTS="true")
    assert result.returncode != 0
    assert "unsupported changelog fragment name" in result.stderr
    assert not (tmp_path / "release.patch").exists()


def test_prepare_rejects_untracked_output(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: mdformat\n"
        "        name: mdformat\n        entry: bash -c 'touch extra-output'\n"
        "        language: system\n        pass_filenames: false\n",
    )
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Write untracked output")
    run(repository, "git", "push", "origin", "main")
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0", FORMAT="markdown")
    assert result.returncode != 0
    assert "created untracked files" in result.stderr


def test_prepare_rejects_empty_release(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "changelog.d/+feature.feature.md").unlink()
    run(repository, "git", "add", "-u")
    run(repository, "git", "commit", "-m", "Remove unused fragment")
    run(repository, "git", "push", "origin", "main")
    result = action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0")
    assert result.returncode != 0
    assert "has no release notes" in result.stderr


def test_prepare_rejects_empty_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", str(action_scripts / "prepare-towncrier-8.sh")],
        cwd=repository,
        env=os.environ | {"PATCH": str(tmp_path / "release.patch")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "produced no patch" in result.stderr


def test_prepare_formats_markdown(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: mdformat\n"
        "        name: mdformat\n        entry: mdformat --wrap 120\n"
        "        language: system\n        types: [markdown]\n",
    )
    (repository / "changelog.d/+feature.feature.md").write_text("Add " + "a long sentence " * 15 + ".\n")
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


def test_prepare_formats_rst(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    project = repository / "pyproject.toml"
    project.write_text(
        project.read_text().replace("CHANGELOG.md", "CHANGELOG.rst").replace("template.jinja2", "template.rst.jinja2")
    )
    (repository / "CHANGELOG.md").rename(repository / "CHANGELOG.rst")
    (repository / "CHANGELOG.rst").write_text("Changelog\n=========\n\n.. towncrier release notes start\n")
    (repository / "changelog.d/+feature.feature.md").rename(repository / "changelog.d/+feature.feature.rst")
    (repository / "changelog.d/+feature.feature.rst").write_text("Add a Before feature.\n")
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: docstrfmt\n"
        "        name: docstrfmt\n        entry: sed -i s/Before/After/\n"
        "        language: system\n        files: CHANGELOG.rst\n"
    )
    run(repository, "git", "add", "-A")
    run(repository, "git", "commit", "-m", "Set RST hook")
    run(repository, "git", "push", "origin", "main")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="0.2.0",
        FORMAT="rst",
        CHANGELOG="CHANGELOG.rst",
    )
    assert result.returncode == 0, result.stderr
    assert "Add a After feature." in (repository / "CHANGELOG.rst").read_text()


def test_prepare_avoids_rst_conflict_marker(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    project = repository / "pyproject.toml"
    project.write_text(
        project.read_text()
        .replace("CHANGELOG.md", "CHANGELOG.rst")
        .replace("template.jinja2", "template.rst.jinja2")
        .replace('name = "Added"', 'name = "Changes"')
        .replace("title_format = false", 'underlines = ["*", "=", "-"]\ntitle_format = false')
    )
    (repository / "CHANGELOG.md").rename(repository / "CHANGELOG.rst")
    (repository / "CHANGELOG.rst").write_text(
        "Changelog\n=========\n\n.. towncrier release notes start\n\n"
        "0.1.0 (2026-01-01)\n******************\n\nChanges\n=======\n\n"
        "- ``>>>>>>> historical branch`` remains quoted.\n"
    )
    (repository / "changelog.d/+feature.feature.md").rename(repository / "changelog.d/+feature.feature.rst")
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: docstrfmt\n"
        "        name: docstrfmt\n        entry: bash -c true\n"
        "        language: system\n        files: CHANGELOG.rst\n"
    )
    run(repository, "git", "add", "-A")
    run(repository, "git", "commit", "-m", "Set RST category")
    run(repository, "git", "push", "origin", "main")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-towncrier",
        version="0.2.0",
        FORMAT="rst",
        CHANGELOG="CHANGELOG.rst",
    )
    assert result.returncode == 0, result.stderr
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-release-patch",
        version="0.2.0",
        CHANGELOG="CHANGELOG.rst",
    )
    assert result.returncode == 0, result.stderr
    assert "Changes\n=======" in (repository / "CHANGELOG.rst").read_text()


@pytest.mark.parametrize(
    "script",
    [
        pytest.param("prepare-towncrier-7.sh", id="prepare"),
        pytest.param("validate-release-patch-5.sh", id="validate"),
    ],
)
@pytest.mark.parametrize("tracked", [pytest.param(True, id="tracked"), pytest.param(False, id="first-release")])
def test_prepare_rejects_rst_conflict_marker(
    repository: Path, action_scripts: Path, script: str, tracked: bool
) -> None:
    if tracked:
        (repository / "CHANGELOG.rst").write_text("Changelog\n=========\n")
        run(repository, "git", "add", "CHANGELOG.rst")
        run(repository, "git", "commit", "-m", "Track RST changelog")
    (repository / "CHANGELOG.rst").write_text("Changelog\n=========\n\n<<<<<<< HEAD\n")
    run(repository, "git", "add", *(["-N"] if script.startswith("prepare") and not tracked else []), "CHANGELOG.rst")
    result = subprocess.run(
        ["bash", str(action_scripts / script)],
        cwd=repository,
        env={name: os.environ[name] for name in ("HOME", "LANG", "PATH") if name in os.environ}
        | {"CHANGELOG": "CHANGELOG.rst"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "conflict markers" in result.stderr


def _author_lookup(github_api: tuple[HTTPServer, dict[str, str]], number: int) -> dict[str, str]:
    server, environment = github_api
    server.expect_request(f"/api/v3/repos/tox-dev/github-workflows/pulls/{number}", method="GET").respond_with_json(
        {"user": {"login": "gaborbernat", "type": "User"}},
    )
    return environment
