from __future__ import annotations

import base64
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from conftest import action
from pytest_httpserver import HTTPServer


def test_action_uses_scoped_job_token() -> None:
    action = yaml.safe_load((Path(__file__).resolve().parents[2] / "check-hook-update-cooldown/action.yml").read_text())
    assert [step["env"]["GH_TOKEN"] for step in action["runs"]["steps"] if "GH_TOKEN" in step.get("env", {})] == [
        "${{ github.token }}",
        "${{ github.token }}",
        "${{ github.token }}",
        "${{ github.token }}",
    ]


@pytest.mark.parametrize(
    ("author", "revision", "frozen_base", "accepted"),
    [
        pytest.param("gaborbernat", "v2", False, True, id="human"),
        pytest.param("pre-commit-ci[bot]", "v1", False, True, id="cooled-revision-on-new-head"),
        pytest.param("pre-commit-ci[bot]", "v0.5", False, True, id="older-cooled-revision"),
        pytest.param("pre-commit-ci[bot]", "1.0", False, True, id="cooled-alias"),
        pytest.param("pre-commit-ci[bot]", "sha-v0.5", True, True, id="older-frozen-revision"),
        pytest.param("pre-commit-ci[bot]", "v1", True, True, id="frozen-base"),
        pytest.param("pre-commit-ci[bot]", "v2", False, False, id="young-revision-on-old-pr"),
        pytest.param("release-app[bot]", "v1", False, True, id="app-cooled-revision"),
        pytest.param("release-app[bot]", "v2", False, False, id="app-young-revision"),
    ],
)
def test_cooldown_checks_hook_revision(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    author: str,
    revision: str,
    frozen_base: bool,
    accepted: bool,
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(server, author=author)
    if author.endswith("[bot]"):
        base_revision = (
            subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "v0^{}"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            if frozen_base
            else "v0"
        )
        if revision == "sha-v0.5":
            revision = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "v0.5^{}"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
        expect_config(server, "b" * 40, repository, base_revision)
        expect_config(server, "a" * 40, repository, revision)
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert (result.returncode == 0) is accepted, result.stderr
    assert [request.path for request, _ in server.log] == [
        "/api/v3/repos/tox-dev/fixture/pulls/7",
        *(
            [
                "/api/v3/repos/tox-dev/fixture/pulls/7/files",
                "/api/v3/repos/tox-dev/fixture/actions/runs",
                "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
                "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
            ]
            if author.endswith("[bot]")
            else []
        ),
    ]


def test_cooldown_skips_bot_without_hook_changes(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    expect_pull(server, author="dependabot[bot]", hook_update=False)
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode == 0, result.stderr
    assert [request.path for request, _ in server.log] == [
        "/api/v3/repos/tox-dev/fixture/pulls/7",
        "/api/v3/repos/tox-dev/fixture/pulls/7/files",
    ]


def test_cooldown_rejects_changed_head(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    expect_pull(server, author="pre-commit-ci[bot]", head="c" * 40)
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode != 0
    assert len(server.log) == 1


def test_cooldown_rejects_backdated_tag_on_recent_pull_request(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    expect_pull(server, author="pre-commit-ci[bot]", observed_days=0, updated_days=10)
    repository = hook_repository(tmp_path)
    expect_config(server, "b" * 40, repository, "v0")
    expect_config(server, "a" * 40, repository, "v2")
    expect_historical_runs(server, older_head=None)
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode != 0
    assert "hook revision has not been observed" in result.stderr


@pytest.mark.parametrize(
    ("historical_revision", "accepted"),
    [pytest.param("v1", True, id="same-revision"), pytest.param("v0", False, id="new-revision")],
)
def test_cooldown_survives_force_push_without_accepting_new_revision(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    historical_revision: str,
    accepted: bool,
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(server, author="pre-commit-ci[bot]", observed_days=0)
    expect_config(server, "b" * 40, repository, "v0")
    expect_config(server, "a" * 40, repository, "v1")
    expect_historical_runs(server, older_head="c" * 40)
    expect_config(server, "c" * 40, repository, historical_revision)
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert (result.returncode == 0) is accepted, result.stderr
    branch_runs = [
        request for request, _ in server.log if request.path.endswith("/actions/runs") and "branch" in request.args
    ]
    assert len(branch_runs) == 1
    cutoff = datetime.fromisoformat(branch_runs[0].args["created"].removeprefix("<"))
    assert timedelta(days=6, hours=23) < datetime.now(UTC) - cutoff < timedelta(days=7, hours=1)
    if not accepted:
        assert "hook revision has not been observed" in result.stderr


def test_cooldown_skips_unavailable_old_head(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(server, author="pre-commit-ci[bot]", observed_days=0)
    expect_config(server, "b" * 40, repository, "v0")
    expect_config(server, "a" * 40, repository, "v1")
    expect_historical_runs(server, older_head=("c" * 40, "d" * 40))
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
        method="GET",
        query_string=f"ref={'c' * 40}",
    ).respond_with_json({"message": "Not Found"}, status=404)
    expect_config(server, "d" * 40, repository, "v1")
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode == 0, result.stderr


def test_cooldown_skips_malformed_old_head(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(server, author="pre-commit-ci[bot]", observed_days=0)
    expect_config(server, "b" * 40, repository, "v0")
    expect_config(server, "a" * 40, repository, "v1")
    expect_historical_runs(server, older_head=("c" * 40, "d" * 40))
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
        method="GET",
        query_string=f"ref={'c' * 40}",
    ).respond_with_json({"content": base64.b64encode(b"repos: [").decode()})
    expect_config(server, "d" * 40, repository, "v1")
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode == 0, result.stderr


def test_cooldown_matches_revision_after_repository_list_change(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(server, author="pre-commit-ci[bot]", observed_days=0)
    expect_config(server, "b" * 40, repository, "v0")
    expect_config(server, "a" * 40, repository, "v1")
    expect_historical_runs(server, older_head="c" * 40)
    historical = (
        "repos:\n"
        "  - repo: https://example.invalid/another-hook\n    rev: v2\n    hooks: []\n"
        f"  - repo: {repository.as_uri()}\n    rev: v1\n    hooks:\n      - id: sample\n"
    )
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
        method="GET",
        query_string=f"ref={'c' * 40}",
    ).respond_with_json({"content": base64.b64encode(historical.encode()).decode()})
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode == 0, result.stderr


def test_cooldown_ignores_another_pull_request_history(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(server, author="pre-commit-ci[bot]", observed_days=0)
    expect_config(server, "b" * 40, repository, "v0")
    expect_config(server, "a" * 40, repository, "v1")
    expect_historical_runs(server, older_head="c" * 40, pull_request=8)
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode != 0
    assert "hook revision has not been observed" in result.stderr


def test_cooldown_checks_each_duplicate_repository(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(server, author="pre-commit-ci[bot]")
    expect_config(server, "b" * 40, repository, ("v0", "v0"))
    expect_config(server, "a" * 40, repository, ("v2", "v0"))
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode != 0
    assert "hook repository entries changed" not in result.stderr
    assert "hook revision is not eligible" in result.stderr


def test_cooldown_does_not_use_another_duplicate_repository_observation(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(server, author="pre-commit-ci[bot]", observed_days=0)
    expect_config(server, "b" * 40, repository, ("v0", "v0"))
    expect_config(server, "a" * 40, repository, ("v1", "v0"))
    expect_historical_runs(server, older_head="c" * 40)
    expect_config(server, "c" * 40, repository, ("v0", "v1"))
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode != 0
    assert "hook revision has not been observed" in result.stderr


def test_cooldown_rejects_other_event_before_api(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    server, environment = github_api
    result = run_cooldown(
        action_scripts,
        tmp_path,
        environment,
        event_name="workflow_dispatch",
    )
    assert result.returncode != 0
    assert not server.log


def run_cooldown(
    action_scripts: Path,
    tmp_path: Path,
    environment: dict[str, str],
    *,
    event_name: str = "pull_request",
    event_head: str = "a" * 40,
) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"number": 7, "pull_request": {"head": {"sha": event_head}}}))
    (tmp_path / "pylock.toml").write_text(
        'lock-version = "1.0"\ncreated-by = "test"\nrequires-python = ">=3.15"\npackages = []\n',
    )
    return action(
        tmp_path,
        tmp_path,
        action_scripts,
        "check-hook-update-cooldown",
        version="",
        MINIMUM_DAYS="7",
        GITHUB_EVENT_NAME=event_name,
        GITHUB_EVENT_PATH=str(path),
        GITHUB_OUTPUT=str(tmp_path / "outputs"),
        **environment,
    )


def expect_pull(
    server: HTTPServer,
    *,
    author: str,
    head: str = "a" * 40,
    observed_days: int = 10,
    updated_days: int = 0,
    hook_update: bool = True,
) -> None:
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7", method="GET").respond_with_json(
        {
            "state": "open",
            "base": {"repo": {"full_name": "tox-dev/fixture"}, "sha": "b" * 40},
            "head": {"sha": head, "ref": "bot-update"},
            "user": {"login": author, "type": "Bot" if author.endswith("[bot]") else "User"},
            "updated_at": (datetime.now(UTC) - timedelta(days=updated_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    if author.endswith("[bot]"):
        server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7/files", method="GET").respond_with_json(
            [{"filename": ".pre-commit-config.yaml" if hook_update else "pyproject.toml"}]
        )
    if author.endswith("[bot]") and hook_update:
        server.expect_request(
            "/api/v3/repos/tox-dev/fixture/actions/runs",
            method="GET",
            query_string=f"event=pull_request&head_sha={head}&per_page=100",
        ).respond_with_json(
            {
                "workflow_runs": [
                    {
                        "event": "pull_request",
                        "head_repository": {"full_name": "tox-dev/fixture"},
                        "head_branch": "bot-update",
                        "head_sha": head,
                        "pull_requests": [{"number": 7}],
                        "created_at": (datetime.now(UTC) - timedelta(days=observed_days)).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                    }
                ]
            }
        )


def expect_config(server: HTTPServer, sha: str, repository: Path, revision: str | tuple[str, ...]) -> None:
    revisions = (revision,) if isinstance(revision, str) else revision
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml", method="GET", query_string=f"ref={sha}"
    ).respond_with_json(
        {
            "content": base64.b64encode(
                (
                    "repos:\n"
                    + "".join(
                        f"  - repo: {repository.as_uri()}\n    rev: {item}\n    hooks:\n      - id: sample\n"
                        for item in revisions
                    )
                ).encode()
            ).decode()
        }
    )


def expect_historical_runs(
    server: HTTPServer, *, older_head: str | tuple[str, ...] | None, pull_request: int = 7
) -> None:
    heads = () if older_head is None else (older_head,) if isinstance(older_head, str) else older_head
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/actions/runs",
        method="GET",
    ).respond_with_json(
        {
            "workflow_runs": [
                {
                    "event": "pull_request",
                    "head_repository": {"full_name": "tox-dev/fixture"},
                    "head_branch": "bot-update",
                    "head_sha": head,
                    "pull_requests": [{"number": pull_request}],
                    "created_at": (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                for head in heads
            ]
        }
    )


def hook_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "hook-repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Hook test"], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.email", "hooks@example.org"], check=True)
    (repository / ".pre-commit-hooks.yaml").write_text(
        "- id: sample\n  name: sample\n  entry: true\n  language: system\n"
    )
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "Add hook"], check=True)
    for name, days in (("v0", 20), ("v0.5", 15), ("v1", 10), ("v2", 1)):
        date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (repository / "version").write_text(name)
        subprocess.run(["git", "-C", str(repository), "add", "version"], check=True)
        subprocess.run(
            ["git", "-C", str(repository), "commit", "-qm", name],
            env=os.environ | {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repository), "tag", "-a", name, "-m", name],
            env=os.environ | {"GIT_COMMITTER_DATE": date},
            check=True,
        )
    subprocess.run(
        ["git", "-C", str(repository), "tag", "-a", "1.0", "v1^{}", "-m", "1.0"],
        env=os.environ
        | {"GIT_COMMITTER_DATE": (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")},
        check=True,
    )
    return repository
