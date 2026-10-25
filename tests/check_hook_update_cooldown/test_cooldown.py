from __future__ import annotations

import base64
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

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
    assert action["runs"]["steps"][0]["env"]["RELEASE_APP_CLIENT_ID"] == "${{ inputs.release-app-client-id }}"
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/check.yaml").read_text())
    caller = workflow["jobs"]["hook-cooldown"]["steps"][0]
    assert caller["with"]["release-app-client-id"] == "${{ vars.RELEASE_APP_CLIENT_ID }}"


def test_action_checks_app_hook_closure_from_pull_request_head() -> None:
    steps = yaml.safe_load((Path(__file__).resolve().parents[2] / "check-hook-update-cooldown/action.yml").read_text())[
        "runs"
    ]["steps"]
    source = next(step for step in steps if step.get("name") == "Read the base and proposed hook configurations")
    closure = next(step for step in steps if step.get("name") == "Verify managed hook dependency closure")

    assert '"repos/$head_repository/contents/.pre-commit-config.yaml?ref=$HEAD_SHA"' in source["run"]
    assert closure["if"] == "steps.identity.outputs.changed == 'true'"
    assert 'cp "$RUNNER_TEMP/proposed-hooks.yaml" "$RUNNER_TEMP/hook-closure/.pre-commit-config.yaml"' in closure["run"]
    assert "release-creator hooks" in closure["run"]
    assert '--check --minimum-days "$MINIMUM_DAYS"' in closure["run"]
    assert closure["env"]["MINIMUM_DAYS"] == "${{ inputs.minimum-days }}"


