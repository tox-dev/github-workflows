from __future__ import annotations

from pathlib import Path

from conftest import action


def test_refresh_rejects_unknown_lock_producer(tmp_path: Path, action_scripts: Path) -> None:
    (tmp_path / "pylock.toml").write_text(
        'lock-version = "1.0"\ncreated-by = "test"\nrequires-python = ">=3.15"\npackages = []\n'
    )

    result = action(tmp_path, tmp_path, action_scripts, "refresh-release-lock", version="")

    assert result.returncode != 0
    assert "lock has no recognized producer" in result.stderr


def test_refresh_rejects_secondary_options_without_lock(tmp_path: Path, action_scripts: Path) -> None:
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "refresh-release-lock",
        version="",
        ADDITIONAL_LOCK_GROUPS="build",
    )

    assert result.returncode != 0
    assert "secondary matrix inputs require additional-lock" in result.stderr
