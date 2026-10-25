from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from conftest import action, run


@pytest.fixture
def tagged_repository(repository: Path) -> Path:
    (repository / "CHANGELOG.md").write_text(
        dedent(
            """\
            # Changelog

            <!-- towncrier release notes start -->

            <a name="release-0-2-0"></a>

            ## 0.2.0 (2026-10-20)

            <a name="release-0-2-0-added"></a>

            ### Added

            - Add a new feature ([#2](https://github.com/tox-dev/fixture/pull/2)) by
              [@gaborbernat](https://github.com/gaborbernat).
            """,
        ),
    )
    run(repository, "git", "add", "CHANGELOG.md")
    run(repository, "git", "commit", "-m", "Release 0.2.0")
    run(repository, "git", "tag", "0.2.0")
    return repository


def test_render_release_notes_uses_tagged_changelog(
    tagged_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    result = action(
        tagged_repository,
        tmp_path,
        action_scripts,
        "render-release-notes",
        version="0.2.0",
        TAG="0.2.0",
        ARTIFACT_URL="https://pypi.org/project/fixture/0.2.0/",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "release-notes.md").read_text() == dedent(
        """\
        <a name="release-0-2-0-added"></a>

        ### Features

        - Add a new feature ([#2](https://github.com/tox-dev/fixture/pull/2)) by @gaborbernat.

        [PyPI release](https://pypi.org/project/fixture/0.2.0/)

        [Full Changelog](https://github.com/tox-dev/fixture/compare/0.1.0...0.2.0)
        """,
    )
    assert "previous=0.1.0" in (tmp_path / "output").read_text()


def test_render_release_notes_uses_generated_contributors(
    tagged_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    generated = tmp_path / "generated.md"
    generated.write_text(
        "* Add a new feature by @gaborbernat in https://github.com/tox-dev/fixture/pull/2\n"
        "\n## New Contributors\n* @gaborbernat made their first contribution in "
        "https://github.com/tox-dev/fixture/pull/2\n",
    )
    result = action(
        tagged_repository,
        tmp_path,
        action_scripts,
        "render-release-notes",
        version="0.2.0",
        TAG="0.2.0",
        GENERATED_NOTES=str(generated),
    )
    assert result.returncode == 0, result.stderr
    assert "### New Contributors\n\n- @gaborbernat" in (tmp_path / "release-notes.md").read_text()


def test_render_release_notes_accepts_first_release(
    tagged_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    run(tagged_repository, "git", "tag", "-d", "0.1.0")
    result = action(
        tagged_repository,
        tmp_path,
        action_scripts,
        "render-release-notes",
        version="0.2.0",
        TAG="0.2.0",
    )
    assert result.returncode == 0, result.stderr
    assert "### Features" in (tmp_path / "release-notes.md").read_text()
    assert "compare/" not in (tmp_path / "release-notes.md").read_text()


@pytest.mark.parametrize(
    ("role", "path"),
    [pytest.param("pr", "pull", id="pull-request"), pytest.param("issue", "issues", id="issue")],
)
def test_render_release_notes_converts_rst_reference(
    tagged_repository: Path, tmp_path: Path, action_scripts: Path, role: str, path: str
) -> None:
    (tagged_repository / "CHANGELOG.rst").write_text(
        f"0.2.0 (2026-10-20)\n==================\n\nFixed\n-----\n\n- Correct a bug (:{role}:`4`).\n",
    )
    result = action(
        tagged_repository,
        tmp_path,
        action_scripts,
        "render-release-notes",
        version="0.2.0",
        TAG="0.2.0",
        CHANGELOG="CHANGELOG.rst",
    )
    assert result.returncode == 0, result.stderr
    assert (
        f"Correct a bug ([#4](https://github.com/tox-dev/fixture/{path}/4))"
        in (tmp_path / "release-notes.md").read_text()
    )


def test_render_release_notes_custom_artifact_label(
    tagged_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    result = action(
        tagged_repository,
        tmp_path,
        action_scripts,
        "render-release-notes",
        version="0.2.0",
        TAG="0.2.0",
        ARTIFACT_URL="https://github.com/tox-dev/fixture/releases/download/0.2.0/fixture.pyz",
        ARTIFACT_LABEL="Zipapp",
    )
    assert result.returncode == 0, result.stderr
    assert (
        "[Zipapp](https://github.com/tox-dev/fixture/releases/download/0.2.0/fixture.pyz)"
        in (tmp_path / "release-notes.md").read_text()
    )


@pytest.mark.parametrize(
    ("tag", "remove_heading", "error"),
    [
        pytest.param("invalid tag", False, "release tag not found", id="invalid-tag"),
        pytest.param("0.2.0", True, "expected one changelog section", id="missing-heading"),
    ],
)
def test_render_release_notes_rejects_invalid_source(
    tagged_repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    tag: str,
    remove_heading: bool,
    error: str,
) -> None:
    if remove_heading:
        changelog = tagged_repository / "CHANGELOG.md"
        changelog.write_text(changelog.read_text().replace("## 0.2.0 (", "0.2.0 ("))
    result = action(
        tagged_repository,
        tmp_path,
        action_scripts,
        "render-release-notes",
        version=tag,
        TAG=tag,
    )
    assert result.returncode != 0
    assert error in result.stderr
