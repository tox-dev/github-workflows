from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pytest_httpserver import HTTPServer


def event(tmp_path: Path, head: str) -> Path:
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"number": 7, "pull_request": {"head": {"sha": head}}}))
    return path


def test_action_uses_scoped_job_token() -> None:
    action = yaml.safe_load((Path(__file__).resolve().parents[2] / "check-hook-update-cooldown/action.yml").read_text())
    assert [step["env"]["GH_TOKEN"] for step in action["runs"]["steps"]] == ["${{ github.token }}"] * 2


def run_cooldown(
    action_scripts: Path,
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    steps = yaml.safe_load((Path(__file__).resolve().parents[2] / "check-hook-update-cooldown/action.yml").read_text())[
        "runs"
    ]["steps"]
    env = env | {"GH_TOKEN": env["GH_ENTERPRISE_TOKEN"]}
    action_variables = {name for step in steps for name in step["env"]}
    base_env = {name: value for name, value in env.items() if name not in action_variables}
    result = None
    for index, step in enumerate(steps):
        result = subprocess.run(
            ["bash", str(action_scripts / f"check-hook-update-cooldown-{index}.sh")],
            cwd=cwd,
            env=base_env | {name: env[name] for name in step["env"]},
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            return result
    assert result is not None
    return result


@pytest.mark.parametrize(
    ("author", "age_days", "pr_update_age_days", "accepted"),
    [
        pytest.param("gaborbernat", 0, 0, True, id="human"),
        pytest.param("pre-commit-ci[bot]", 6, 6, False, id="young-bot-update"),
        pytest.param("pre-commit-ci[bot]", 8, 8, True, id="cooled-bot-update"),
        pytest.param("pre-commit-ci[bot]", 8, 0, True, id="label-only-update"),
    ],
)
def test_cooldown_checks_current_head(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    author: str,
    age_days: int,
    pr_update_age_days: int,
    accepted: bool,
) -> None:
    server, environment = github_api
    committed = (datetime.now(UTC) - timedelta(days=age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    pull = {
        "state": "open",
        "base": {"repo": {"full_name": "tox-dev/fixture"}},
        "head": {"sha": "a" * 40},
        "user": {"login": author},
        "updated_at": (datetime.now(UTC) - timedelta(days=pr_update_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7", method="GET").respond_with_json(pull)
    if author == "pre-commit-ci[bot]":
        server.expect_request("/api/v3/repos/tox-dev/fixture/commits/" + "a" * 40, method="GET").respond_with_json(
            {"commit": {"committer": {"date": committed}}}
        )
    result = run_cooldown(
        action_scripts,
        cwd=tmp_path,
        env=os.environ
        | environment
        | {
            "REPOSITORY": "tox-dev/fixture",
            "PR_NUMBER": "7",
            "HEAD_SHA": "a" * 40,
            "MINIMUM_DAYS": "7",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_EVENT_PATH": str(event(tmp_path, "a" * 40)),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "check-hook-update-cooldown"),
        },
    )
    assert (result.returncode == 0) == accepted, result.stderr
    assert [request.method for request, _ in server.log] == ["GET"] * (2 if author == "pre-commit-ci[bot]" else 1)


def test_cooldown_rejects_changed_head(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    pull = {
        "state": "open",
        "base": {"repo": {"full_name": "tox-dev/fixture"}},
        "head": {"sha": "a" * 40},
        "user": {"login": "gaborbernat"},
        "updated_at": "2026-10-21T00:00:00Z",
    }
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7", method="GET").respond_with_json(
        pull | {"head": {"sha": "b" * 40}}
    )
    result = run_cooldown(
        action_scripts,
        cwd=tmp_path,
        env=os.environ
        | environment
        | {
            "REPOSITORY": "tox-dev/fixture",
            "PR_NUMBER": "7",
            "HEAD_SHA": "a" * 40,
            "MINIMUM_DAYS": "7",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_EVENT_PATH": str(event(tmp_path, "a" * 40)),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "check-hook-update-cooldown"),
        },
    )
    assert result.returncode != 0
    assert [request.method for request, _ in server.log] == ["GET"]


def test_old_bot_pr_with_new_head_restarts_cooldown(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7", method="GET").respond_with_json(
        {
            "state": "open",
            "base": {"repo": {"full_name": "tox-dev/fixture"}},
            "head": {"sha": "b" * 40},
            "user": {"login": "pre-commit-ci[bot]"},
            "updated_at": (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "created_at": "2026-01-01T00:00:00Z",
        }
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/commits/" + "b" * 40, method="GET").respond_with_json(
        {"commit": {"committer": {"date": (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}}}
    )
    result = run_cooldown(
        action_scripts,
        cwd=tmp_path,
        env=os.environ
        | environment
        | {
            "REPOSITORY": "tox-dev/fixture",
            "PR_NUMBER": "7",
            "HEAD_SHA": "b" * 40,
            "MINIMUM_DAYS": "7",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_EVENT_PATH": str(event(tmp_path, "b" * 40)),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "check-hook-update-cooldown"),
        },
    )
    assert result.returncode != 0
    assert "Hook update cooldown ends" in result.stdout


@pytest.mark.parametrize("event_name", ["workflow_dispatch", "pull_request"], ids=["wrong-event", "wrong-event-head"])
def test_cooldown_rejects_other_event_or_head_before_api(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    event_name: str,
) -> None:
    server, environment = github_api
    result = run_cooldown(
        action_scripts,
        cwd=tmp_path,
        env=os.environ
        | environment
        | {
            "REPOSITORY": "tox-dev/fixture",
            "PR_NUMBER": "7",
            "HEAD_SHA": "a" * 40,
            "MINIMUM_DAYS": "7",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_EVENT_NAME": event_name,
            "GITHUB_EVENT_PATH": str(event(tmp_path, "b" * 40)),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "check-hook-update-cooldown"),
        },
    )
    assert result.returncode != 0
    assert not server.log