@pytest.mark.parametrize(
    ("author", "revision", "frozen_base", "accepted"),
    [
        pytest.param("gaborbernat", "v1", False, True, id="human-cooled-revision"),
        pytest.param("gaborbernat", "v2", False, False, id="human-young-revision"),
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
        "/api/v3/repos/tox-dev/fixture/pulls/7/files",
        "/api/v3/repos/tox-dev/fixture/actions/runs",
        "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
        "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
    ]


@pytest.mark.parametrize(
    ("observed_days", "accepted"),
    [pytest.param(10, True, id="cooled"), pytest.param(0, False, id="new")],
)
def test_cooldown_checks_new_human_hook_repository(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    observed_days: int,
    accepted: bool,
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(server, author="gaborbernat", observed_days=observed_days)
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
        method="GET",
        query_string=f"ref={'b' * 40}",
    ).respond_with_json({"content": base64.b64encode(b"repos: []\n").decode()})
    expect_config(server, "a" * 40, repository, "v1", hook="      - id: sample\n        args: [--strict]\n")
    if not accepted:
        expect_historical_runs(server, older_head=None)

    result = run_cooldown(action_scripts, tmp_path, environment)

    assert (result.returncode == 0) is accepted, result.stderr
    if not accepted:
        assert "hook revision has not been observed" in result.stderr


def test_cooldown_checks_fork_head_configuration(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    expect_pull(server, author="gaborbernat", head_repository="gaborbernat/fixture")
    for repository, sha, content in (
        ("tox-dev/fixture", "b" * 40, "repos: []\n"),
        (
            "gaborbernat/fixture",
            "a" * 40,
            (
                "repos:\n  - repo: local\n    hooks:\n      - id: check\n        name: check\n"
                "        entry: true\n        language: system\n"
            ),
        ),
    ):
        server.expect_request(
            f"/api/v3/repos/{repository}/contents/.pre-commit-config.yaml", method="GET", query_string=f"ref={sha}"
        ).respond_with_json({"content": base64.b64encode(content.encode()).decode()})

    result = run_cooldown(action_scripts, tmp_path, environment)

    assert result.returncode == 0, result.stderr
    assert [request.path for request, _ in server.log if request.path.endswith("/.pre-commit-config.yaml")] == [
        "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
        "/api/v3/repos/gaborbernat/fixture/contents/.pre-commit-config.yaml",
    ]


@pytest.mark.parametrize(
    ("head_repository", "observed_repository", "opened_days", "observed_days", "workflow_path", "accepted"),
    [
        pytest.param(
            "gaborbernat/fixture", None, 20, 10, ".github/workflows/check.yaml", True, id="fork-observed-after-open"
        ),
        pytest.param(
            "gaborbernat/fixture", None, 20, 0, ".github/workflows/check.yaml", False, id="fork-observed-too-recently"
        ),
        pytest.param(
            "gaborbernat/fixture", None, 5, 10, ".github/workflows/check.yaml", False, id="old-run-before-new-pr"
        ),
        pytest.param(
            "tox-dev/fixture", None, 20, 10, ".github/workflows/check.yaml", True, id="same-repository-unlinked-run"
        ),
        pytest.param(
            "gaborbernat/fixture",
            "another/fixture",
            20,
            10,
            ".github/workflows/check.yaml",
            False,
            id="same-branch-other-fork",
        ),
        pytest.param(
            "gaborbernat/fixture", None, 20, 10, ".github/workflows/news.yaml", False, id="unrelated-workflow"
        ),
    ],
)
def test_cooldown_checks_unlinked_run_identity(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    head_repository: str,
    observed_repository: str | None,
    opened_days: int,
    observed_days: int,
    workflow_path: str,
    accepted: bool,
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(
        server,
        author="gaborbernat",
        head_repository=head_repository,
        opened_days=opened_days,
        observed_days=observed_days,
        associated_pull_request=None,
        observed_repository=observed_repository,
        workflow_path=workflow_path,
    )
    expect_config(server, "b" * 40, repository, "v0")
    expect_config(server, "a" * 40, repository, "v1", source_repository=head_repository)
    if not accepted:
        expect_historical_runs(server, older_head=None)

    result = run_cooldown(action_scripts, tmp_path, environment)

    assert (result.returncode == 0) is accepted, result.stderr
    if not accepted:
        assert "hook revision has not been observed" in result.stderr


@pytest.mark.parametrize(
    ("head_repository", "opened_days", "observed_repository", "workflow_path", "accepted"),
    [
        pytest.param(
            "gaborbernat/fixture", 20, "gaborbernat/fixture", ".github/workflows/check.yaml", True, id="fork-history"
        ),
        pytest.param(
            "tox-dev/fixture", 20, "tox-dev/fixture", ".github/workflows/check.yaml", True, id="same-repository-history"
        ),
        pytest.param(
            "gaborbernat/fixture",
            5,
            "gaborbernat/fixture",
            ".github/workflows/check.yaml",
            False,
            id="earlier-pr-same-branch",
        ),
        pytest.param(
            "gaborbernat/fixture",
            20,
            "another/fixture",
            ".github/workflows/check.yaml",
            False,
            id="same-branch-other-fork",
        ),
        pytest.param(
            "gaborbernat/fixture",
            20,
            "gaborbernat/fixture",
            ".github/workflows/news.yaml",
            False,
            id="unrelated-workflow",
        ),
    ],
)
def test_cooldown_checks_unlinked_history(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    head_repository: str,
    opened_days: int,
    observed_repository: str,
    workflow_path: str,
    accepted: bool,
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(
        server,
        author="gaborbernat",
        head_repository=head_repository,
        opened_days=opened_days,
        observed_days=0,
        associated_pull_request=None,
    )
    expect_config(server, "b" * 40, repository, "v0")
    expect_config(server, "a" * 40, repository, "v1", source_repository=head_repository)
    expect_historical_runs(
        server,
        older_head="c" * 40,
        head_repository=observed_repository,
        pull_request=None,
        workflow_path=workflow_path,
    )
    if accepted:
        expect_config(server, "c" * 40, repository, "v1", source_repository=head_repository)

    result = run_cooldown(action_scripts, tmp_path, environment)

    assert (result.returncode == 0) is accepted, result.stderr
    if not accepted:
        assert "hook revision has not been observed" in result.stderr


@pytest.mark.parametrize(
    ("minimum_days", "accepted"),
    [pytest.param("7", True, id="default"), pytest.param("1000", False, id="configured-cooldown")],
)
def test_cooldown_checks_human_local_hook_dependencies(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    minimum_days: str,
    accepted: bool,
) -> None:
    server, environment = github_api
    expect_pull(server, author="gaborbernat", observed_days=1100)
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
        method="GET",
        query_string=f"ref={'b' * 40}",
    ).respond_with_json({"content": base64.b64encode(b"repos: []\n").decode()})
    proposed = (
        "repos:\n  - repo: local\n    hooks:\n      - id: check\n        name: check\n"
        "        entry: python\n        language: python\n"
        "        additional_dependencies:\n          - packaging==25.0\n"
    )
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml",
        method="GET",
        query_string=f"ref={'a' * 40}",
    ).respond_with_json({"content": base64.b64encode(proposed.encode()).decode()})

    result = run_cooldown(action_scripts, tmp_path, environment, minimum_days=minimum_days)

    assert (result.returncode == 0) is accepted, result.stderr
    assert (tmp_path / "hook-closure/.pre-commit-config.yaml").read_text() == proposed


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("prek.toml", id="root-prek-toml"),
        pytest.param("sub/prek.toml", id="nested-prek-toml"),
        pytest.param(".pre-commit-config.yml", id="root-yml"),
        pytest.param("sub/.pre-commit-config.yaml", id="nested-yaml"),
        pytest.param("sub/.pre-commit-config.yml", id="nested-yml"),
    ],
)
def test_cooldown_rejects_other_hook_configuration(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]], path: str
) -> None:
    server, environment = github_api
    expect_pull(server, author="gaborbernat", hook_update=False, other_files=(("added", path),))

    result = run_cooldown(action_scripts, tmp_path, environment)

    assert result.returncode != 0
    assert f"only in the root .pre-commit-config.yaml: {path}" in result.stderr


