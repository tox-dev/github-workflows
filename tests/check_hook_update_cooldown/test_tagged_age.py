from __future__ import annotations

import base64
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import coverage
import pytest
import yaml
from pytest_httpserver import HTTPServer

from tools.check_tagged_hook_age import check_tagged_hooks

TOOL = Path(__file__).resolve().parents[2] / "tools/check_tagged_hook_age.py"
CONFIG = ".pre-commit-config.yaml"
OLD = "a" * 40
NEW = "b" * 40


def _config(revision: str) -> str:
    return f"repos:\n  - repo: https://github.com/example/hook\n    rev: {revision}\n    hooks: []\n"


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=repository, text=True, capture_output=True, check=True
    ).stdout.strip()


def _repository(tmp_path: Path, *, reintroduce: bool = False) -> tuple[Path, str]:
    repository = tmp_path / "source"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Test")
    _git(repository, "config", "user.email", "test@example.com")
    (repository / CONFIG).write_text(_config(OLD))
    _git(repository, "add", CONFIG)
    _git(repository, "commit", "-qm", "Initial hooks")
    _git(repository, "tag", "v1.0.0")
    (repository / CONFIG).write_text(_config(NEW))
    _git(repository, "commit", "-qam", "Change hooks")
    introduction = _git(repository, "rev-parse", "HEAD")
    if reintroduce:
        (repository / CONFIG).write_text(_config(OLD))
        _git(repository, "commit", "-qam", "Remove new hook")
        (repository / CONFIG).write_text(_config(NEW))
        _git(repository, "commit", "-qam", "Restore new hook directly")
    _git(repository, "tag", "v1.1.0")
    return repository, introduction


def _timestamp(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def _expect_release(server: HTTPServer, tag: str = "v1.0.0") -> None:
    server.expect_request("/api/v3/repos/tox-dev/fixture/releases", query_string="per_page=100").respond_with_json(
        [{"tag_name": tag, "draft": False, "published_at": _timestamp(30)}]
    )


def _expect_pull(server: HTTPServer, introduction: str, *, merged_days: int, revision: str = NEW) -> None:
    server.expect_request(
        f"/api/v3/repos/tox-dev/fixture/commits/{introduction}/pulls", query_string="per_page=100"
    ).respond_with_json(
        [
            {
                "number": 7,
                "merge_commit_sha": introduction,
                "merged_at": _timestamp(merged_days),
                "created_at": _timestamp(20),
                "base": {"repo": {"full_name": "tox-dev/fixture"}},
                "head": {"repo": {"full_name": "gaborbernat/fixture"}, "ref": "feature", "sha": "c" * 40},
            }
        ]
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7/files", query_string="per_page=100").respond_with_json(
        [{"filename": CONFIG}]
    )
    if merged_days < 7:
        server.expect_request(
            f"/api/v3/repos/gaborbernat/fixture/contents/{CONFIG}", query_string=f"ref={'c' * 40}"
        ).respond_with_json({"content": base64.b64encode(_config(revision).encode()).decode()})


def _run(repository: Path, environment: dict[str, str], tag: str = "v1.1.0") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(TOOL.parents[1] / ".release-tools/bin/python"), str(TOOL), "tox-dev/fixture", tag],
        cwd=repository,
        env=os.environ
        | environment
        | {
            "PYTHONPATH": str(TOOL.parents[1] / "tests/coverage_bootstrap"),
            "GW_COVERAGE_SITE_PACKAGES": str(Path(coverage.__file__).parent.parent),
        },
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("merged_days", "head_revision", "accepted"),
    [
        pytest.param(10, NEW, True, id="old-merged-pr-survives-deleted-fork"),
        pytest.param(0, OLD, False, id="recent-pr-head-lacks-pair"),
    ],
)
def test_tagged_hook_age_binds_introducing_pull_request(
    tmp_path: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    merged_days: int,
    head_revision: str,
    accepted: bool,
) -> None:
    server, environment = github_api
    repository, introduction = _repository(tmp_path)
    _expect_release(server)
    _expect_pull(server, introduction, merged_days=merged_days, revision=head_revision)

    result = _run(repository, environment)

    assert (result.returncode == 0) is accepted, result.stderr
    server.check_assertions()


