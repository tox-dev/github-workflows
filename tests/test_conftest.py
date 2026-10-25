from __future__ import annotations

from pathlib import Path

import pytest
from conftest import run


def test_run_reports_failed_command(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="false failed with exit code 1"):
        run(tmp_path, "false")