def test_cooldown_allows_removing_other_hook_configuration(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    expect_pull(server, author="gaborbernat", hook_update=False, other_files=(("removed", "prek.toml"),))

    result = run_cooldown(action_scripts, tmp_path, environment)

    assert result.returncode == 0, result.stderr


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


def test_cooldown_skips_unrelated_human_fork(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    expect_pull(server, author="gaborbernat", head_repository="gaborbernat/fixture", hook_update=False)

    result = run_cooldown(action_scripts, tmp_path, environment)

    assert result.returncode == 0, result.stderr
    assert [request.path for request, _ in server.log] == [
        "/api/v3/repos/tox-dev/fixture/pulls/7",
        "/api/v3/repos/tox-dev/fixture/pulls/7/files",
    ]


@pytest.mark.parametrize(
    "dependency_location",
    [pytest.param("project", id="project"), pytest.param("manifest", id="manifest")],
)
def test_cooldown_rejects_rev_only_hook_with_new_dependency(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    dependency_location: Literal["project", "manifest"],
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path, dependency_location=dependency_location)
    expect_pull(server, author="pre-commit-ci[bot]")
    for ref, tag in (("b" * 40, "v0"), ("a" * 40, "v1")):
        revision = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", f"{tag}^{{}}"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        expect_config(server, ref, repository, revision)

    result = run_cooldown(action_scripts, tmp_path, environment)

    assert result.returncode != 0
    assert "hook is missing managed dependencies" in result.stderr


@pytest.mark.parametrize(
    ("observed_days", "accepted"),
    [pytest.param(0, False, id="new"), pytest.param(10, True, id="cooled")],
)
def test_cooldown_checks_generated_update_branch(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    observed_days: int,
    accepted: bool,
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(
        server, author="release-app[bot]", branch="automation/update-release-tools", observed_days=observed_days
    )
    for ref, tag in (("b" * 40, "v0"), ("a" * 40, "v1")):
        revision = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", f"{tag}^{{}}"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        expect_config(server, ref, repository, revision)
    if not accepted:
        expect_historical_runs(server, older_head=None)

    result = run_cooldown(action_scripts, tmp_path, environment | {"RELEASE_APP_CLIENT_ID": "Iv1.release"})

    assert (result.returncode == 0) is accepted, result.stderr
    assert len(server.log) >= 4


@pytest.mark.parametrize(
    "marker",
    [
        pytest.param('python_version >= "3.15"', id="active"),
        pytest.param('python_version < "3.15"', id="inactive"),
    ],
)
def test_cooldown_accepts_managed_pin_with_python_marker(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    marker: str,
) -> None:
    server, environment = github_api
    source = (
        "repos:\n  - repo: local\n    hooks:\n      - id: lint\n        name: lint\n"
        "        entry: echo\n        language: python\n"
        "        additional_dependencies:\n"
        f"          - 'packaging>=24,<25; {marker}'\n"
        f"          - 'packaging==24.2; {marker}' # release-creator managed\n"
    )
    expect_pull(server, author="release-app[bot]", branch="automation/update-release-tools")
    for ref in ("b" * 40, "a" * 40):
        server.expect_request(
            "/api/v3/repos/tox-dev/fixture/contents/.pre-commit-config.yaml", method="GET", query_string=f"ref={ref}"
        ).respond_with_json({"content": base64.b64encode(source.encode()).decode()})

    result = run_cooldown(action_scripts, tmp_path, environment | {"RELEASE_APP_CLIENT_ID": "Iv1.release"})

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "hook-closure/.pre-commit-config.yaml").read_text() == source


@pytest.mark.parametrize(
    ("author", "client_id"),
    [
        pytest.param("gaborbernat", "Iv1.release", id="human-author"),
        pytest.param("release-app[bot]", "", id="unconfigured-app"),
    ],
)
def test_cooldown_requires_configured_app_on_updater_branch(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]], author: str, client_id: str
) -> None:
    server, environment = github_api
    expect_pull(server, author=author, branch="automation/update-release-tools")

    result = run_cooldown(action_scripts, tmp_path, environment | {"RELEASE_APP_CLIENT_ID": client_id})

    assert result.returncode != 0
    assert "release tool branch requires the configured release App" in result.stderr
    assert "/api/v3/apps/release-app" not in [request.path for request, _ in server.log]


