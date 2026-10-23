from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import action
from pytest_httpserver import HTTPServer


@pytest.mark.parametrize(
    ("files", "labels", "edit_option", "fragment_dirs", "extension", "fragment_style"),
    [
        pytest.param([], [], "--add-label", "changelog.d", "md", "towncrier", id="add"),
        pytest.param(
            [{"filename": "changelog.d/+old.feature.md", "status": "removed"}],
            [],
            "--add-label",
            "changelog.d",
            "md",
            "towncrier",
            id="deleted-fragment-needs-label",
        ),
        pytest.param([], [{"name": "skip news"}], None, "changelog.d", "md", "towncrier", id="already-labeled"),
        pytest.param(
            [{"filename": "changelog.d/+fix.bugfix.md"}],
            [{"name": "skip news"}],
            "--remove-label",
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
            [{"filename": "changelog.d/+fix.bugfix.2.md"}],
            [{"name": "skip news"}],
            "--remove-label",
            "changelog.d",
            "md",
            "towncrier",
            id="named-fragment-counter",
        ),
        pytest.param(
            [{"filename": "changelog.d/123.bugfix.md"}],
            [{"name": "skip news"}],
            "--remove-label",
            "changelog.d",
            "md",
            "towncrier",
            id="numeric-fragment",
        ),
        pytest.param(
            [{"filename": "changelog.d/123.bugfix.2.md"}],
            [{"name": "skip news"}],
            "--remove-label",
            "changelog.d",
            "md",
            "towncrier",
            id="numeric-fragment-counter",
        ),
        pytest.param(
            [{"filename": "changelog.d/topic.feature.md"}],
            [{"name": "skip news"}],
            None,
            "changelog.d",
            "md",
            "towncrier",
            id="bare-name-not-a-fragment",
        ),
        pytest.param(
            [{"filename": "changelog.d/123a.feature.md"}],
            [{"name": "skip news"}],
            None,
            "changelog.d",
            "md",
            "towncrier",
            id="mixed-number-not-a-fragment",
        ),
        pytest.param(
            [{"filename": "changelog.d/+.feature.md"}],
            [{"name": "skip news"}],
            None,
            "changelog.d",
            "md",
            "towncrier",
            id="empty-named-stem-not-a-fragment",
        ),
        pytest.param(
            [{"filename": "docs/changelog.d/+fix.bugfix.md"}],
            [{"name": "skip news"}],
            "--remove-label",
            "changelog.d,docs/changelog.d",
            "md",
            "towncrier",
            id="legacy-fragment-path",
        ),
        pytest.param(
            [{"filename": "docs/changelog/+fix.bugfix.rst"}],
            [{"name": "skip news"}],
            "--remove-label",
            "docs/changelog",
            "rst",
            "towncrier",
            id="rst-fragment-removes-label",
        ),
        pytest.param([], [], "--add-label", ".changeset", "md", "changeset", id="changeset-add"),
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
            "--remove-label",
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
    edit_option: str | None,
    fragment_dirs: str,
    extension: str,
    fragment_style: str,
) -> None:
    server, environment = github_api
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_request(f"{prefix}/pulls/1/files", method="GET").respond_with_json(files)
    server.expect_request(f"{prefix}/issues/1/labels", method="GET").respond_with_json(labels)
    real_gh = shutil.which("gh")
    assert real_gh is not None
    executable = tmp_path / "gh-shim" / "gh"
    executable.parent.mkdir()
    executable.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ $1 == pr && $2 == edit ]]; then printf "%s\\0" "$@" >>"$GH_EDIT_LOG"; exit 0; fi\n'
        'exec "$GH_REAL" "$@"\n',
    )
    executable.chmod(0o755)
    edit_log = tmp_path / "gh-edit-args"
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
        PATH=f"{executable.parent}:{os.environ['PATH']}",
        GH_REAL=real_gh,
        GH_EDIT_LOG=str(edit_log),
        **environment,
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET", "GET"]
    assert (edit_log.read_bytes().split(b"\0")[:-1] if edit_log.exists() else []) == (
        [part.encode() for part in ("pr", "edit", "1", "--repo", "tox-dev/fixture", edit_option, "skip news")]
        if edit_option is not None
        else []
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