def test_tagged_hook_age_rejects_direct_reintroduction(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository, introduction = _repository(tmp_path, reintroduce=True)
    _expect_release(server)
    server.expect_request(
        f"/api/v3/repos/tox-dev/fixture/commits/{_git(repository, 'rev-parse', 'HEAD')}/pulls",
        query_string="per_page=100",
    ).respond_with_json([])

    result = _run(repository, environment)

    assert result.returncode != 0
    assert "seven-day GitHub observation" in result.stderr
    assert all(introduction not in request.path for request, _ in server.log)


@pytest.mark.parametrize(
    ("observed_days", "observed_revision", "accepted"),
    [
        pytest.param(10, NEW, True, id="old-run-with-pair"),
        pytest.param(0, NEW, False, id="recent-run-with-pair"),
        pytest.param(10, OLD, False, id="old-run-before-pair"),
    ],
)
def test_tagged_hook_age_checks_observed_run_content(
    tmp_path: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    observed_days: int,
    observed_revision: str,
    accepted: bool,
) -> None:
    server, environment = github_api
    repository, introduction = _repository(tmp_path)
    _expect_release(server)
    _expect_pull(server, introduction, merged_days=0)
    server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs").respond_with_json(
        {
            "workflow_runs": [
                {
                    "event": "pull_request",
                    "head_repository": {"full_name": "gaborbernat/fixture"},
                    "head_branch": "feature",
                    "head_sha": "d" * 40,
                    "created_at": _timestamp(observed_days),
                    "pull_requests": [],
                }
            ]
        }
    )
    if observed_days >= 7:
        server.expect_request(
            f"/api/v3/repos/gaborbernat/fixture/contents/{CONFIG}", query_string=f"ref={'d' * 40}"
        ).respond_with_json({"content": base64.b64encode(_config(observed_revision).encode()).decode()})

    result = _run(repository, environment)

    assert (result.returncode == 0) is accepted, result.stderr
    server.check_assertions()


def test_tagged_hook_age_tries_another_observed_head_after_404(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository, introduction = _repository(tmp_path)
    _expect_release(server)
    _expect_pull(server, introduction, merged_days=0)
    runs = [
        {
            "event": "pull_request",
            "head_repository": {"full_name": "gaborbernat/fixture"},
            "head_branch": "feature",
            "head_sha": revision * 40,
            "created_at": _timestamp(10),
            "pull_requests": [],
        }
        for revision in ("e", "d")
    ]
    server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs").respond_with_json({"workflow_runs": runs})
    server.expect_request(
        f"/api/v3/repos/gaborbernat/fixture/contents/{CONFIG}", query_string=f"ref={'e' * 40}"
    ).respond_with_data("Not Found", status=404)
    server.expect_request(
        f"/api/v3/repos/gaborbernat/fixture/contents/{CONFIG}", query_string=f"ref={'d' * 40}"
    ).respond_with_json({"content": base64.b64encode(_config(NEW).encode()).decode()})

    result = _run(repository, environment)

    assert result.returncode == 0, result.stderr
    server.check_assertions()


def test_tagged_hook_age_rejects_shallow_checkout(tmp_path: Path) -> None:
    repository, _ = _repository(tmp_path)
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", repository.as_uri(), str(shallow)],
        check=True,
        capture_output=True,
    )

    result = _run(shallow, {})

    assert result.returncode != 0
    assert "complete git history and tags" in result.stderr


@pytest.mark.parametrize(
    ("previous_tag", "foreign_tag", "current_tag"),
    [
        pytest.param("tox-toml-fmt/1.0.0", "pyproject-fmt/9.0.0", "tox-toml-fmt/1.1.0", id="package-stream"),
        pytest.param("v1.0.0", "v1.1.0", "v1.2.0", id="side-branch-release"),
    ],
)
def test_tagged_hook_age_ignores_other_release_lineage(
    tmp_path: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    previous_tag: str,
    foreign_tag: str,
    current_tag: str,
) -> None:
    server, environment = github_api
    repository, introduction = _repository(tmp_path)
    _git(repository, "tag", "-d", "v1.0.0", "v1.1.0")
    _git(repository, "tag", previous_tag, "HEAD^")
    if foreign_tag.startswith("v"):
        main_branch = _git(repository, "branch", "--show-current")
        _git(repository, "branch", "side", "HEAD^")
        _git(repository, "checkout", "-q", "side")
        (repository / CONFIG).write_text(_config(NEW))
        _git(repository, "commit", "-qam", "Add hook on side branch")
        _git(repository, "tag", foreign_tag)
        _git(repository, "checkout", "-q", main_branch)
    else:
        _git(repository, "tag", foreign_tag)
    _git(repository, "tag", current_tag)
    server.expect_request("/api/v3/repos/tox-dev/fixture/releases", query_string="per_page=100").respond_with_json(
        [
            {"tag_name": foreign_tag, "draft": False, "published_at": _timestamp(20)},
            {"tag_name": previous_tag, "draft": False, "published_at": _timestamp(30)},
        ]
    )
    server.expect_request(
        f"/api/v3/repos/tox-dev/fixture/commits/{introduction}/pulls", query_string="per_page=100"
    ).respond_with_json([])

    result = _run(repository, environment, current_tag)

    assert result.returncode != 0
    assert "seven-day GitHub observation" in result.stderr
    server.check_assertions()


