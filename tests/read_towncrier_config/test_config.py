from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from conftest import action, run


def test_reader_uses_configured_type_array(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(repository, tmp_path, action_scripts, "read-towncrier-config", version="")
    assert result.returncode == 0, result.stderr
    outputs = dict(line.split("=", 1) for line in (tmp_path / "output").read_text().splitlines())
    assert {key: value for key, value in outputs.items() if key != "categories-file"} == {
        "changelog": "CHANGELOG.md",
        "fragments": "changelog.d",
        "format": "markdown",
    }
    assert Path(outputs["categories-file"]).read_text() == "feature\n"


def test_reader_prefers_towncrier_fragment_tables(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "towncrier.toml").write_text(
        dedent(
            """\
            [tool.towncrier]
            directory = "docs/news"
            filename = "docs/NEWS.rst"

            [tool.towncrier.fragment.feature]
            name = "Added"

            [tool.towncrier.fragment.bugfix]
            name = "Fixed"
            """
        )
    )
    run(repository, "git", "add", "towncrier.toml")
    run(repository, "git", "commit", "-m", "Configure Towncrier in a separate file")
    result = action(repository, tmp_path, action_scripts, "read-towncrier-config", version="")
    assert result.returncode == 0, result.stderr
    outputs = dict(line.split("=", 1) for line in (tmp_path / "output").read_text().splitlines())
    assert {key: value for key, value in outputs.items() if key != "categories-file"} == {
        "changelog": "docs/NEWS.rst",
        "fragments": "docs/news",
        "format": "rst",
    }
    assert Path(outputs["categories-file"]).read_text() == "feature\nbugfix\n"


@pytest.mark.parametrize("path", [pytest.param("../NEWS.md", id="parent"), pytest.param("/NEWS.md", id="absolute")])
def test_reader_rejects_unsafe_changelog_path(
    repository: Path, tmp_path: Path, action_scripts: Path, path: str
) -> None:
    project = repository / "pyproject.toml"
    project.write_text(project.read_text().replace('filename = "CHANGELOG.md"', f'filename = "{path}"'))
    run(repository, "git", "add", "pyproject.toml")
    run(repository, "git", "commit", "-m", "Set changelog path")
    result = action(repository, tmp_path, action_scripts, "read-towncrier-config", version="")
    assert result.returncode != 0
    assert "Towncrier paths must stay within the repository" in result.stderr


def test_reader_rejects_mixed_fragment_styles(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    project = repository / "pyproject.toml"
    project.write_text(project.read_text() + '\n[tool.towncrier.fragment.bugfix]\nname = "Fixed"\n')
    run(repository, "git", "add", "pyproject.toml")
    run(repository, "git", "commit", "-m", "Mix Towncrier fragment styles")
    result = action(repository, tmp_path, action_scripts, "read-towncrier-config", version="")
    assert result.returncode != 0
    assert "type and fragment tables cannot be combined" in result.stderr


def test_reader_rejects_non_table_fragment(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "towncrier.toml").write_text(
        '[tool.towncrier]\ndirectory = "changelog.d"\nfilename = "CHANGELOG.md"\nfragment = { feature = "Added" }\n'
    )
    run(repository, "git", "add", "towncrier.toml")
    run(repository, "git", "commit", "-m", "Set an invalid fragment definition")
    result = action(repository, tmp_path, action_scripts, "read-towncrier-config", version="")
    assert result.returncode != 0
    assert "Towncrier fragment categories are required" in result.stderr
