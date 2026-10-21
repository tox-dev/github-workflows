from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import run
from pytest_httpserver import HTTPServer


def test_validator_group_reaches_distribution_check() -> None:
    root = Path(__file__).resolve().parents[2]
    rehearsal = yaml.load((root / ".github/workflows/validate-python-release.yaml").read_text(), Loader=yaml.BaseLoader)
    dispatcher = yaml.load((root / ".github/workflows/check.yaml").read_text(), Loader=yaml.BaseLoader)
    validator = next(
        step for step in rehearsal["jobs"]["validate"]["steps"] if step.get("uses") == "$/validate-python-distribution"
    )
    assert dispatcher["on"]["workflow_dispatch"]["inputs"]["validation-group"]["default"] == "pkg-meta"
    assert dispatcher["jobs"]["external-rehearsal"]["with"]["validation-group"] == "${{ inputs.validation-group }}"
    assert rehearsal["on"]["workflow_call"]["inputs"]["validation-group"]["default"] == "pkg-meta"
    assert validator["with"]["validation-group"] == "${{ inputs.validation-group }}"


@pytest.mark.parametrize(
    ("pr_number", "checkout_matches", "github_matches", "accepted"),
    [
        pytest.param("2", True, True, True, id="exact-head"),
        pytest.param("2", True, False, False, id="moved-pr"),
        pytest.param("2", False, True, False, id="wrong-checkout"),
        pytest.param("invalid", True, True, False, id="invalid-pr-number"),
    ],
)
def test_external_target_verifies_pr_head(
    repository: Path,
    tmp_path: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    pr_number: str,
    checkout_matches: bool,
    github_matches: bool,
    accepted: bool,
) -> None:
    server, environment = github_api
    head = run(repository, "git", "rev-parse", "HEAD").stdout.strip()
    base = run(repository, "git", "rev-list", "--max-parents=0", "HEAD").stdout.strip()
    if pr_number == "2" and checkout_matches:
        server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/2").respond_with_json(
            {"head": {"sha": head if github_matches else "1" * 40}, "base": {"sha": base}}
        )
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text()
    )
    target = next(step for step in workflow["jobs"]["validate"]["steps"] if step.get("id") == "target")
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-c", target["run"]],
        cwd=repository,
        env=os.environ
        | environment
        | {
            "RELEASE_REPOSITORY": "tox-dev/fixture",
            "PR_NUMBER": pr_number,
            "HEAD_SHA": head if checkout_matches else "0" * 40,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == accepted
    if accepted:
        assert output.read_text() == f"base={base}\n"


@pytest.mark.parametrize(
    ("fixture_issue", "issue_role", "accepted"),
    [
        pytest.param("", "issue", True, id="without-issue"),
        pytest.param("31", "issue", True, id="with-issue"),
        pytest.param("invalid", "issue", False, id="invalid-issue"),
        pytest.param("31", "pull", False, id="wrong-role"),
    ],
)
def test_fixture_creates_rst_fragments_without_directory(
    repository: Path,
    tmp_path: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    fixture_issue: str,
    issue_role: str,
    accepted: bool,
) -> None:
    base = run(repository, "git", "rev-list", "--max-parents=0", "HEAD").stdout.strip()
    changelog = repository / "docs/changelog.rst"
    changelog.parent.mkdir()
    changelog.write_text("Changelog\n=========\n", encoding="utf-8")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Add reStructuredText changelog (#2)")
    head = run(repository, "git", "rev-parse", "HEAD").stdout.strip()
    run(repository, "git", "config", "--unset", "user.name")
    run(repository, "git", "config", "--unset", "user.email")
    server, environment = github_api
    if accepted:
        server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/2").respond_with_json(
            {"user": {"login": "maintainer", "type": "User"}}
        )
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text()
    )
    output = tmp_path / "output"
    result = None
    for name in (
        "Squash the target pull request",
        "Select validation fragment format",
        "Add validation fragments",
        "Commit the local release candidate",
        "Create the local release remote",
        "Record release candidate identity",
    ):
        step = next(item for item in workflow["jobs"]["validate"]["steps"] if item.get("name") == name)
        result = subprocess.run(
            ["bash", "-c", step["run"]],
            cwd=repository,
            env=os.environ
            | environment
            | {
                "BASE_SHA": base,
                "HEAD_SHA": head,
                "PR_NUMBER": "2",
                "FRAGMENTS": "docs/changelog",
                "CHANGELOG": "docs/changelog.rst",
                "FIXTURE_ISSUE": fixture_issue,
                "ISSUE_ROLE": issue_role,
                "EXTENSION": "rst",
                "GITHUB_SHA": head,
                "GITHUB_REPOSITORY": "tox-dev/fixture",
                "RELEASE_REPOSITORY": "tox-dev/fixture",
                "GITHUB_OUTPUT": str(output),
                "RUNNER_TEMP": str(tmp_path),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            break
    assert result is not None
    assert (result.returncode == 0) == accepted
    if not accepted:
        assert "fixture-issue requires an RST changelog, issue role, and numeric issue" in result.stderr
        return
    assert sorted(path.name for path in (repository / "docs/changelog").iterdir()) == [
        "+validation-2.bugfix.rst",
        "2.bugfix.rst",
    ]
    assert "extension=rst" in output.read_text()
    assert (":issue:`31`" in (repository / "docs/changelog/+validation-2.bugfix.rst").read_text()) == bool(
        fixture_issue
    )


@pytest.mark.parametrize(
    ("duplicate_issue", "accepted"),
    [
        pytest.param(False, True, id="single-pr-link"),
        pytest.param(True, False, id="duplicate-issue-link"),
    ],
)
def test_candidate_rejects_numbered_pr_as_issue(
    repository: Path, tmp_path: Path, duplicate_issue: bool, accepted: bool
) -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text()
    )
    issue = " (:issue:`2`)" if duplicate_issue else ""
    issue_link = " ([#2](https://github.com/tox-dev/fixture/issues/2))" if duplicate_issue else ""
    changelog = repository / "changelog.rst"
    changelog.write_text(f"- Verify a numbered release fix (:pr:`2`){issue}\n", encoding="utf-8")
    notes = (
        "### Bug fixes\n\n"
        "- Verify a numbered release fix ([#2](https://github.com/tox-dev/fixture/pull/2))"
        f"{issue_link}\n\n"
        "**Full Changelog**: https://github.com/tox-dev/fixture/commits/1.0.0\n"
    )
    (tmp_path / "release-notes.md").write_text(notes, encoding="utf-8")
    (tmp_path / "tag-preview-notes.md").write_text(notes, encoding="utf-8")
    (repository / "dist").mkdir()
    (repository / "dist" / "package.whl").write_bytes(b"wheel")
    result = None
    for name in (
        "Verify release note links",
        "Verify the numbered fragment",
        "Verify contributor credits",
        "Record distribution hashes",
        "Record candidate changelog",
        "Verify distribution hashes",
    ):
        step = next(item for item in workflow["jobs"]["validate"]["steps"] if item.get("name") == name)
        result = subprocess.run(
            ["bash", "-c", step["run"]],
            cwd=repository,
            env=os.environ
            | {
                "PR_NUMBER": "2",
                "PR_AUTHOR": "dependabot[bot]",
                "PR_AUTHOR_TYPE": "Bot",
                "FIXTURE_ISSUE": "",
                "CHANGELOG": "changelog.rst",
                "REPOSITORY": "tox-dev/fixture",
                "RUNNER_TEMP": str(tmp_path),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            break
    assert result is not None
    assert (result.returncode == 0) == accepted
    if not accepted:
        assert "numbered fragment links its pull request as an issue" in result.stdout