def test_tagged_hook_age_ignores_public_tag_on_merged_side_branch(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository, side_commit = _repository(tmp_path)
    main_branch = _git(repository, "branch", "--show-current")
    _git(repository, "tag", "-d", "v1.1.0")
    _git(repository, "branch", "side")
    _git(repository, "reset", "--hard", "HEAD^")
    _git(repository, "checkout", "-q", "side")
    _git(repository, "tag", "v1.1.0")
    _git(repository, "checkout", "-q", main_branch)
    _git(repository, "merge", "--no-ff", "-m", "Merge side hooks", "side")
    merge = _git(repository, "rev-parse", "HEAD")
    _git(repository, "tag", "v1.2.0")
    server.expect_request("/api/v3/repos/tox-dev/fixture/releases", query_string="per_page=100").respond_with_json(
        [
            {"tag_name": "v1.1.0", "draft": False, "published_at": _timestamp(20)},
            {"tag_name": "v1.0.0", "draft": False, "published_at": _timestamp(30)},
        ]
    )
    server.expect_request(
        f"/api/v3/repos/tox-dev/fixture/commits/{merge}/pulls", query_string="per_page=100"
    ).respond_with_json([])

    result = _run(repository, environment, "v1.2.0")

    assert result.returncode != 0
    assert "seven-day GitHub observation" in result.stderr
    assert all(side_commit not in request.path for request, _ in server.log)


@pytest.mark.parametrize(
    ("tag", "accepted"),
    [pytest.param("v1.1.0", True, id="dispatched-tag"), pytest.param("v1.0.0", False, id="wrong-checkout")],
)
def test_dispatched_release_requires_checkout_at_tag(tmp_path: Path, tag: str, accepted: bool) -> None:
    repository, _ = _repository(tmp_path)
    action = yaml.safe_load((TOOL.parents[1] / "verify-frozen-hooks/action.yml").read_text())
    step = next(item for item in action["runs"]["steps"] if item.get("name") == "Check tagged hook revision provenance")
    assert step["if"] == "inputs.tag != '' || startsWith(github.ref, 'refs/tags/')"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/bin/sh\nexit 0\n")
    fake_uv.chmod(0o755)

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=repository,
        env=os.environ
        | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "TAG": tag,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ACTION_PATH": str(TOOL.parent),
            "GITHUB_REPOSITORY": "tox-dev/fixture",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode == 0) is accepted, result.stderr


@pytest.mark.parametrize(
    ("repository", "tag", "config"),
    [
        pytest.param("", "v1.0.0", CONFIG, id="missing-repository"),
        pytest.param("tox-dev/fixture", "", CONFIG, id="missing-tag"),
        pytest.param("tox-dev/fixture", "v1.0.0", "/tmp/hooks.yaml", id="absolute-config"),
        pytest.param("tox-dev/fixture", "v1.0.0", "../hooks.yaml", id="traversing-config"),
    ],
)
def test_tagged_hook_age_rejects_invalid_arguments(repository: str, tag: str, config: str) -> None:
    with pytest.raises(ValueError, match="relative config path"):
        check_tagged_hooks(repository, tag, config)


@pytest.mark.parametrize(
    ("content", "error"),
    [
        pytest.param("[]\n", "repository list", id="non-mapping"),
        pytest.param("repos: null\n", "repository list", id="missing-list"),
        pytest.param("repos:\n  - 1\n", "needs a URL", id="non-mapping-repository"),
        pytest.param("repos:\n  - repo: 1\n", "needs a URL", id="invalid-url"),
        pytest.param("repos:\n  - repo: https://github.com/example/hook\n", "needs a revision", id="missing-rev"),
    ],
)
def test_tagged_hook_age_rejects_malformed_configuration(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]], content: str, error: str
) -> None:
    server, environment = github_api
    repository, _ = _repository(tmp_path)
    _expect_release(server)
    (repository / CONFIG).write_text(content)

    result = _run(repository, environment)

    assert result.returncode != 0
    assert error in result.stderr


