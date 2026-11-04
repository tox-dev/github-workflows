from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/build-maturin-wheels.yaml"
PINNED = re.compile(r"^(\$/|[\w.-]+/[\w./-]+@[0-9a-f]{40})")


@pytest.fixture(scope="module")
def workflow() -> dict[Any, Any]:
    return yaml.safe_load(WORKFLOW.read_text())


def test_inputs_have_documented_defaults(workflow: dict[Any, Any]) -> None:
    inputs = workflow[True]["workflow_call"]["inputs"]

    assert inputs["package-path"]["default"] == "."
    assert inputs["sdist"]["default"] is True
    assert inputs["release-build"]["default"] is False
    assert inputs["pre-build-command"]["default"] == ""
    assert inputs["post-build-command"]["default"] == ""
    assert inputs["matrix"]["required"] is True
    assert inputs["package-name"]["required"] is True


def test_matrix_comes_from_the_json_input(workflow: dict[Any, Any]) -> None:
    assert workflow["jobs"]["build"]["strategy"]["matrix"] == {"include": "${{ fromJSON(inputs.matrix) }}"}
    assert workflow["jobs"]["build"]["runs-on"] == "${{ matrix.os }}"


def test_artifact_names_match_the_callers_names(workflow: dict[Any, Any]) -> None:
    uploads = {
        step["name"]: step["with"]["name"]
        for job in ("build", "sdist")
        for step in workflow["jobs"][job]["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    }

    assert uploads == {
        "📤 Upload wheels": "${{ inputs.package-name }}-wheels-${{ matrix.artifact }}",
        "📤 Upload sdist": "${{ inputs.package-name }}-wheels-sdist",
    }


def test_release_mode_disables_sccache_for_tags_or_input(workflow: dict[Any, Any]) -> None:
    release = workflow["jobs"]["source"]["outputs"]["release"]
    build = next(step for step in workflow["jobs"]["build"]["steps"] if step["name"] == "🏗️ Build wheels")

    assert release == "${{ inputs.release-build || startsWith(github.ref, 'refs/tags/') }}"
    assert build["with"]["sccache"] == "${{ needs.source.outputs.release != 'true' }}"


def test_post_build_command_runs_after_maturin_and_before_upload(workflow: dict[Any, Any]) -> None:
    names = [step["name"] for step in workflow["jobs"]["build"]["steps"]]

    assert names.index("🏗️ Build wheels") < names.index("🏗️ Run post-build command") < names.index("📤 Upload wheels")


def test_pre_build_command_runs_once_in_the_source_job(workflow: dict[Any, Any]) -> None:
    steps = [step["name"] for step in workflow["jobs"]["source"]["steps"]]

    assert "🏷️ Run pre-build command" in steps
    assert steps.index("🏷️ Run pre-build command") < steps.index("📤 Upload source")
    assert "🏷️ Run pre-build command" not in [step["name"] for step in workflow["jobs"]["build"]["steps"]]


def test_no_job_requests_a_write_token(workflow: dict[Any, Any]) -> None:
    for name, job in workflow["jobs"].items():
        assert job.get("permissions", {}) in ({}, {"contents": "read"}), name
    assert workflow["permissions"] == {}


def test_every_external_action_is_sha_pinned(workflow: dict[Any, Any]) -> None:
    uses = [step["uses"] for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step]

    assert uses
    assert all(PINNED.match(value) for value in uses), uses


def test_every_checkout_keeps_credentials_out_of_the_job(workflow: dict[Any, Any]) -> None:
    checkouts = [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    ]

    assert checkouts
    assert all(step["with"]["persist-credentials"] is False for step in checkouts)


def test_gate_accepts_success_and_skipped_jobs(workflow: dict[Any, Any]) -> None:
    run = workflow["jobs"]["gate"]["steps"][0]["run"]

    needs = {"source": {"result": "success"}, "build": {"result": "success"}, "sdist": {"result": "skipped"}}
    assert _gate(run, needs).returncode == 0


@pytest.mark.parametrize("result", ["failure", "cancelled"])
def test_gate_rejects_failed_or_cancelled_jobs(workflow: dict[Any, Any], result: str) -> None:
    run = workflow["jobs"]["gate"]["steps"][0]["run"]

    needs = {"source": {"result": "success"}, "build": {"result": result}, "sdist": {"result": "success"}}
    assert _gate(run, needs).returncode != 0


def _gate(run: str, needs: dict[Any, Any]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", run],
        env=os.environ | {"NEEDS_JSON": json.dumps(needs)},
        text=True,
        capture_output=True,
        check=False,
    )
