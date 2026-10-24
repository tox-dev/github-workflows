from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from conftest import action


def test_verify_secondary_lock_accepts_cooled_selection(tmp_path: Path, action_scripts: Path) -> None:
    lock = tmp_path / "pylock.zipapp.toml"
    lock.write_text(
        'lock-version = "1.0"\nrequires-python = ">=3.15"\n'
        'dependency-groups = ["project-runtime"]\ncreated-by = "test"\npackages = []\n'
        "[tool.nab]\ncreated-at = 2026-10-19T00:00:00Z\n"
    )

    result = action(
        Path(__file__).resolve().parents[2],
        tmp_path,
        action_scripts,
        "install-locked-tools",
        version="",
        LOCK_SOURCE="shared",
        VERIFY_LOCK=str(lock),
        VERIFY_GROUPS="project-runtime",
    )

    assert result.returncode == 0, result.stderr


def test_verify_secondary_lock_rejects_direct_source(tmp_path: Path, action_scripts: Path) -> None:
    lock = tmp_path / "pylock.zipapp.toml"
    lock.write_text(
        dedent(
            """\
            lock-version = "1.0"
            requires-python = ">=3.15"
            dependency-groups = ["project-runtime"]
            created-by = "test"
            [tool.nab]
            created-at = 2026-10-19T00:00:00Z
            [[packages]]
            name = "six"
            version = "1.16.0"
            marker = '"project-runtime" in dependency_groups'
            archive = { url = "https://evil.invalid/six.whl", hashes = { sha256 = "0000000000000000000000000000000000000000000000000000000000000000" } }
            """
        )
    )

    result = action(
        Path(__file__).resolve().parents[2],
        tmp_path,
        action_scripts,
        "install-locked-tools",
        version="",
        LOCK_SOURCE="shared",
        VERIFY_LOCK=str(lock),
        VERIFY_GROUPS="project-runtime",
    )

    assert result.returncode != 0
    assert "direct-source package: six" in result.stderr


def test_verify_secondary_lock_requires_group(tmp_path: Path, action_scripts: Path) -> None:
    result = action(
        Path(__file__).resolve().parents[2],
        tmp_path,
        action_scripts,
        "install-locked-tools",
        version="",
        LOCK_SOURCE="shared",
        VERIFY_LOCK="pylock.zipapp.toml",
    )

    assert result.returncode != 0
    assert "verify-lock and verify-groups must be set together" in result.stderr
