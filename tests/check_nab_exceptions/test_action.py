from __future__ import annotations

from pathlib import Path

import pytest
from conftest import action


@pytest.mark.parametrize(
    "content",
    [
        pytest.param('[tool.nab]\nmode = "universal"\n', id="no-exceptions"),
        pytest.param(
            "[tool.nab]\n# expires 2999-01-01\n[tool.nab.packages.sphinx]\nuploaded-prior-to = 2026-10-21\n",
            id="dated",
        ),
    ],
)
def test_check_nab_exceptions_action_accepts_dated_exceptions(
    tmp_path: Path, action_scripts: Path, content: str
) -> None:
    (tmp_path / "pyproject.toml").write_text(content)

    result = action(tmp_path, tmp_path / "runner", action_scripts, "check-nab-exceptions", version="")

    assert (result.returncode, result.stderr) == (0, "")


def test_check_nab_exceptions_action_names_undated_package(tmp_path: Path, action_scripts: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.nab.packages.sphinx]\nuploaded-prior-to = 2026-10-21\n")

    result = action(tmp_path, tmp_path / "runner", action_scripts, "check-nab-exceptions", version="")

    assert (result.returncode, result.stderr) == (
        1,
        (
            "::error::pyproject.toml: packages.sphinx uploaded-prior-to exception needs a "
            "'# expires YYYY-MM-DD' comment directly above it\n"
        ),
    )


def test_check_nab_exceptions_action_names_expired_package(tmp_path: Path, action_scripts: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "# expires 2000-01-01\n[tool.nab.packages.sphinx]\nuploaded-prior-to = 2026-10-21\n"
    )

    result = action(tmp_path, tmp_path / "runner", action_scripts, "check-nab-exceptions", version="")

    assert (result.returncode, result.stderr) == (
        1,
        (
            "::error::pyproject.toml: packages.sphinx uploaded-prior-to exception expired on 2000-01-01; "
            "remove it or extend its expiry\n"
        ),
    )
