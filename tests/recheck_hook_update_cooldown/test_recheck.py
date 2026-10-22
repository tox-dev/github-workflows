from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pytest_httpserver import HTTPServer


def test_recheck_schedule_has_only_required_permissions() -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/recheck-hook-cooldown.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert workflow["jobs"]["recheck"] == {
        "runs-on": "ubuntu-26.04",
        "permissions": {"actions": "write", "contents": "read", "pull-requests": "read"},
        "steps": [{"uses": "$/recheck-hook-update-cooldown"}],
    }


@pytest.mark.parametrize(
    ("observed_age", "job_age", "job_conclusion", "job_name", "reruns"),
    [
        pytest.param(8, 8, "failure", "hook-cooldown", 1, id="matured-failure"),
        pytest.param(8, 8, "failure", "Hook update cooldown", 1, id="named-job"),
        pytest.param(6, 6, "failure", "hook-cooldown", 1, id="recent-pull"),
        pytest.param(8, 0, "failure", "hook-cooldown", 1, id="failed-rerun"),
        pytest.param(31, 31, "failure", "hook-cooldown", 0, id="expired-run"),
        pytest.param(8, 8, "success", "hook-cooldown", 0, id="successful-job"),
    ],
)
def test_recheck_reruns_failed_job(
    github_api: tuple[HTTPServer, dict[str, str]],
    action_scripts: Path,
    tmp_path: Path,
    observed_age: int,
    job_age: int,
    job_conclusion: str,
    job_name: str,
    reruns: int,
) -> None:
    server, environment = github_api
    observed_at = (datetime.now(UTC) - timedelta(days=observed_age)).strftime("%Y-%m-%dT%H:%M:%SZ")
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls", method="GET").respond_with_json(
        [
            {
                "number": 7,
                "user": {"login": "pre-commit-ci[bot]"},
                "head": {
                    "sha": "a" * 40,
                    "ref": "pre-commit-ci-update-config",
                    "repo": {"full_name": "tox-dev/fixture"},
                },
                "base": {"repo": {"full_name": "tox-dev/fixture"}},
                "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ]
    )
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/actions/workflows/check.yaml/runs", method="GET"
    ).respond_with_json(
        {
            "workflow_runs": [
                {
                    "id": 42,
                    "event": "pull_request",
                    "head_repository": {"full_name": "tox-dev/fixture"},
                    "head_sha": "a" * 40,
                    "head_branch": "pre-commit-ci-update-config",
                    "pull_requests": [{"number": 7}],
                    "status": "completed",
                    "created_at": observed_at,
                }
            ]
        }
    )
    if observed_age < 30:
        server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs/42/jobs", method="GET").respond_with_json(
            {
                "jobs": [
                    {"id": 98, "name": "Other failed job", "conclusion": "failure", "completed_at": observed_at},
                    {
                        "id": 99,
                        "name": job_name,
                        "conclusion": job_conclusion,
                        "completed_at": (datetime.now(UTC) - timedelta(days=job_age)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                ]
            }
        )
    if reruns:
        server.expect_request("/api/v3/repos/tox-dev/fixture/actions/jobs/99/rerun", method="POST").respond_with_data(
            status=201
        )
    values = (
        os.environ
        | environment
        | {
            "GITHUB_REPOSITORY": "tox-dev/fixture",
            "RUNNER_TEMP": str(tmp_path),
            "MINIMUM_DAYS": "7",
            "WORKFLOW": "check.yaml",
            "JOB_NAME": job_name,
            "GH_TOKEN": environment["GH_ENTERPRISE_TOKEN"],
        }
    )
    action_path = Path(__file__).resolve().parents[2] / "recheck-hook-update-cooldown/action.yml"
    steps = yaml.safe_load(action_path.read_text())["runs"]["steps"]
    assert [step["name"] for step in steps] == ["Find hook update pull requests", "Rerun the failed hook checks"]
    for index, _ in enumerate(steps):
        result = subprocess.run(
            ["bash", str(action_scripts / f"recheck-hook-update-cooldown-{index}.sh")],
            env=values,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    assert [request.path for request, _ in server.log].count(
        "/api/v3/repos/tox-dev/fixture/actions/jobs/99/rerun"
    ) == reruns