@pytest.mark.parametrize(
    ("client_id", "head_repository"),
    [
        pytest.param("Iv1.other", "tox-dev/fixture", id="another-app"),
        pytest.param("Iv1.release", "other/fixture", id="fork-head"),
    ],
)
def test_cooldown_rejects_untrusted_updater_identity(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    client_id: str,
    head_repository: str,
) -> None:
    server, environment = github_api
    expect_pull(
        server,
        author="release-app[bot]",
        branch="automation/update-release-tools",
        app_client_id=client_id,
        head_repository=head_repository,
    )

    result = run_cooldown(action_scripts, tmp_path, environment | {"RELEASE_APP_CLIENT_ID": "Iv1.release"})

    assert result.returncode != 0
    assert (
        "different App identity" in result.stderr
        if head_repository == "tox-dev/fixture"
        else [request.path for request, _ in server.log]
        == ["/api/v3/repos/tox-dev/fixture/pulls/7", "/api/v3/repos/tox-dev/fixture/pulls/7/files"]
    )


def test_cooldown_rejects_hook_configuration_change(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(server, author="pre-commit-ci[bot]")
    expect_config(server, "b" * 40, repository, "v0")
    expect_config(server, "a" * 40, repository, "v1", hook="      - id: sample\n        entry: untrusted\n")

    result = run_cooldown(action_scripts, tmp_path, environment)

    assert result.returncode != 0
    assert "changes fields beyond revisions" in result.stderr


def test_cooldown_rejects_changed_head(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    expect_pull(server, author="pre-commit-ci[bot]", head="c" * 40)
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode != 0
    assert len(server.log) == 1


@pytest.mark.parametrize(
    "minimum_days",
    [
        pytest.param("6", id="short"),
        pytest.param("07", id="leading-zero"),
        pytest.param("bad", id="non-numeric"),
    ],
)
def test_cooldown_rejects_invalid_minimum(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]], minimum_days: str
) -> None:
    server, environment = github_api
    result = run_cooldown(action_scripts, tmp_path, environment, minimum_days=minimum_days)
    assert result.returncode != 0
    assert "minimum-days must be a whole number of at least seven" in result.stderr
    assert not server.log


