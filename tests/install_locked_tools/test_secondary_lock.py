from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
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


@pytest.mark.parametrize(
    ("action_name", "group"),
    [
        pytest.param("install-locked-tools", "project-runtime", id="zipapp-runtime"),
        pytest.param("export-build-constraints", "pgo", id="profile-build"),
    ],
)
def test_verify_secondary_lock_rejects_direct_source(
    tmp_path: Path, action_scripts: Path, action_name: str, group: str
) -> None:
    lock = tmp_path / "pylock.zipapp.toml"
    lock.write_text(
        dedent(
            f"""\
            lock-version = "1.0"
            requires-python = ">=3.15"
            dependency-groups = ["build", "{group}"]
            created-by = "test"
            [tool.nab]
            created-at = 2026-10-19T00:00:00Z
            [[packages]]
            name = "six"
            version = "1.16.0"
            marker = '"{group}" in dependency_groups'
            archive = {{ url = "https://evil.invalid/six.whl", hashes = {{ sha256 = "0000000000000000000000000000000000000000000000000000000000000000" }} }}
            """
        )
    )

    result = action(
        Path(__file__).resolve().parents[2],
        tmp_path,
        action_scripts,
        action_name,
        version="",
        VERIFY_GROUPS=group,
        **({"LOCK_SOURCE": "shared", "VERIFY_LOCK": str(lock)} if group == "project-runtime" else {"LOCK": str(lock)}),
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


def test_verify_secondary_lock_rejects_forged_pypi_hash(
    tmp_path: Path, action_scripts: Path, pypi_metadata_environment: None
) -> None:
    lock = tmp_path / "pylock.zipapp.toml"
    lock.write_text(
        'lock-version = "1.0"\nrequires-python = ">=3.15"\n'
        'dependency-groups = ["project-runtime"]\ncreated-by = "test"\n'
        "[tool.nab]\ncreated-at = 2026-10-19T00:00:00Z\n"
        '[[packages]]\nname = "six"\nversion = "1.16.0"\n'
        'marker = "\'project-runtime\' in dependency_groups"\nindex = "https://pypi.org/simple/"\n'
        '[[packages.wheels]]\nname = "six-1.16.0-py2.py3-none-any.whl"\n'
        'url = "https://files.pythonhosted.org/packages/d9/5a/e7c31adbe875f2abbb91bd84cf2dc52d792b5a01506781dbcf25c91daf11/six-1.16.0-py2.py3-none-any.whl"\n'
        'upload-time = 2021-05-05T14:18:17.237677Z\nhashes.sha256 = "' + "0" * 64 + '"\n'
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
    assert "release lock differs from PyPI metadata" in result.stderr
