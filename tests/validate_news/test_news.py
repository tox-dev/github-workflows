from __future__ import annotations

from pathlib import Path

import pytest
from conftest import action, run


@pytest.mark.parametrize(
    ("bot", "skip", "accepted"),
    [
        pytest.param("false", "false", False, id="human-needs-fragment"),
        pytest.param("true", "false", True, id="bot-needs-no-fragment"),
        pytest.param("false", "true", True, id="human-can-skip-news"),
    ],
)
def test_validate_news_without_fragment(
    repository: Path, tmp_path: Path, action_scripts: Path, bot: str, skip: str, accepted: bool
) -> None:
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        BOT_AUTHOR=bot,
        SKIP_NEWS=skip,
    )
    assert (result.returncode == 0) == accepted
    if not accepted:
        assert "add a changelog fragment" in result.stderr


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("+addition.feature.md", id="named"),
        pytest.param("+addition.feature.1.md", id="named-multiple"),
        pytest.param("123.feature.2.md", id="numbered-multiple"),
    ],
)
def test_validate_news_checks_bot_fragment(repository: Path, tmp_path: Path, action_scripts: Path, name: str) -> None:
    (repository / "changelog.d" / name).write_text("Add another feature.\n")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Add news")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        BOT_AUTHOR="true",
        SKIP_NEWS="true",
    )
    assert result.returncode == 0, result.stderr


def test_validate_news_reads_rst_categories(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    project = repository / "pyproject.toml"
    project.write_text(
        project.read_text()
        .replace('directory = "changelog.d"', 'directory = "docs/changelog"')
        .replace('filename = "CHANGELOG.md"', 'filename = "CHANGELOG.rst"')
        .replace('directory = "feature", name = "Added"', 'directory = "fix", name = "Fixed"')
    )
    (repository / "docs").mkdir()
    (repository / "docs/changelog").mkdir()
    (repository / "docs/changelog/+repair.fix.rst").write_text("Repair a user-facing bug.\n")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Add RST news")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        BOT_AUTHOR="false",
        SKIP_NEWS="false",
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("name", "content", "error"),
    [
        pytest.param("+addition.unknown.md", "Add a feature.\n", "unsupported changelog fragment", id="category"),
        pytest.param("addition.feature.md", "Add a feature.\n", "unsupported changelog fragment", id="name"),
        pytest.param("+addition.feature.x.md", "Add a feature.\n", "unsupported changelog fragment", id="ordinal"),
        pytest.param("+addition.feature.md", " \n", "empty changelog fragment", id="empty"),
    ],
)
def test_validate_news_rejects_bad_fragment(
    repository: Path, tmp_path: Path, action_scripts: Path, name: str, content: str, error: str
) -> None:
    (repository / "changelog.d" / name).write_text(content)
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Add news")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        BOT_AUTHOR="true",
        SKIP_NEWS="false",
    )
    assert result.returncode != 0
    assert error in result.stderr


def test_validate_news_requires_pr_base(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="",
        BOT_AUTHOR="true",
        SKIP_NEWS="false",
    )
    assert result.returncode != 0
    assert "news validation needs a PR base" in result.stderr