def test_tagged_hook_age_accepts_unchanged_revision(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository, _ = _repository(tmp_path)
    _git(repository, "tag", "-d", "v1.1.0")
    _git(repository, "reset", "--hard", "HEAD^")
    _git(repository, "commit", "--allow-empty", "-qm", "No hook changes")
    _git(repository, "tag", "v1.1.0")
    _expect_release(server)

    result = _run(repository, environment)

    assert result.returncode == 0, result.stderr


def test_tagged_hook_age_accepts_local_only_configuration(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository, _ = _repository(tmp_path)
    _expect_release(server)
    (repository / CONFIG).write_text("repos:\n  - repo: local\n    hooks: []\n  - repo: meta\n    hooks: []\n")

    result = _run(repository, environment)

    assert result.returncode == 0, result.stderr


def test_tagged_hook_age_rejects_invalid_tag_and_api_failure(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository, _ = _repository(tmp_path)
    _expect_release(server)

    invalid = _run(repository, environment, "not-a-release")

    assert invalid.returncode != 0
    assert "cannot select prior release tag" in invalid.stderr
    server.clear()
    server.expect_request("/api/v3/repos/tox-dev/fixture/releases", query_string="per_page=100").respond_with_data(
        "server error", status=503
    )

    unavailable = _run(repository, environment)

    assert unavailable.returncode != 0
    assert "GitHub API request failed" in unavailable.stderr


def test_tagged_hook_age_rejects_missing_git_repository(tmp_path: Path) -> None:
    result = _run(tmp_path, {})

    assert result.returncode != 0
    assert "git rev-parse" in result.stderr


def test_tagged_hook_age_requires_proof_for_first_release(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository, introduction = _repository(tmp_path)
    server.expect_request("/api/v3/repos/tox-dev/fixture/releases", query_string="per_page=100").respond_with_json([])
    for commit in (_git(repository, "rev-parse", "HEAD^"), introduction):
        server.expect_request(
            f"/api/v3/repos/tox-dev/fixture/commits/{commit}/pulls", query_string="per_page=100"
        ).respond_with_json([])

    result = _run(repository, environment)

    assert result.returncode != 0
    assert "seven-day GitHub observation" in result.stderr
    server.check_assertions()


@pytest.mark.parametrize("case", ["unrelated-pull", "unchanged-file", "deleted-fork"], ids=str)
def test_tagged_hook_age_rejects_unproven_introducing_pull(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]], case: str
) -> None:
    server, environment = github_api
    repository, introduction = _repository(tmp_path)
    _expect_release(server)
    pull = {
        "number": 7,
        "merge_commit_sha": "0" * 40 if case == "unrelated-pull" else introduction,
        "merged_at": _timestamp(0),
        "created_at": _timestamp(20),
        "base": {"repo": {"full_name": "tox-dev/fixture"}},
        "head": {
            "repo": None if case == "deleted-fork" else {"full_name": "gaborbernat/fixture"},
            "ref": "feature",
            "sha": "c" * 40,
        },
    }
    server.expect_request(
        f"/api/v3/repos/tox-dev/fixture/commits/{introduction}/pulls", query_string="per_page=100"
    ).respond_with_json([pull])
    if case != "unrelated-pull":
        server.expect_request(
            "/api/v3/repos/tox-dev/fixture/pulls/7/files", query_string="per_page=100"
        ).respond_with_json([{"filename": "README.md" if case == "unchanged-file" else CONFIG}])

    result = _run(repository, environment)

    assert result.returncode != 0
    assert "seven-day GitHub observation" in result.stderr
    server.check_assertions()


@pytest.mark.parametrize("case", ["other-pull", "server-error"], ids=str)
def test_tagged_hook_age_rejects_untrusted_or_unavailable_run(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]], case: str
) -> None:
    server, environment = github_api
    repository, introduction = _repository(tmp_path)
    _expect_release(server)
    _expect_pull(server, introduction, merged_days=0)
    server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs").respond_with_json(
        {
            "workflow_runs": [
                {
                    "event": "pull_request",
                    "head_repository": {"full_name": "gaborbernat/fixture"},
                    "head_branch": "feature",
                    "head_sha": "d" * 40,
                    "created_at": _timestamp(10),
                    "pull_requests": [{"number": 8}] if case == "other-pull" else [],
                }
            ]
        }
    )
    if case == "server-error":
        server.expect_request(
            f"/api/v3/repos/gaborbernat/fixture/contents/{CONFIG}", query_string=f"ref={'d' * 40}"
        ).respond_with_data("server error", status=503)

    result = _run(repository, environment)

    assert result.returncode != 0
    assert ("seven-day GitHub observation" if case == "other-pull" else "GitHub API request failed") in result.stderr
    server.check_assertions()
