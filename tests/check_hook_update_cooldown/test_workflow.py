from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml


def test_cooldown_job_is_read_only_and_required() -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/check.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    job = workflow["jobs"]["hook-cooldown"]
    assert job["if"] == "github.event_name == 'pull_request'"
    assert job["permissions"] == {"actions": "read", "contents": "read", "pull-requests": "read"}
    assert job["steps"][0] == {"uses": "$/check-hook-update-cooldown"}
    assert "hook-cooldown" in workflow["jobs"]["gate"]["needs"]


def test_cooldown_installs_only_required_hook_tools() -> None:
    action = yaml.safe_load((Path(__file__).resolve().parents[2] / "check-hook-update-cooldown/action.yml").read_text())
    assert next(step for step in action["runs"]["steps"] if step.get("uses") == "$/install-locked-tools") == {
        "uses": "$/install-locked-tools",
        "if": "steps.identity.outputs.bot == 'true'",
        "with": {"groups": "release-hook-check", "venv": "${{ runner.temp }}/hook-tools"},
    }


@pytest.mark.parametrize(
    ("event_name", "cooldown_result", "accepted"),
    [
        pytest.param("pull_request", "success", True, id="cooled-pr"),
        pytest.param("pull_request", "skipped", False, id="skipped-pr"),
        pytest.param("pull_request", "failure", False, id="young-bot-pr"),
        pytest.param("push", "skipped", True, id="push"),
    ],
)
def test_required_gate_checks_cooldown_result(event_name: str, cooldown_result: str, accepted: bool) -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/check.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    script = workflow["jobs"]["gate"]["steps"][0]["run"]
    needs = {
        name: {
            "result": cooldown_result
            if name == "hook-cooldown"
            else "skipped"
            if event_name == "push" and name in {"changelog", "hook-cooldown", "release-tools-preview"}
            else "success"
        }
        for name in workflow["jobs"]["gate"]["needs"]
    }
    result = subprocess.run(
        ["bash", "-c", script],
        env=os.environ | {"NEEDS_JSON": json.dumps(needs), "EVENT_NAME": event_name},
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, result.stderr