def test_cooldown_rejects_bot_without_observed_run(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    repository = hook_repository(tmp_path)
    expect_pull(server, author="pre-commit-ci[bot]", observed_days=None)
    expect_config(server, "b" * 40, repository, "v0")
    expect_config(server, "a" * 40, repository, "v1")
    expect_historical_runs(server, older_head=None)
    result = run_cooldown(action_scripts, tmp_path, environment)
    assert result.returncode != 0
    assert "hook revision has not been observed" in result.stderr


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
    prior_revision = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "v1^{}"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    historical = (
        "repos:\n"
        "  - repo: https://example.invalid/another-hook\n    rev: v2\n    hooks: []\n"
        f"  - repo: {repository.as_uri()}\n    rev: {prior_revision}\n    hooks:\n      - id: sample\n"
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


def run_cooldown(
    action_scripts: Path,
    tmp_path: Path,
    environment: dict[str, str],
    *,
    event_name: str = "pull_request",
    event_head: str = "a" * 40,
    minimum_days: str = "7",
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
        MINIMUM_DAYS=minimum_days,
        GITHUB_EVENT_NAME=event_name,
        GITHUB_EVENT_PATH=str(path),
        GITHUB_OUTPUT=str(tmp_path / "outputs"),
        GITHUB_WORKFLOW_REF="tox-dev/fixture/.github/workflows/check.yaml@refs/pull/7/merge",
        **environment,
    )


def expect_pull(
    server: HTTPServer,
    *,
    author: str,
    head: str = "a" * 40,
    observed_days: int | None = 10,
    updated_days: int = 0,
    hook_update: bool = True,
    branch: str = "bot-update",
    app_client_id: str = "Iv1.release",
    head_repository: str = "tox-dev/fixture",
    opened_days: int = 20,
    associated_pull_request: int | None = 7,
    observed_repository: str | None = None,
    workflow_path: str = ".github/workflows/check.yaml",
    other_files: tuple[tuple[str, str], ...] = (),
) -> None:
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7", method="GET").respond_with_json(
        {
            "state": "open",
            "base": {"repo": {"full_name": "tox-dev/fixture"}, "sha": "b" * 40},
            "head": {"sha": head, "ref": branch, "repo": {"full_name": head_repository}},
            "user": {"login": author, "type": "Bot" if author.endswith("[bot]") else "User"},
            "created_at": (datetime.now(UTC) - timedelta(days=opened_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": (datetime.now(UTC) - timedelta(days=updated_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7/files", method="GET").respond_with_json(
        [
            {"status": "modified", "filename": ".pre-commit-config.yaml" if hook_update else "pyproject.toml"},
            *({"status": status, "filename": filename} for status, filename in other_files),
        ]
    )
    if hook_update:
        if author.endswith("[bot]") and branch == "automation/update-release-tools":
            server.expect_request("/api/v3/apps/release-app", method="GET").respond_with_json(
                {"slug": "release-app", "client_id": app_client_id}
            )
        server.expect_request(
            "/api/v3/repos/tox-dev/fixture/actions/runs",
            method="GET",
            query_string=f"event=pull_request&head_sha={head}&per_page=100",
        ).respond_with_json(
            {
                "workflow_runs": []
                if observed_days is None
                else [
                    {
                        "event": "pull_request",
                        "head_repository": {"full_name": observed_repository or head_repository},
                        "head_branch": branch,
                        "head_sha": head,
                        "pull_requests": []
                        if associated_pull_request is None
                        else [{"number": associated_pull_request}],
                        "path": workflow_path,
                        "created_at": (datetime.now(UTC) - timedelta(days=observed_days)).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                    }
                ]
            }
        )


def expect_config(
    server: HTTPServer,
    sha: str,
    repository: Path,
    revision: str | tuple[str, ...],
    *,
    hook: str = "      - id: sample\n",
    source_repository: str = "tox-dev/fixture",
) -> None:
    revisions = (revision,) if isinstance(revision, str) else revision
    frozen = tuple(
        item
        if len(item) == 40
        else subprocess.run(
            ["git", "-C", str(repository), "rev-parse", f"{item}^{{}}"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        for item in revisions
    )
    server.expect_request(
        f"/api/v3/repos/{source_repository}/contents/.pre-commit-config.yaml",
        method="GET",
        query_string=f"ref={sha}",
    ).respond_with_json(
        {
            "content": base64.b64encode(
                (
                    "repos:\n"
                    + "".join(
                        f"  - repo: {repository.as_uri()}\n    rev: {item}\n    hooks:\n{hook}" for item in frozen
                    )
                ).encode()
            ).decode()
        }
    )


def expect_historical_runs(
    server: HTTPServer,
    *,
    older_head: str | tuple[str, ...] | None,
    pull_request: int | None = 7,
    head_repository: str = "tox-dev/fixture",
    workflow_path: str = ".github/workflows/check.yaml",
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
                    "head_repository": {"full_name": head_repository},
                    "head_branch": "bot-update",
                    "head_sha": head,
                    "pull_requests": [] if pull_request is None else [{"number": pull_request}],
                    "path": workflow_path,
                    "created_at": (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                for head in heads
            ]
        }
    )


def hook_repository(tmp_path: Path, *, dependency_location: Literal["project", "manifest"] | None = None) -> Path:
    repository = tmp_path / "hook-repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Hook test"], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.email", "hooks@example.org"], check=True)
    (repository / ".pre-commit-hooks.yaml").write_text(
        f"- id: sample\n  name: sample\n  entry: true\n  language: {'python' if dependency_location else 'system'}\n"
    )
    if dependency_location:
        (repository / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["setuptools==80.9.0"]\nbuild-backend = "setuptools.build_meta"\n'
            '[project]\nname = "hook-fixture"\nversion = "0.1.0"\ndependencies = []\n'
        )
        package = repository / "src/hook_fixture"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text('"""Hook fixture."""\n')
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "Add hook"], check=True)
    for name, days in (("v0", 20), ("v0.5", 15), ("v1", 10), ("v2", 1)):
        date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (repository / "version").write_text(name)
        if dependency_location == "project" and name == "v1":
            project = repository / "pyproject.toml"
            project.write_text(project.read_text().replace("dependencies = []", 'dependencies = ["packaging==24.2"]'))
        if dependency_location == "manifest" and name == "v1":
            manifest = repository / ".pre-commit-hooks.yaml"
            manifest.write_text(f"{manifest.read_text()}  additional_dependencies: [packaging==24.2]\n")
        subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
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
