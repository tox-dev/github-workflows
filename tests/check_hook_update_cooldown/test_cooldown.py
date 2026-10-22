from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from textwrap import dedent

import pytest
import yaml
from pytest_httpserver import HTTPServer


def test_action_uses_scoped_job_token() -> None:
    action = yaml.safe_load((Path(__file__).resolve().parents[2] / "check-hook-update-cooldown/action.yml").read_text())
    assert [step["env"]["GH_TOKEN"] for step in action["runs"]["steps"] if "GH_TOKEN" in step.get("env", {})] == [
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
    if author == "pre-commit-ci[bot]":
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
                "/api/v3/repos/tox-dev/fixture/actions/runs",
                "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
                "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
            ]
            if author == "pre-commit-ci[bot]"
            else []
        ),
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
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode != 0
    assert "pull request head is still in its cooldown period" in result.stderr
    assert len(server.log) == 2


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
        tmp_path,
        environment,
        event_name=event_name,
        event_head="c" * 40,
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
    tools = tmp_path / "hook-tools" / "bin"
    tools.mkdir(parents=True)
    for name in ("prek", "yq"):
        executable = shutil.which(name)
        assert executable is not None
        (tools / name).symlink_to(executable)
    steps = yaml.safe_load((Path(__file__).resolve().parents[2] / "check-hook-update-cooldown/action.yml").read_text())[
        "runs"
    ]["steps"]
    values = (
        os.environ
        | environment
        | {
            "REPOSITORY": "tox-dev/fixture",
            "PR_NUMBER": "7",
            "HEAD_SHA": "a" * 40,
            "MINIMUM_DAYS": "7",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_EVENT_NAME": event_name,
            "GITHUB_EVENT_PATH": str(path),
            "GITHUB_OUTPUT": str(tmp_path / "outputs"),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "check-hook-update-cooldown"),
            "GH_TOKEN": environment["GH_ENTERPRISE_TOKEN"],
        }
    )
    result = subprocess.CompletedProcess[str]([], 0, "", "")
    for index, step in enumerate(steps):
        if "run" not in step or step.get("name") == "Install locked hook tools":
            continue
        if step.get("if") and not (tmp_path / "outputs").exists():
            continue
        result = subprocess.run(
            ["bash", str(action_scripts / f"check-hook-update-cooldown-{index}.sh")],
            cwd=tmp_path,
            env=values,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            break
    return result


def expect_pull(
    server: HTTPServer, *, author: str, head: str = "a" * 40, observed_days: int = 10, updated_days: int = 0
) -> None:
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7", method="GET").respond_with_json(
        {
            "state": "open",
            "base": {"repo": {"full_name": "tox-dev/fixture"}, "sha": "b" * 40},
            "head": {"sha": head, "ref": "bot-update"},
            "user": {"login": author},
            "updated_at": (datetime.now(UTC) - timedelta(days=updated_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    if author == "pre-commit-ci[bot]":
        server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs", method="GET").respond_with_json(
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


def expect_config(server: HTTPServer, sha: str, repository: Path, revision: str) -> None:
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml", method="GET", query_string=f"ref={sha}"
    ).respond_with_json(
        {
            "content": base64.b64encode(
                dedent(
                    f"""\
                    repos:
                      - repo: {repository.as_uri()}
                        rev: {revision}
                        hooks:
                          - id: sample
                    """
                ).encode()
            ).decode()
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
