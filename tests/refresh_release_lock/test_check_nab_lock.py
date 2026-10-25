from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import tomlkit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.check_nab_lock import main as check_nab_lock


@pytest.fixture
def nab_lock_pair(tmp_path: Path) -> tuple[Path, Path]:
    committed = tmp_path / "committed.toml"
    regenerated = tmp_path / "regenerated.toml"
    committed.write_text(
        'environments = ["python_version == 3.15"]\npackages = ["safe"]\n'
        '[tool.nab]\ncreated-at = 2026-10-01T00:00:00Z\ncommand-line = ["--upgrade"]\n'
    )
    regenerated.write_bytes(committed.read_bytes())
    return committed, regenerated


def test_check_nab_lock_restores_committed_bytes(nab_lock_pair: tuple[Path, Path]) -> None:
    committed, regenerated = nab_lock_pair
    regenerated.write_text(regenerated.read_text().replace('command-line = ["--upgrade"]', "command-line = []"))
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "tools/check_nab_lock.py"),
            str(committed),
            str(regenerated),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert regenerated.read_bytes() == committed.read_bytes()


def test_check_nab_lock_environments_only_preserves_other_changes(
    nab_lock_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    committed, regenerated = nab_lock_pair
    changed = regenerated.read_text().replace('packages = ["safe"]', 'packages = ["changed"]')
    regenerated.write_text(changed)
    monkeypatch.setattr(sys, "argv", ["check-nab-lock", str(committed), str(regenerated)])
    with pytest.raises(SystemExit) as error:
        check_nab_lock()
    assert error.value.code == 2
    monkeypatch.setattr(sys, "argv", ["check-nab-lock", "--environments-only", str(committed), str(regenerated)])
    check_nab_lock()
    assert regenerated.read_text() == changed


def test_check_nab_lock_environments_only_rejects_target_change(nab_lock_pair: tuple[Path, Path]) -> None:
    committed, regenerated = nab_lock_pair
    regenerated.write_text(regenerated.read_text().replace("python_version == 3.15", "python_version == 3.14"))
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "tools/check_nab_lock.py"),
            "--environments-only",
            str(committed),
            str(regenerated),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "changed its target environments" in result.stderr


def test_check_nab_lock_reports_invalid_encoding(nab_lock_pair: tuple[Path, Path]) -> None:
    committed, regenerated = nab_lock_pair
    committed.write_bytes(b"\xff")
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "tools/check_nab_lock.py"),
            str(committed),
            str(regenerated),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "utf-8" in result.stderr


def test_check_nab_lock_rejects_package_change(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "tools/check_nab_lock.py"
    committed = tmp_path / "committed.toml"
    generated = tmp_path / "generated.toml"
    committed.write_text(
        'packages = ["safe"]\n[tool.nab]\ncreated-at = 2026-10-01T00:00:00Z\ncommand-line = ["--upgrade"]\n'
    )
    generated.write_text('packages = ["changed"]\n[tool.nab]\ncreated-at = 2026-10-01T00:00:00Z\ncommand-line = []\n')
    result = subprocess.run(
        [sys.executable, str(source), str(committed), str(generated)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "regenerated Nab lock differs" in result.stderr


def test_check_nab_lock_rejects_future_creation(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "tools/check_nab_lock.py"
    lock = tmp_path / "pylock.toml"
    lock.write_text("[tool.nab]\ncreated-at = 2099-01-01T00:00:00Z\n")
    result = subprocess.run(
        [sys.executable, str(source), str(lock), str(lock)], text=True, capture_output=True, check=False
    )
    assert result.returncode != 0
    assert "created in the future" in result.stderr


def test_check_nab_lock_rejects_forged_upload_time(
    build_repository: Path, nab_executable: Path, tmp_path: Path
) -> None:
    source = Path(__file__).resolve().parents[2] / "tools/check_nab_lock.py"
    lock = build_repository / "pylock.toml"
    document = tomlkit.parse(lock.read_text())
    package = next(item for item in document["packages"] if item["name"] == "hatchling")
    package["wheels"][0]["upload-time"] = "2020-01-01T00:00:00Z"
    lock.write_text(tomlkit.dumps(document))
    committed = tmp_path / "committed.toml"
    committed.write_bytes(lock.read_bytes())

    regenerated = subprocess.run(
        [str(nab_executable), "lock", "--no-cache", "--groups", "release-notes", "--output", "pylock.toml"],
        cwd=build_repository,
        text=True,
        capture_output=True,
        check=False,
    )
    assert regenerated.returncode == 0, regenerated.stderr
    result = subprocess.run(
        [sys.executable, str(source), str(committed), str(lock)], text=True, capture_output=True, check=False
    )
    assert result.returncode != 0
    assert "regenerated Nab lock differs" in result.stderr
