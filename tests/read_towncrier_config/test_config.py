from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from conftest import action, run


def test_reader_uses_configured_type_array(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(repository, tmp_path, action_scripts, "read-towncrier-config", version="")
    assert result.returncode == 0, result.stderr
    outputs = dict(line.split("=", 1) for line in (tmp_path / "output").read_text().splitlines())
    assert outputs == {
        "changelog": "CHANGELOG.md",
        "fragments": "changelog.d",
        "format": "markdown",
    }


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
    assert outputs == {
        "changelog": "docs/NEWS.rst",
        "fragments": "docs/news",
        "format": "rst",
    }
