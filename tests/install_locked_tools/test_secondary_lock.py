from __future__ import annotations

from pathlib import Path

from conftest import action


def test_verify_secondary_lock_accepts_cooled_selection(tmp_path: Path, caller: Path, action_scripts: Path) -> None:
    lock = tmp_path / "pylock.zipapp.toml"
    lock.write_text(
        'lock-version = "1.0"\nrequires-python = ">=3.15"\n'
        'dependency-groups = ["project-runtime"]\ncreated-by = "test"\npackages = []\n'
        "[tool.nab]\ncreated-at = 2026-10-19T00:00:00Z\n"
    )

    result = action(
        caller,
        tmp_path,
        action_scripts,
        "install-locked-tools",
        version="",
        VERIFY_LOCK=str(lock),
        VERIFY_GROUPS="project-runtime",
    )

    assert result.returncode == 0, result.stderr


def test_verify_secondary_lock_requires_group(tmp_path: Path, caller: Path, action_scripts: Path) -> None:
    result = action(
        caller,
        tmp_path,
        action_scripts,
        "install-locked-tools",
        version="",
        VERIFY_LOCK="pylock.zipapp.toml",
    )

    assert result.returncode != 0
    assert "verify-lock and verify-groups must be set together" in result.stderr
