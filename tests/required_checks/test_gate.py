from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from conftest import action

ROOT = Path(__file__).resolve().parents[2]


def _needs(results: dict[str, str]) -> str:
    return json.dumps({name: {"result": result} for name, result in results.items()})


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
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yaml").read_text())
    gate = workflow["jobs"]["gate"]
    assert gate["needs"] == ["check", "shell", "test", "type"]
    assert gate["if"] == "${{ !cancelled() }}"
    assert gate["steps"][-1]["uses"] == "$/required-checks"
    assert gate["steps"][-1]["with"] == {"needs": "${{ toJSON(needs) }}"}


def test_ci_does_not_repeat_changelog_lock_check() -> None:
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yaml").read_text())
    news = yaml.safe_load((ROOT / ".github/workflows/news.yaml").read_text())

    assert "release-tools-preview" not in ci["jobs"]
    assert news["jobs"]["changelog"]["steps"][-1]["uses"] == "$/validate-news"
