from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from conftest import action
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
    ("observed_age", "job_age", "job_conclusion", "job_name", "configured_job", "workflow", "reruns"),
    [
        pytest.param(8, 8, "failure", "hook-cooldown", "hook-cooldown", "check.yaml", 1, id="matured-failure"),
        pytest.param(8, 8, "failure", "Hook update cooldown", "hook-cooldown", "check.yaml", 0, id="other-job"),
        pytest.param(
            8,
            8,
            "failure",
            "Hook update cooldown",
            "Hook update cooldown",
            "pr-gate.yaml",
            1,
            id="configured-job-and-workflow",
        ),
        pytest.param(6, 6, "failure", "hook-cooldown", "hook-cooldown", "check.yaml", 0, id="recent-pull"),
        pytest.param(8, 0, "failure", "hook-cooldown", "hook-cooldown", "check.yaml", 1, id="failed-rerun"),
        pytest.param(31, 31, "failure", "hook-cooldown", "hook-cooldown", "check.yaml", 0, id="expired-run"),
        pytest.param(8, 8, "success", "hook-cooldown", "hook-cooldown", "check.yaml", 0, id="successful-job"),
    ],
)
@pytest.mark.parametrize(
    ("login", "author_type", "head_repository"),
    [
        pytest.param("pre-commit-ci[bot]", "Bot", "tox-dev/fixture", id="pre-commit-ci"),
        pytest.param("release-app[bot]", "Bot", "tox-dev/fixture", id="app"),
        pytest.param("gaborbernat", "User", "tox-dev/fixture", id="human"),
        pytest.param("gaborbernat", "User", "gaborbernat/fixture", id="human-fork"),
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
    configured_job: str,
    workflow: str,
    reruns: int,
    login: str,
    author_type: str,
    head_repository: str,
) -> None:
    server, environment = github_api
    observed_at = (datetime.now(UTC) - timedelta(days=observed_age)).strftime("%Y-%m-%dT%H:%M:%SZ")
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls", method="GET").respond_with_json(
        [
            {
                "number": 7,
                "user": {"login": login, "type": author_type},
                "head": {
                    "sha": "a" * 40,
                    "ref": "pre-commit-ci-update-config",
                    "repo": {"full_name": head_repository},
                },
                "base": {"repo": {"full_name": "tox-dev/fixture"}},
                "created_at": (datetime.now(UTC) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ]
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7/files", method="GET").respond_with_json(
        [{"filename": ".pre-commit-config.yaml"}]
    )
    server.expect_request(
        f"/api/v3/repos/tox-dev/fixture/actions/workflows/{workflow}/runs", method="GET"
    ).respond_with_json(
        {
            "workflow_runs": [
                {
                    "id": 42,
                    "event": "pull_request",
                    "head_repository": {"full_name": head_repository},
                    "head_sha": "a" * 40,
                    "head_branch": "pre-commit-ci-update-config",
                    "pull_requests": [{"number": 7}],
                    "status": "completed",
                    "created_at": observed_at,
                }
            ]
        }
    )
    if observed_age >= 7 and observed_age < 30:
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
        server.expect_request("/api/v3/repos/tox-dev/fixture/actions/jobs/99", method="GET").respond_with_json(
            {"id": 99, "run_id": 42, "name": job_name, "status": "completed", "conclusion": "failure"}
        )
        server.expect_request("/api/v3/repos/tox-dev/fixture/actions/jobs/99/rerun", method="POST").respond_with_data(
            status=201
        )
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "recheck-hook-update-cooldown",
        version="",
        GH_TOKEN=environment["GH_ENTERPRISE_TOKEN"],
        JOB_NAME=configured_job,
        WORKFLOW=workflow,
        **environment,
    )
    assert result.returncode == 0, result.stderr
    assert [request.path for request, _ in server.log].count(
        "/api/v3/repos/tox-dev/fixture/actions/jobs/99/rerun"
    ) == reruns


@pytest.mark.parametrize(
    ("head_repository", "opened_days", "reruns"),
    [
        pytest.param("tox-dev/fixture", 20, 1, id="same-repository-unlinked"),
        pytest.param("gaborbernat/fixture", 20, 1, id="fork-unlinked"),
        pytest.param("gaborbernat/fixture", 5, 0, id="observation-predates-pr"),
    ],
)
def test_recheck_observes_unlinked_exact_head(
    github_api: tuple[HTTPServer, dict[str, str]],
    action_scripts: Path,
    tmp_path: Path,
    head_repository: str,
    opened_days: int,
    reruns: int,
) -> None:
    server, environment = github_api
    observed_at = (datetime.now(UTC) - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls", method="GET").respond_with_json(
        [
            {
                "number": 7,
                "head": {"sha": "a" * 40, "ref": "update", "repo": {"full_name": head_repository}},
                "base": {"repo": {"full_name": "tox-dev/fixture"}},
                "created_at": (datetime.now(UTC) - timedelta(days=opened_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ]
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7/files", method="GET").respond_with_json(
        [{"filename": ".pre-commit-config.yaml"}]
    )
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/actions/workflows/check.yaml/runs", method="GET"
    ).respond_with_json(
        {
            "workflow_runs": [
                {
                    "id": 42,
                    "event": "pull_request",
                    "head_repository": {"full_name": head_repository},
                    "head_sha": "a" * 40,
                    "head_branch": "update",
                    "pull_requests": [],
                    "status": "completed",
                    "created_at": observed_at,
                }
            ]
        }
    )
    if reruns:
        server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs/42/jobs", method="GET").respond_with_json(
            {"jobs": [{"id": 99, "name": "hook-cooldown", "conclusion": "failure"}]}
        )
        server.expect_request("/api/v3/repos/tox-dev/fixture/actions/jobs/99", method="GET").respond_with_json(
            {"id": 99, "run_id": 42, "name": "hook-cooldown", "status": "completed", "conclusion": "failure"}
        )
        server.expect_request("/api/v3/repos/tox-dev/fixture/actions/jobs/99/rerun", method="POST").respond_with_data(
            status=201
        )

    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "recheck-hook-update-cooldown",
        version="",
        GH_TOKEN=environment["GH_ENTERPRISE_TOKEN"],
        **environment,
    )

    assert result.returncode == 0, result.stderr
    assert [request.path for request, _ in server.log].count(
        "/api/v3/repos/tox-dev/fixture/actions/jobs/99/rerun"
    ) == reruns


def test_recheck_continues_after_failed_rerun(
    github_api: tuple[HTTPServer, dict[str, str]], action_scripts: Path, tmp_path: Path
) -> None:
    server, environment = github_api
    observed_at = (datetime.now(UTC) - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls", method="GET").respond_with_json(
        [
            {
                "number": number,
                "user": {"login": "release-app[bot]", "type": "Bot"},
                "head": {"sha": str(number) * 40, "ref": f"update-{number}", "repo": {"full_name": "tox-dev/fixture"}},
                "base": {"repo": {"full_name": "tox-dev/fixture"}},
                "created_at": (datetime.now(UTC) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            for number in (7, 8)
        ]
    )
    for number in (7, 8):
        server.expect_request(f"/api/v3/repos/tox-dev/fixture/pulls/{number}/files", method="GET").respond_with_json(
            [{"filename": ".pre-commit-config.yaml"}]
        )
        server.expect_request(
            "/api/v3/repos/tox-dev/fixture/actions/workflows/check.yaml/runs",
            method="GET",
            query_string=f"branch=update-{number}&event=pull_request&per_page=100",
        ).respond_with_json(
            {
                "workflow_runs": [
                    {
                        "id": number + 40,
                        "event": "pull_request",
                        "head_repository": {"full_name": "tox-dev/fixture"},
                        "head_sha": str(number) * 40,
                        "head_branch": f"update-{number}",
                        "pull_requests": [{"number": number}],
                        "status": "completed",
                        "created_at": observed_at,
                    }
                ]
            }
        )
        job = number + 90
        server.expect_request(
            f"/api/v3/repos/tox-dev/fixture/actions/runs/{number + 40}/jobs", method="GET"
        ).respond_with_json({"jobs": [{"id": job, "name": "hook-cooldown", "conclusion": "failure"}]})
        server.expect_request(f"/api/v3/repos/tox-dev/fixture/actions/jobs/{job}", method="GET").respond_with_json(
            {"id": job, "run_id": number + 40, "name": "hook-cooldown", "status": "completed"}
        )
        server.expect_request(
            f"/api/v3/repos/tox-dev/fixture/actions/jobs/{job}/rerun", method="POST"
        ).respond_with_data(status=500 if number == 7 else 201)
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "recheck-hook-update-cooldown",
        version="",
        GH_TOKEN=environment["GH_ENTERPRISE_TOKEN"],
        **environment,
    )
    assert result.returncode == 0, result.stderr
    assert "could not rerun hook cooldown for pull request #7" in result.stderr
    assert [request.path for request, _ in server.log if request.method == "POST"] == [
        "/api/v3/repos/tox-dev/fixture/actions/jobs/97/rerun",
        "/api/v3/repos/tox-dev/fixture/actions/jobs/98/rerun",
    ]


@pytest.mark.parametrize(
    ("older_head_age", "reruns"),
    [pytest.param(8, 1, id="older-head-matured"), pytest.param(3, 0, id="all-heads-recent")],
)
def test_recheck_counts_observations_on_earlier_heads(
    github_api: tuple[HTTPServer, dict[str, str]],
    action_scripts: Path,
    tmp_path: Path,
    older_head_age: int,
    reruns: int,
) -> None:
    server, environment = github_api
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls", method="GET").respond_with_json(
        [
            {
                "number": 7,
                "head": {"sha": "a" * 40, "ref": "update", "repo": {"full_name": "tox-dev/fixture"}},
                "base": {"repo": {"full_name": "tox-dev/fixture"}},
                "created_at": (datetime.now(UTC) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ]
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7/files", method="GET").respond_with_json(
        [{"filename": ".pre-commit-config.yaml"}]
    )
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/actions/workflows/check.yaml/runs",
        method="GET",
        query_string="branch=update&event=pull_request&per_page=100",
    ).respond_with_json(
        {
            "workflow_runs": [
                {
                    "id": run_id,
                    "event": "pull_request",
                    "head_repository": {"full_name": "tox-dev/fixture"},
                    "head_sha": head,
                    "head_branch": "update",
                    "pull_requests": [{"number": 7}],
                    "status": "completed",
                    "created_at": (datetime.now(UTC) - timedelta(days=age)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                for run_id, head, age in ((41, "b" * 40, older_head_age), (42, "a" * 40, 1))
            ]
        }
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs/42/jobs", method="GET").respond_with_json(
        {"jobs": [{"id": 99, "name": "hook-cooldown", "conclusion": "failure"}]}
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/actions/jobs/99", method="GET").respond_with_json(
        {"id": 99, "run_id": 42, "name": "hook-cooldown", "status": "completed", "conclusion": "failure"}
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/actions/jobs/99/rerun", method="POST").respond_with_data(
        status=201
    )

    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "recheck-hook-update-cooldown",
        version="",
        GH_TOKEN=environment["GH_ENTERPRISE_TOKEN"],
        **environment,
    )

    assert result.returncode == 0, result.stderr
    assert [request.path for request, _ in server.log].count(
        "/api/v3/repos/tox-dev/fixture/actions/jobs/99/rerun"
    ) == reruns
