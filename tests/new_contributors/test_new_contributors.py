from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parents[2] / "tools/new_contributors.py"


def test_new_contributors_lead_a_body_of_links_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    notes, generated, output = tmp_path / "notes.md", tmp_path / "generated.md", tmp_path / "body.md"
    notes.write_text("[📜 Full Changelog](https://github.com/tox-dev/fixture/commits/0.1.0)\n")
    generated.write_text("## New Contributors\n* @alice made their first contribution in https://example.org/pull/1\n")
    monkeypatch.setattr(sys, "argv", ["new_contributors.py", str(notes), str(generated), str(output)])

    runpy.run_path(str(_TOOL), run_name="__main__")

    assert output.read_text() == (
        "### New Contributors\n\n- @alice made their first contribution in https://example.org/pull/1\n\n"
        "[📜 Full Changelog](https://github.com/tox-dev/fixture/commits/0.1.0)\n"
    )
    assert capsys.readouterr().out == "New Contributors: @alice\n"


def test_new_contributors_module_imports_without_running() -> None:
    assert runpy.run_path(str(_TOOL))["__all__"] == ["main"]
