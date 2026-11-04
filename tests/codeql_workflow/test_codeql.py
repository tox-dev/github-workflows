from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

ROOT: Final = Path(__file__).resolve().parents[2]
# BaseLoader keeps the `on` key a string and every scalar a string, as written in the file.
REUSABLE: Final[dict[str, Any]] = yaml.load((ROOT / ".github/workflows/codeql.yaml").read_text(), Loader=yaml.BaseLoader)
CALLER: Final[dict[str, Any]] = yaml.load((ROOT / ".github/workflows/codeql-self.yaml").read_text(), Loader=yaml.BaseLoader)
INPUTS: Final[dict[str, Any]] = REUSABLE["on"]["workflow_call"]["inputs"]
ANALYZE: Final[dict[str, Any]] = REUSABLE["jobs"]["analyze"]
CODEQL_SHA: Final = "9b3254085494b55a0f7c4c2b3d2d52cc712ce370"


def _step(name: str) -> dict[str, Any]:
    return next(step for step in ANALYZE["steps"] if step["name"] == name)


@pytest.mark.parametrize(
    ("name", "default"),
    [
        pytest.param("languages", '["actions","python"]', id="languages"),
        pytest.param("paths-ignore", "[]", id="paths-ignore"),
        pytest.param("queries", "security-extended", id="queries"),
        pytest.param("config-file", "", id="config-file"),
        pytest.param("build-mode", "none", id="build-mode"),
    ],
)
def test_input_defaults(name: str, default: str) -> None:
    assert INPUTS[name]["default"] == default


def test_each_language_gets_its_own_job() -> None:
    assert ANALYZE["name"] == "🛡️ Analyze ${{ matrix.language }}"
    assert ANALYZE["strategy"] == {"fail-fast": "false", "matrix": {"language": "${{ fromJSON(inputs.languages) }}"}}


def test_analysis_needs_security_events_write_from_caller() -> None:
    assert ANALYZE["permissions"] == {"contents": "read", "security-events": "write"}
    assert REUSABLE["permissions"] == {}


def test_init_receives_each_input() -> None:
    init = _step("🛡️ Initialize CodeQL")
    assert init["uses"] == f"github/codeql-action/init@{CODEQL_SHA}"
    assert init["with"]["languages"] == "${{ matrix.language }}"
    assert init["with"]["build-mode"] == "${{ inputs.build-mode }}"
    assert init["with"]["queries"] == "${{ inputs.queries }}"
    assert init["with"]["config-file"] == "${{ inputs.config-file }}"


def test_paths_ignore_becomes_config_only_without_config_file() -> None:
    config = _step("🛡️ Initialize CodeQL")["with"]["config"]
    assert config == "${{ inputs.config-file == '' && format('paths-ignore: {0}', inputs.paths-ignore) || '' }}"


@pytest.mark.parametrize(
    ("paths_ignore", "expected"),
    [
        pytest.param("[]", [], id="none"),
        pytest.param('["tests"]', ["tests"], id="tests"),
        pytest.param('["tests","docs/conf.py"]', ["tests", "docs/conf.py"], id="several"),
    ],
)
def test_paths_ignore_input_is_valid_codeql_yaml(paths_ignore: str, expected: list[str]) -> None:
    assert json.loads(paths_ignore) == expected
    assert yaml.safe_load(f"paths-ignore: {paths_ignore}") == {"paths-ignore": expected}


def test_analyze_uses_the_same_pinned_release() -> None:
    assert _step("🛡️ Analyze")["uses"] == f"github/codeql-action/analyze@{CODEQL_SHA}"
    assert _step("🛡️ Analyze")["with"] == {"category": "/language:${{ matrix.language }}"}


def test_gw_caller_keeps_its_triggers() -> None:
    assert list(CALLER["on"]) == ["push", "pull_request", "schedule", "workflow_dispatch"]
    assert CALLER["on"]["schedule"] == [{"cron": "0 9 * * 2"}]


def test_gw_caller_passes_its_scope_to_the_reusable_workflow() -> None:
    job = CALLER["jobs"]["analyze"]
    assert job == {
        "name": "🛡️ Analyze",
        "uses": "$/.github/workflows/codeql.yaml",
        "permissions": {"contents": "read", "security-events": "write"},
        "with": {"languages": '["actions","python"]', "paths-ignore": '["tests"]'},
    }
