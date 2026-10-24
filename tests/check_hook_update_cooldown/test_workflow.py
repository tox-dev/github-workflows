from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml


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
            if event_name == "push" and name == "hook-cooldown"
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


def test_required_gate_does_not_repeat_changelog_lock_check() -> None:
    root = Path(__file__).resolve().parents[2]
    check = yaml.load((root / ".github/workflows/check.yaml").read_text(), Loader=yaml.BaseLoader)
    news = yaml.load((root / ".github/workflows/news.yaml").read_text(), Loader=yaml.BaseLoader)

    assert "release-tools-preview" not in check["jobs"]
    assert check["jobs"]["gate"]["needs"] == ["check", "shell", "test", "type", "hook-cooldown"]
    assert news["jobs"]["changelog"]["steps"][-1]["uses"] == "$/validate-news"


@pytest.mark.parametrize(
    ("workflow_name", "job_name"),
    [
        pytest.param("prepare-towncrier-release", "assemble", id="prepare"),
        pytest.param("validate-python-release", "source-check", id="python-release"),
        pytest.param("release", "check", id="self-release"),
    ],
)
def test_tagged_source_checks_frozen_hooks_before_prek(workflow_name: str, job_name: str) -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.load((root / ".github/workflows" / f"{workflow_name}.yaml").read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"][job_name]["steps"]

    assert next(index for index, step in enumerate(steps) if step.get("uses") == "$/verify-frozen-hooks") < next(
        index for index, step in enumerate(steps) if "prek" in step.get("run", "")
    )


@pytest.mark.parametrize(
    ("path", "step_name"),
    [
        pytest.param(".github/workflows/check.yaml", "Check repository formatting", id="pr-format"),
        pytest.param(".github/workflows/check.yaml", "Check inline shell", id="pr-inline-shell"),
        pytest.param(".github/workflows/prepare-towncrier-release.yaml", "Install prek hooks", id="prepare-install"),
        pytest.param(".github/workflows/release.yaml", "Check tagged source", id="self-release"),
        pytest.param(".github/workflows/validate-python-release.yaml", "Run tagged source checks", id="python-release"),
        pytest.param("prepare-towncrier/action.yml", "Format changelog", id="prepare-format"),
        pytest.param("validate-release-patch/action.yml", "Run prek on release patch", id="patch-validation"),
    ],
)
def test_hook_execution_uses_install_time_cutoff(path: str, step_name: str) -> None:
    document = yaml.load((Path(__file__).resolve().parents[2] / path).read_text(), Loader=yaml.BaseLoader)
    steps = (
        document["runs"]["steps"]
        if path.endswith("action.yml")
        else [step for job in document["jobs"].values() for step in job["steps"]]
    )

    step = next(step for step in steps if step.get("name") == step_name)
    assert step["env"]["UV_EXCLUDE_NEWER"] == "7 days"
    assert step["env"]["UV_NO_CONFIG"] == "1"
    assert step["env"]["UV_NO_SOURCES"] == "1"
    unset_names = {name for line in step["run"].splitlines() if line.startswith("unset ") for name in line.split()[1:]}
    assert {
        "UV_CONFIG_FILE",
        "UV_INDEX",
        "UV_INDEX_URL",
        "UV_DEFAULT_INDEX",
        "UV_EXTRA_INDEX_URL",
        "UV_FIND_LINKS",
        "UV_EXCLUDE_NEWER_PACKAGE",
        "UV_INSECURE_HOST",
        "UV_SYSTEM_CERTS",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    } <= unset_names
