from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import action
from pytest_httpserver import HTTPServer


@pytest.mark.parametrize(
    ("files", "labels", "write_method", "fragment_dirs", "extension", "fragment_style"),
    [
        pytest.param([], [], "POST", "changelog.d", "md", "towncrier", id="add"),
        pytest.param(
            [{"filename": "changelog.d/+old.feature.md", "status": "removed"}],
            [],
            "POST",
            "changelog.d",
            "md",
            "towncrier",
            id="deleted-fragment-needs-label",
        ),
        pytest.param([], [{"name": "skip news"}], None, "changelog.d", "md", "towncrier", id="already-labeled"),
        pytest.param(
            [{"filename": "changelog.d/+fix.bugfix.md"}],
            [{"name": "skip news"}],
            "DELETE",
            "changelog.d",
            "md",
            "towncrier",
            id="remove",
        ),
        pytest.param(
            [{"filename": "changelog.d/+fix.bugfix.md"}],
            [],
            None,
            "changelog.d",
            "md",
            "towncrier",
            id="fragment-without-label",
        ),
        pytest.param(
            [{"filename": "docs/changelog.d/+fix.bugfix.md"}],
            [{"name": "skip news"}],
            "DELETE",
            "changelog.d,docs/changelog.d",
            "md",
            "towncrier",
            id="legacy-fragment-path",
        ),
        pytest.param(
            [{"filename": "docs/changelog/+fix.bugfix.rst"}],
            [{"name": "skip news"}],
            "DELETE",
            "docs/changelog",
            "rst",
            "towncrier",
            id="rst-fragment-removes-label",
        ),
        pytest.param([], [], "POST", ".changeset", "md", "changeset", id="changeset-add"),
        pytest.param(
            [{"filename": "changelog.d/nested/+fix.bugfix.md"}],
            [{"name": "skip news"}],
            None,
            "changelog.d",
            "md",
            "towncrier",
            id="nested-towncrier-is-not-a-fragment",
        ),
        pytest.param(
            [{"filename": ".changeset/nested/fix-something.md"}],
            [{"name": "skip news"}],
            None,
            ".changeset",
            "md",
            "changeset",
            id="nested-changeset-is-not-a-fragment",
        ),
        pytest.param(
            [{"filename": ".changeset/fix-something.md"}],
            [{"name": "skip news"}],
            "DELETE",
            ".changeset",
            "md",
            "changeset",
            id="changeset-remove",
        ),
        pytest.param(
            [{"filename": ".changeset/fix-something.md"}],
            [],
            None,
            ".changeset",
            "md",
            "changeset",
            id="changeset-fragment-without-label",
        ),
    ],
)
def test_label_bot_news_updates_label(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    files: list[dict[str, str]],
    labels: list[dict[str, str]],
    write_method: str | None,
    fragment_dirs: str,
    extension: str,
    fragment_style: str,
) -> None:
    server, environment = github_api
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_request(f"{prefix}/pulls/1/files", method="GET").respond_with_json(files)
    server.expect_request(f"{prefix}/issues/1/labels", method="GET").respond_with_json(labels)
    if write_method is not None:
        uri = f"{prefix}/issues/1/labels" + ("/skip news" if write_method == "DELETE" else "")
        server.expect_request(uri, method=write_method).respond_with_json(labels)
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "label-bot-news",
        version="0.2.0",
        REPOSITORY="tox-dev/fixture",
        GITHUB_EVENT_PULL_REQUEST_NUMBER="1",
        BOT_AUTHOR="true",
        FRAGMENTS=fragment_dirs,
        EXTENSION=extension,
        FRAGMENT_STYLE=fragment_style,
        RUNNER_TEMP=str(tmp_path),
        **environment,
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET", "GET"] + (
        [write_method] if write_method is not None else []
    )


def test_label_bot_news_ignores_human(
    repository: Path, tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    steps = yaml.safe_load((Path(__file__).resolve().parents[2] / "label-bot-news/action.yml").read_text())["runs"][
        "steps"
    ]
    assert all(
        step.get("if") == "inputs.bot-author == 'true' || github.event.pull_request.user.type == 'Bot'"
        for step in steps
    )
    server, environment = github_api
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "label-bot-news",
        version="0.2.0",
        BOT_AUTHOR="false",
        **environment,
    )
    assert result.returncode == 0
    assert not server.log


def test_label_bot_news_rejects_extension(
    repository: Path, tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "label-bot-news",
        version="0.2.0",
        BOT_AUTHOR="true",
        EXTENSION="txt",
        **environment,
    )
    assert result.returncode != 0
    assert "fragment extension must be md or rst" in result.stderr
    assert not server.log


@pytest.mark.parametrize(
    ("style", "extension", "error"),
    [
        pytest.param("unknown", "md", "fragment style must be towncrier or changeset", id="unknown-style"),
        pytest.param("changeset", "rst", "changeset fragments must use md", id="rst-changeset"),
    ],
)
def test_label_bot_news_rejects_invalid_style(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    style: str,
    extension: str,
    error: str,
) -> None:
    server, environment = github_api
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "label-bot-news",
        version="0.2.0",
        BOT_AUTHOR="true",
        FRAGMENT_STYLE=style,
        EXTENSION=extension,
        **environment,
    )
    assert result.returncode != 0
    assert error in result.stderr
    assert not server.log
