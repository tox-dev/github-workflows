import json
from pathlib import Path

import pytest
from conftest import WORKFLOWS, JsonObject, action, at, load_yaml, mapping, step, steps, text


@pytest.fixture(scope="module")
def workflow() -> JsonObject:
    return load_yaml(WORKFLOWS / "build-maturin-wheels.yaml")


def test_inputs_have_documented_defaults(workflow: JsonObject) -> None:
    inputs = mapping(at(workflow, "on", "workflow_call", "inputs"))

    assert at(inputs, "package-path", "default") == "."
    assert at(inputs, "sdist", "default") == "true"
    assert at(inputs, "release-build", "default") == "false"
    assert at(inputs, "pre-build-command", "default") == ""
    assert at(inputs, "post-build-command", "default") == ""
    assert at(inputs, "matrix", "required") == "true"
    assert at(inputs, "package-name", "required") == "true"


def test_matrix_comes_from_the_json_input(workflow: JsonObject) -> None:
    assert at(workflow, "jobs", "build", "strategy", "matrix") == {"include": "${{ fromJSON(inputs.matrix) }}"}
    assert at(workflow, "jobs", "build", "runs-on") == "${{ matrix.os }}"


def test_artifact_names_match_the_callers_names(workflow: JsonObject) -> None:
    uploads = {
        text(item["name"]): text(at(item, "with", "name"))
        for job in ("build", "sdist")
        for item in steps(workflow, job)
        if text(item.get("uses", "")).startswith("actions/upload-artifact@")
    }

    assert uploads == {
        "📤 Upload wheels": "${{ inputs.package-name }}-wheels-${{ matrix.artifact }}",
        "📤 Upload sdist": "${{ inputs.package-name }}-wheels-sdist",
    }


def test_sccache_is_off_for_releases_and_windows(workflow: JsonObject) -> None:
    assert at(workflow, "jobs", "source", "outputs", "release") == (
        "${{ inputs.release-build || startsWith(github.ref, 'refs/tags/') }}"
    )
    assert at(step(workflow, "build", "🏗️ Build wheels"), "with", "sccache") == (
        "${{ needs.source.outputs.release != 'true' && !startsWith(matrix.os, 'windows') }}"
    )


def test_interpreter_is_passed_only_for_entries_that_name_one(workflow: JsonObject) -> None:
    args = text(at(step(workflow, "build", "🏗️ Build wheels"), "with", "args"))

    assert "${{ matrix.python && format('--interpreter {0}', matrix.python) || '' }}" in args
    assert "'3.15'" not in args


def test_post_build_command_runs_after_maturin_and_before_upload(workflow: JsonObject) -> None:
    names = [item["name"] for item in steps(workflow, "build")]

    assert names.index("🏗️ Build wheels") < names.index("🏗️ Run post-build command") < names.index("📤 Upload wheels")


def test_pre_build_command_runs_once_in_the_source_job(workflow: JsonObject) -> None:
    names = [item["name"] for item in steps(workflow, "source")]

    assert "🏷️ Run pre-build command" in names
    assert names.index("🏷️ Run pre-build command") < names.index("📤 Upload source")
    assert "🏷️ Run pre-build command" not in [item["name"] for item in steps(workflow, "build")]


@pytest.mark.parametrize(
    ("job", "first_use"),
    [
        pytest.param("build", "🏗️ Build wheels", id="wheels"),
        pytest.param("sdist", "📦 Export locked build constraints", id="sdist"),
    ],
)
def test_source_download_overlaps_uv_setup_and_is_joined_before_use(
    workflow: JsonObject, job: str, first_use: str
) -> None:
    names = [item["name"] for item in steps(workflow, job)]

    assert step(workflow, job, "📩 Download source")["background"] == "true"
    assert names.index("📩 Download source") < names.index("🐍 Install uv and Python")
    assert names.index("🐍 Install uv and Python") < names.index("⏳ Wait for source") < names.index(first_use)
    assert step(workflow, job, "⏳ Wait for source")["wait"] == "download"


def test_no_job_requests_a_write_token(workflow: JsonObject) -> None:
    for name, job in mapping(workflow["jobs"]).items():
        assert mapping(job).get("permissions", {}) in ({}, {"contents": "read"}), name
    assert at(workflow, "permissions") == {}


def test_every_checkout_keeps_credentials_out_of_the_job(workflow: JsonObject) -> None:
    checkouts = [
        item
        for job in mapping(workflow["jobs"])
        for item in steps(workflow, job)
        if text(item.get("uses", "")).startswith("actions/checkout@")
    ]

    assert checkouts
    assert all(at(item, "with", "persist-credentials") == "false" for item in checkouts)


def test_gate_delegates_to_required_checks(workflow: JsonObject) -> None:
    assert at(workflow, "jobs", "gate") == {
        "name": "🚦 Build distributions pass",
        "if": "${{ !cancelled() }}",
        "needs": ["source", "build", "sdist"],
        "runs-on": "ubuntu-26.04",
        "permissions": {},
        "steps": [
            {
                "name": "🚦 Require all needed jobs to pass",
                "uses": "$/required-checks",
                "with": {"needs": "${{ toJSON(needs) }}", "allow-skipped": "sdist"},
            }
        ],
    }


@pytest.mark.parametrize(
    ("results", "accepted"),
    [
        pytest.param({"source": "success", "build": "success", "sdist": "success"}, True, id="all-succeeded"),
        pytest.param({"source": "success", "build": "success", "sdist": "skipped"}, True, id="sdist-skipped"),
        pytest.param({"source": "success", "build": "success", "sdist": "failure"}, False, id="sdist-failed"),
        pytest.param({"source": "success", "build": "failure", "sdist": "success"}, False, id="build-failed"),
        pytest.param({"source": "success", "build": "cancelled", "sdist": "success"}, False, id="build-cancelled"),
        pytest.param({"source": "success", "build": "skipped", "sdist": "success"}, False, id="build-skipped"),
    ],
)
def test_gate_requires_build_jobs_to_succeed(
    tmp_path: Path,
    action_scripts: Path,
    results: dict[str, str],
    accepted: bool,
) -> None:
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "required-checks",
        version="",
        NEEDS=json.dumps({name: {"result": outcome} for name, outcome in results.items()}),
        ALLOW_SKIPPED="sdist",
    )
    assert (result.returncode == 0) is accepted, result.stderr
