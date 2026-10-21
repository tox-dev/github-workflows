from __future__ import annotations

from pathlib import Path

import pytest
from conftest import action
from pytest_httpserver import HTTPServer


@pytest.mark.parametrize(
    ("head_repository", "head_owner", "branch", "author_type", "conclusion"),
    [
        pytest.param("tox-dev/fixture", "tox-dev", "dependabot/uv", "Bot", "success", id="same-repo-bot"),
        pytest.param("external/fixture", "external", "fix/news", "Bot", "failure", id="fork-bot-failed-ci"),
        pytest.param("external/fixture", "external", "fix/news", "User", "success", id="human"),
    ],
)
def test_resolve_pr_from_run_matches_current_head(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    head_repository: str,
    head_owner: str,
    branch: str,
    author_type: str,
    conclusion: str,
) -> None:
    server, environment = github_api
    server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs/42").respond_with_json(
        {
            "id": 42,
            "repository": {"full_name": "tox-dev/fixture"},
            "event": "pull_request",
            "path": ".github/workflows/check.yaml",
            "status": "completed",
            "conclusion": conclusion,
            "head_repository": {"full_name": head_repository, "owner": {"login": head_owner}},
            "head_branch": branch,
            "head_sha": "a" * 40,
            "pull_requests": [],
        },
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls").respond_with_json(
        [
            {
                "number": 7,
                "state": "open",
                "user": {"type": author_type},
                "head": {"sha": "a" * 40, "repo": {"full_name": head_repository}},
                "base": {"repo": {"full_name": "tox-dev/fixture"}},
            },
        ],
    )
    result = action(repository, tmp_path, action_scripts, "resolve-pr-from-run", version="0.2.0", **environment)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == f"number=7\nbot-author={str(author_type == 'Bot').lower()}\n"
    assert server.log[1][0].args["head"] == f"{head_owner}:{branch}"


@pytest.mark.parametrize(
    ("head_sha", "head_repository", "response"),
    [
        pytest.param("b" * 40, "external/fixture", "stale-head", id="stale-head"),
        pytest.param("a" * 40, "other/fixture", "wrong-fork", id="wrong-fork"),
        pytest.param("a" * 40, "external/fixture", "missing", id="no-pr"),
    ],
)
def test_resolve_pr_from_run_skips_unmatched_pr(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    head_sha: str,
    head_repository: str,
    response: str,
) -> None:
    server, environment = github_api
    server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs/42").respond_with_json(
        {
            "id": 42,
            "repository": {"full_name": "tox-dev/fixture"},
            "event": "pull_request",
            "path": ".github/workflows/check.yaml",
            "status": "completed",
            "head_repository": {"full_name": "external/fixture", "owner": {"login": "external"}},
            "head_branch": "fix/news",
            "head_sha": "a" * 40,
        },
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls").respond_with_json(
        []
        if response == "missing"
        else [
            {
                "number": 7,
                "state": "open",
                "user": {"type": "Bot"},
                "head": {"sha": head_sha, "repo": {"full_name": head_repository}},
                "base": {"repo": {"full_name": "tox-dev/fixture"}},
            },
        ],
    )
    result = action(repository, tmp_path, action_scripts, "resolve-pr-from-run", version="0.2.0", **environment)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "output").exists()


def test_resolve_pr_from_run_rejects_ambiguous_pr(
    repository: Path, tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs/42").respond_with_json(
        {
            "id": 42,
            "repository": {"full_name": "tox-dev/fixture"},
            "event": "pull_request",
            "path": ".github/workflows/check.yaml",
            "status": "completed",
            "head_repository": {"full_name": "external/fixture", "owner": {"login": "external"}},
            "head_branch": "fix/news",
            "head_sha": "a" * 40,
        },
    )
    candidate = {
        "number": 7,
        "state": "open",
        "user": {"type": "Bot"},
        "head": {"sha": "a" * 40, "repo": {"full_name": "external/fixture"}},
        "base": {"repo": {"full_name": "tox-dev/fixture"}},
    }
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls").respond_with_json(
        [candidate, candidate | {"number": 8}],
    )
    result = action(repository, tmp_path, action_scripts, "resolve-pr-from-run", version="0.2.0", **environment)
    assert result.returncode != 0
    assert "source run matches multiple pull requests" in result.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("event", "pull_request_target", id="privileged-event"),
        pytest.param("path", ".github/workflows/release.yaml", id="wrong-workflow"),
        pytest.param("status", "in_progress", id="unfinished-run"),
        pytest.param("repository", {"full_name": "other/fixture"}, id="wrong-repository"),
        pytest.param("id", 43, id="wrong-run-id"),
    ],
)
def test_resolve_pr_from_run_rejects_untrusted_source(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    field: str,
    value: object,
) -> None:
    server, environment = github_api
    source: dict[str, object] = {
        "id": 42,
        "repository": {"full_name": "tox-dev/fixture"},
        "event": "pull_request",
        "path": ".github/workflows/check.yaml",
        "status": "completed",
        "head_repository": {"full_name": "external/fixture", "owner": {"login": "external"}},
        "head_branch": "fix/news",
        "head_sha": "a" * 40,
    }
    source[field] = value
    server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs/42").respond_with_json(source)
    result = action(repository, tmp_path, action_scripts, "resolve-pr-from-run", version="0.2.0", **environment)
    assert result.returncode != 0
    assert len(server.log) == 1


def test_resolve_pr_from_run_rejects_non_numeric_id(
    repository: Path, tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    result = action(
        repository, tmp_path, action_scripts, "resolve-pr-from-run", version="0.2.0", RUN_ID="../42", **environment
    )
    assert result.returncode != 0
    assert "run-id must be a decimal integer" in result.stderr
    assert not server.log
