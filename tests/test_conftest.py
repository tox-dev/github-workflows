from __future__ import annotations

from pathlib import Path

import pytest
from conftest import load_yaml, mapping, run, steps, text


def test_run_reports_failed_command(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="false failed with exit code 1"):
        run(tmp_path, "false")


def test_load_yaml_rejects_a_top_level_sequence(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text("- one\n")
    with pytest.raises(TypeError, match="is not a YAML mapping"):
        load_yaml(path)


def test_mapping_rejects_a_sequence() -> None:
    with pytest.raises(TypeError, match="expected a mapping"):
        mapping(["one"])


def test_text_rejects_a_sequence() -> None:
    with pytest.raises(TypeError, match="expected text"):
        text(["one"])


def test_steps_rejects_a_job_without_a_step_list(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text("jobs:\n  build:\n    steps: none\n")
    with pytest.raises(TypeError, match="has no step list"):
        steps(load_yaml(path), "build")
