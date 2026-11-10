import json
from pathlib import Path
from typing import Final

import pytest
from conftest import WORKFLOWS, JsonObject, at, load_yaml, mapping, step

REUSABLE: Final[JsonObject] = load_yaml(WORKFLOWS / "codeql.yaml")
CALLER: Final[JsonObject] = load_yaml(WORKFLOWS / "codeql-self.yaml")
INPUTS: Final[JsonObject] = mapping(at(REUSABLE, "on", "workflow_call", "inputs"))
ANALYZE: Final[JsonObject] = mapping(at(REUSABLE, "jobs", "analyze"))
CODEQL_REF: Final = "v4.39.1"


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
    assert at(INPUTS, name, "default") == default


def test_each_language_gets_its_own_job() -> None:
    assert ANALYZE["name"] == "🛡️ Analyze ${{ matrix.language }}"
    assert ANALYZE["strategy"] == {"fail-fast": "false", "matrix": {"language": "${{ fromJSON(inputs.languages) }}"}}


def test_analysis_needs_security_events_write_from_caller() -> None:
    assert ANALYZE["permissions"] == {"contents": "read", "security-events": "write"}
    assert at(REUSABLE, "permissions") == {}


def test_init_receives_each_input() -> None:
    init = step(REUSABLE, "analyze", "🛡️ Initialize CodeQL")
    assert init["uses"] == f"github/codeql-action/init@{CODEQL_REF}"
    assert at(init, "with", "languages") == "${{ matrix.language }}"
    assert at(init, "with", "build-mode") == "${{ inputs.build-mode }}"
    assert at(init, "with", "queries") == "${{ inputs.queries }}"
    assert at(init, "with", "config-file") == "${{ inputs.config-file }}"


def test_paths_ignore_becomes_config_only_without_config_file() -> None:
    assert at(step(REUSABLE, "analyze", "🛡️ Initialize CodeQL"), "with", "config") == (
        "${{ inputs.config-file == '' && format('paths-ignore: {0}', inputs.paths-ignore) || '' }}"
    )


@pytest.mark.parametrize(
    ("paths_ignore", "expected"),
    [
        pytest.param("[]", [], id="none"),
        pytest.param('["tests"]', ["tests"], id="tests"),
        pytest.param('["tests","docs/conf.py"]', ["tests", "docs/conf.py"], id="several"),
    ],
)
def test_paths_ignore_input_is_valid_codeql_yaml(tmp_path: Path, paths_ignore: str, expected: list[str]) -> None:
    assert json.loads(paths_ignore) == expected
    config = tmp_path / "codeql.yaml"
    config.write_text(f"paths-ignore: {paths_ignore}\n")
    assert load_yaml(config) == {"paths-ignore": expected}


def test_analyze_uses_the_same_pinned_release() -> None:
    analyze = step(REUSABLE, "analyze", "🛡️ Analyze")
    assert analyze["uses"] == f"github/codeql-action/analyze@{CODEQL_REF}"
    assert analyze["with"] == {"category": "/language:${{ matrix.language }}"}


def test_gw_caller_keeps_its_triggers() -> None:
    assert list(mapping(CALLER["on"])) == ["push", "pull_request", "schedule", "workflow_dispatch"]
    assert at(CALLER, "on", "schedule") == [{"cron": "0 9 * * 2"}]


def test_gw_caller_passes_its_scope_to_the_reusable_workflow() -> None:
    assert at(CALLER, "jobs", "analyze") == {
        "name": "🛡️ Analyze",
        "uses": "$/.github/workflows/codeql.yaml",
        "permissions": {"contents": "read", "security-events": "write"},
        "with": {"languages": '["actions","python"]', "paths-ignore": '["tests"]'},
    }
