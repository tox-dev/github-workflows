import json
from pathlib import Path

import pytest
from conftest import WORKFLOWS, action, at, load_yaml, mapping, steps


@pytest.mark.parametrize(
    ("results", "allow_skipped", "accepted"),
    [
        pytest.param({"test": "success", "lint": "success"}, "", True, id="all-succeeded"),
        pytest.param({"test": "success", "lint": "failure"}, "", False, id="failed-job"),
        pytest.param({"test": "success", "lint": "cancelled"}, "", False, id="cancelled-job"),
        pytest.param({"test": "success", "lint": "skipped"}, "", False, id="skipped-job-not-allowed"),
        pytest.param({"test": "success", "lint": "skipped"}, "lint", True, id="skipped-job-allowed"),
        pytest.param({"test": "success", "lint": "success"}, "lint", True, id="allowed-job-ran"),
        pytest.param({"test": "failure", "lint": "skipped"}, "lint", False, id="allowed-skip-hides-failure"),
        pytest.param(
            {"test": "skipped", "lint": "skipped", "docs": "success"},
            "test",
            False,
            id="other-skip-not-allowed",
        ),
        pytest.param(
            {"test": "skipped", "lint": "skipped", "docs": "success"},
            "test\nlint",
            True,
            id="multi-line-allowed-skips",
        ),
    ],
)
def test_gate_requires_each_needed_job_to_succeed(
    tmp_path: Path,
    action_scripts: Path,
    results: dict[str, str],
    allow_skipped: str,
    accepted: bool,
) -> None:
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "required-checks",
        version="",
        NEEDS=_needs(results),
        ALLOW_SKIPPED=allow_skipped,
    )
    assert (result.returncode == 0) is accepted, result.stderr


def test_gate_rejects_allowed_job_missing_from_needs(tmp_path: Path, action_scripts: Path) -> None:
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "required-checks",
        version="",
        NEEDS=_needs({"test": "success"}),
        ALLOW_SKIPPED="tset",
    )
    assert result.returncode != 0
    assert "allow-skipped names a job that is not in needs: tset" in result.stderr


def test_gate_is_used_by_ci_and_needs_its_jobs() -> None:
    ci = load_yaml(WORKFLOWS / "ci.yaml")
    gate = steps(ci, "gate")[-1]

    assert at(ci, "jobs", "gate", "needs") == ["check", "shell", "test", "type", "release"]
    assert at(ci, "jobs", "gate", "if") == "${{ !cancelled() }}"
    assert gate["uses"] == "$/required-checks"
    assert gate["with"] == {"needs": "${{ toJSON(needs) }}"}


def test_ci_does_not_repeat_changelog_lock_check() -> None:
    assert "release-tools-preview" not in mapping(load_yaml(WORKFLOWS / "ci.yaml")["jobs"])


def test_news_validates_the_changelog_with_validate_news() -> None:
    assert steps(load_yaml(WORKFLOWS / "news.yaml"), "changelog")[-1]["uses"] == "$/validate-news"


def _needs(results: dict[str, str]) -> str:
    return json.dumps({name: {"result": result} for name, result in results.items()})
