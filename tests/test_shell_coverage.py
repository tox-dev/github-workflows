from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

import pytest
import yaml


def check_action_shell_coverage(report: Path, expected: set[str]) -> None:
    coverage = {
        Path(path).name: lines
        for path, lines in cast("dict[str, dict[str, bool]]", json.loads(report.read_text())["coverage"]).items()
        if Path(path).parent.name.startswith("action-steps")
    }
    assert set(coverage) == expected
    uncovered = {path: [line for line, covered in lines.items() if not covered] for path, lines in coverage.items()}
    assert all(coverage.values())
    assert not any(uncovered.values()), uncovered


def test_action_shell_coverage() -> None:
    if (merged := os.getenv("KCOV_MERGED")) is None:
        pytest.skip("kcov merge is available only in the runner coverage job")
    reports = list(Path(merged).rglob("codecov.json"))
    assert len(reports) == 1
    expected = {
        f"{path.parent.name}-{index}.sh"
        for path in Path().glob("*/action.yml")
        for index, _ in enumerate(yaml.safe_load(path.read_text())["runs"]["steps"])
    }
    check_action_shell_coverage(reports[0], expected)


def test_action_shell_coverage_rejects_missing_step(tmp_path: Path) -> None:
    report = tmp_path / "codecov.json"
    report.write_text(json.dumps({"coverage": {"action-steps0/first-0.sh": {"1": True}}}))
    with pytest.raises(AssertionError):
        check_action_shell_coverage(report, {"first-0.sh", "second-0.sh"})


def test_action_shell_coverage_ignores_external_files(tmp_path: Path) -> None:
    report = tmp_path / "codecov.json"
    report.write_text(
        json.dumps({"coverage": {"action-steps0/first-0.sh": {"1": True}, "installed/tool.py": {"1": False}}})
    )
    check_action_shell_coverage(report, {"first-0.sh"})
