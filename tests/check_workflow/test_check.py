from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

ROOT: Final = Path(__file__).resolve().parents[2]
# BaseLoader keeps the `on` key a string and every scalar a string, as written in the file.
WORKFLOW: Final[dict[str, Any]] = yaml.load((ROOT / ".github/workflows/check.yaml").read_text(), Loader=yaml.BaseLoader)
INPUTS: Final[dict[str, Any]] = WORKFLOW["on"]["workflow_call"]["inputs"]
TEST: Final[dict[str, Any]] = WORKFLOW["jobs"]["test"]
GATE: Final[dict[str, Any]] = WORKFLOW["jobs"]["gate"]


def _step(name: str) -> dict[str, Any]:
    return next(step for step in TEST["steps"] if step["name"] == name)


@pytest.mark.parametrize(
    ("name", "default"),
    [
        pytest.param("os", "ubuntu-26.04", id="os"),
        pytest.param("apt-packages", "", id="apt-packages"),
        pytest.param("tox-install", "tox --with tox-uv", id="tox-install"),
        pytest.param("exclude-newer", "7 days", id="exclude-newer"),
        pytest.param("exclude-newer-package", "", id="exclude-newer-package"),
        pytest.param("pytest-addopts", "-vv --durations=20", id="pytest-addopts"),
        pytest.param("diff-against", "HEAD", id="diff-against"),
        pytest.param("coverage", "false", id="coverage"),
    ],
)
def test_input_defaults(name: str, default: str) -> None:
    assert INPUTS[name]["default"] == default


def test_include_input_is_required_json_rows() -> None:
    assert INPUTS["include"]["required"] == "true"
    assert TEST["strategy"]["matrix"] == {"include": "${{ fromJSON(inputs.include) }}"}
    assert TEST["runs-on"] == "${{ matrix.os || inputs.os }}"


def test_workflow_grants_no_token_scope_beyond_contents_read() -> None:
    assert WORKFLOW["permissions"] == {}
    assert TEST["permissions"] == {"contents": "read"}


def test_checkout_keeps_full_history_without_credentials() -> None:
    assert _step("📥 Check out repository")["with"] == {"fetch-depth": "0", "persist-credentials": "false"}


def test_every_run_block_uses_bash_on_windows_rows() -> None:
    assert all(step.get("shell") == "bash" for step in TEST["steps"] if "run" in step)


def test_tox_environment_is_built_without_running_tests() -> None:
    assert _step("📦 Set up test suite")["run"] == 'tox run -vv --notest --skip-missing-interpreters false -e "$MATRIX_ENV"'


def test_test_run_reuses_built_environment_with_inputs() -> None:
    run = _step("🧪 Run test suite")
    assert run["run"] == 'tox run --skip-pkg-install -e "$MATRIX_ENV"'
    assert run["env"]["PYTEST_ADDOPTS"] == "${{ inputs.pytest-addopts }}"
    assert run["env"]["DIFF_AGAINST"] == "${{ inputs.diff-against }}"


def test_python_is_installed_only_for_rows_that_name_one() -> None:
    step = _step("🐍 Install Python")
    assert step["if"] == "${{ matrix.python }}"
    assert step["env"] == {"PYTHON": "${{ matrix.python }}"}


def test_apt_packages_install_on_linux_only() -> None:
    step = _step("📦 Install apt packages")
    assert step["if"] == "${{ inputs.apt-packages != '' && runner.os == 'Linux' }}"
    assert step["env"] == {"APT_PACKAGES": "${{ inputs.apt-packages }}"}


def test_coverage_upload_is_opt_in_and_named_per_job() -> None:
    step = _step("📤 Upload coverage data")
    assert step["if"] == "${{ inputs.coverage }}"
    assert step["with"]["name"] == ".coverage.${{ matrix.os || inputs.os }}.${{ matrix.env }}"
    assert step["with"]["path"] == ".tox/.coverage.*"
    assert step["with"]["if-no-files-found"] == "error"


def test_gate_requires_test_through_required_checks() -> None:
    assert GATE == {
        "name": "🚦 Required checks pass",
        "if": "${{ !cancelled() }}",
        "needs": ["test"],
        "runs-on": "ubuntu-26.04",
        "permissions": {},
        "steps": [
            {
                "name": "🚦 Require all needed jobs to pass",
                "uses": "$/required-checks",
                "with": {"needs": "${{ toJSON(needs) }}"},
            }
        ],
    }


@pytest.mark.parametrize(
    ("tox_install", "package_cutoffs", "expected"),
    [
        pytest.param(
            "tox --with tox-uv",
            "",
            ["tool", "install", "--python-preference", "only-managed", "--python", "3.15"]
            + ["--exclude-newer", "7 days", "tox", "--with", "tox-uv"],
            id="default",
        ),
        pytest.param(
            "tox --with .",
            "",
            ["tool", "install", "--python-preference", "only-managed", "--python", "3.15"]
            + ["--exclude-newer", "7 days", "tox", "--with", "."],
            id="local-tox-uv",
        ),
        pytest.param(
            "tox --with tox-uv",
            "nab=2026-10-24T00:00:00Z\nrelease-creator=2026-10-30T15:13:19Z\n",
            ["tool", "install", "--python-preference", "only-managed", "--python", "3.15"]
            + [
                "--exclude-newer",
                "7 days",
                "--exclude-newer-package",
                "nab=2026-10-24T00:00:00Z",
                "--exclude-newer-package",
                "release-creator=2026-10-30T15:13:19Z",
                "tox",
                "--with",
                "tox-uv",
            ],
            id="package-cutoffs",
        ),
    ],
)
def test_tox_install_passes_cutoffs_to_uv(
    tmp_path: Path, tox_install: str, package_cutoffs: str, expected: list[str]
) -> None:
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "uv").write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" >"$UV_ARGUMENTS"\n')
    (stub / "uv").chmod(0o755)
    arguments = tmp_path / "arguments"
    result = subprocess.run(
        ["bash", "-c", _step("📦 Install tox")["run"]],
        env={
            "PATH": f"{stub}{os.pathsep}{os.environ['PATH']}",
            "UV_ARGUMENTS": str(arguments),
            "TOX_INSTALL": tox_install,
            "EXCLUDE_NEWER": "7 days",
            "EXCLUDE_NEWER_PACKAGE": package_cutoffs,
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert arguments.read_text().splitlines() == expected
