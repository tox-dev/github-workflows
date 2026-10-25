from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import _condition, _step_value, run


def test_run_reports_failed_command(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="false failed with exit code 1"):
        run(tmp_path, "false")


@pytest.mark.parametrize(
    ("helper", "value", "message"),
    [
        pytest.param(_condition, "contains(inputs.x, 'y')", "unsupported GitHub step condition", id="condition"),
        pytest.param(_step_value, "${{ inputs.x", "unterminated GitHub expression", id="unterminated"),
        pytest.param(_step_value, "${{ github.actor }}", "unsupported GitHub step environment", id="environment"),
    ],
)
def test_harness_rejects_unsupported_workflow_syntax(helper: Callable[..., object], value: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        helper(value, {}, {}, {})
