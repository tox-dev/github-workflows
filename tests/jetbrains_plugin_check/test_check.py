from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
import yaml
from conftest import workflow_step

WORKFLOW: Final[str] = "jetbrains-plugin-check.yaml"
ROOT: Final = Path(__file__).resolve().parents[2]


def _workflow() -> dict[str, Any]:
    return yaml.load((ROOT / ".github/workflows" / WORKFLOW).read_text(), Loader=yaml.BaseLoader)


def _step(job: str, name: str) -> dict[str, Any]:
    return next(step for step in _workflow()["jobs"][job]["steps"] if step.get("name") == name)


def _record_digest(directory: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return workflow_step(
        WORKFLOW,
        "build",
        "⚙️ Record unsigned ZIP digest",
        directory,
        {"GITHUB_OUTPUT": str(output)},
    )


@pytest.mark.parametrize(
    ("archives", "accepted"),
    [
        pytest.param([], False, id="no-archive"),
        pytest.param(["Plugin-1.2.3.zip"], True, id="one-archive"),
        pytest.param(["Plugin-1.2.3.zip", "Other-1.2.3.zip"], False, id="ambiguous"),
    ],
)
def test_build_records_digest_of_exactly_one_zip(tmp_path: Path, archives: list[str], accepted: bool) -> None:
    (tmp_path / "gradle.properties").write_text("pluginVersion=1.2.3\n")
    distributions = tmp_path / "build/distributions"
    distributions.mkdir(parents=True)
    for name in archives:
        (distributions / name).write_bytes(b"zip bytes")
    output = tmp_path / "output"
    result = _record_digest(tmp_path, output)
    assert (result.returncode == 0) is accepted, result.stderr
    if accepted:
        fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
        assert fields == {"name": "Plugin-1.2.3.zip", "sha256": hashlib.sha256(b"zip bytes").hexdigest()}


def test_build_ignores_archives_of_other_versions(tmp_path: Path) -> None:
    (tmp_path / "gradle.properties").write_text("pluginVersion=1.2.3\n")
    distributions = tmp_path / "build/distributions"
    distributions.mkdir(parents=True)
    (distributions / "Plugin-1.2.2.zip").write_bytes(b"old")
    (distributions / "Plugin-1.2.3.zip").write_bytes(b"new")
    output = tmp_path / "output"
    result = _record_digest(tmp_path, output)
    assert result.returncode == 0, result.stderr
    assert "name=Plugin-1.2.3.zip" in output.read_text()


def test_plugin_version_input_overrides_committed_version(tmp_path: Path) -> None:
    (tmp_path / "gradle.properties").write_text("pluginVersion=1.2.2\nother=keep\n")
    result = workflow_step(WORKFLOW, "build", "🏷️ Set plugin version", tmp_path, {"PLUGIN_VERSION": "v1.2.3"})
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "gradle.properties").read_text() == "pluginVersion=1.2.3\nother=keep\n"


def test_plugin_version_rejects_sed_metacharacters(tmp_path: Path) -> None:
    (tmp_path / "gradle.properties").write_text("pluginVersion=1.2.2\n")
    result = workflow_step(WORKFLOW, "build", "🏷️ Set plugin version", tmp_path, {"PLUGIN_VERSION": "1&2"})
    assert result.returncode != 0


def test_verify_matrix_default_checks_python_only() -> None:
    default = _workflow()["on"]["workflow_call"]["inputs"]["verify-matrix"]["default"]
    assert json.loads(default) == [{"label": "PY", "ide": "PY", "version": ""}]


def test_ui_timeout_input_bounds_ide_start() -> None:
    assert _workflow()["on"]["workflow_call"]["inputs"]["ui-test-timeout"]["default"] == "300"
    assert _step("ui-test", "🧪 Run UI tests")["env"] == {"UI_TEST_TIMEOUT": "${{ inputs.ui-test-timeout }}"}


def test_ui_test_failure_uploads_reports() -> None:
    upload = _step("ui-test", "📤 Upload UI test artifacts")
    assert upload["if"] == "${{ failure() }}"
    assert "build/idea-sandbox/**/log/idea.log" in upload["with"]["path"]


def test_jobs_hold_read_permission_only() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {}
    for name in ("build", "verify", "ui-test"):
        assert workflow["jobs"][name]["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["gate"]["permissions"] == {}


def test_outputs_come_from_build_job() -> None:
    outputs = _workflow()["on"]["workflow_call"]["outputs"]
    assert outputs["archive-sha256"]["value"] == "${{ jobs.build.outputs.archive-sha256 }}"
    assert outputs["artifact-id"]["value"] == "${{ jobs.build.outputs.artifact-id }}"


def test_verify_step_passes_matrix_entries_through_env() -> None:
    assert _step("verify", "🔍 Run verification")["env"] == {
        "IDE": "${{ matrix.ide }}",
        "VERSION": "${{ matrix.version }}",
    }


@pytest.mark.parametrize(
    ("failed_result", "accepted"),
    [
        pytest.param(None, True, id="all-succeeded"),
        pytest.param("skipped", False, id="skipped-job"),
        pytest.param("failure", False, id="failed-job"),
    ],
)
def test_gate_requires_every_job_to_succeed(failed_result: str | None, accepted: bool, tmp_path: Path) -> None:
    names = _workflow()["jobs"]["gate"]["needs"]
    needs = {name: {"result": "success"} for name in names}
    if failed_result is not None:
        needs[names[-1]] = {"result": failed_result}
    result = workflow_step(
        WORKFLOW,
        "gate",
        "🚦 Require all needed jobs to pass",
        tmp_path,
        {"NEEDS_JSON": json.dumps(needs)},
    )
    assert (result.returncode == 0) is accepted, result.stderr


def test_run_blocks_take_no_expressions_and_mask_no_failures() -> None:
    for job in _workflow()["jobs"].values():
        for step in job.get("steps", []):
            script = step.get("run", "")
            assert "${{" not in script, step.get("name")
            assert "|| true" not in script, step.get("name")
