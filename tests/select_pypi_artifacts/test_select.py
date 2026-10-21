from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def select(
    tmp_path: Path,
    action_scripts: Path,
    dist: Path,
    manifest: Path,
    output: Path,
    expected_count: str = "1",
    partitioned: str = "false",
) -> subprocess.CompletedProcess[str]:
    script = action_scripts / "select-pypi-artifacts-0.sh"
    return subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        env=os.environ
        | {
            "DIST": str(dist),
            "MANIFEST": str(manifest),
            "OUTPUT_DIR": str(output),
            "EXPECTED_COUNT": expected_count,
            "PARTITIONED": partitioned,
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "RUNNER_TEMP": str(tmp_path),
        },
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.fixture
def artifact(tmp_path: Path) -> tuple[Path, Path]:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "fixture-1.0-py3-none-any.whl").write_bytes(b"original artifact")
    manifest = tmp_path / "missing.txt"
    manifest.write_text("fixture-1.0-py3-none-any.whl\n")
    return dist, manifest


def test_select_copies_original_bytes(artifact: tuple[Path, Path], tmp_path: Path, action_scripts: Path) -> None:
    dist, manifest = artifact
    result = select(tmp_path, action_scripts, dist, manifest, tmp_path / "selected")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "selected/fixture-1.0-py3-none-any.whl").read_bytes() == b"original artifact"
    assert (tmp_path / "output").read_text().startswith("count=1\nmanifest=")


def test_empty_selection_uploads_nothing(artifact: tuple[Path, Path], tmp_path: Path, action_scripts: Path) -> None:
    dist, manifest = artifact
    manifest.write_text("")
    result = select(tmp_path, action_scripts, dist, manifest, tmp_path / "selected", "0")
    assert result.returncode == 0, result.stderr
    assert list((tmp_path / "selected").iterdir()) == []
    assert (tmp_path / "output").read_text().startswith("count=0\nmanifest=")


def test_partitioned_selection_copies_only_local_bytes(
    artifact: tuple[Path, Path], tmp_path: Path, action_scripts: Path
) -> None:
    dist, manifest = artifact
    manifest.write_text("fixture-1.0-py3-none-any.whl\nfixture-1.0.tar.gz\n")
    result = select(tmp_path, action_scripts, dist, manifest, tmp_path / "selected", "", "true")
    assert result.returncode == 0, result.stderr
    assert [path.name for path in (tmp_path / "selected").iterdir()] == ["fixture-1.0-py3-none-any.whl"]
    selected_manifest = Path((tmp_path / "output").read_text().split("manifest=", 1)[1].strip())
    assert selected_manifest.read_text() == "fixture-1.0-py3-none-any.whl\n"


@pytest.mark.parametrize(
    "name", ["../secret", "other.whl", "fixture-1.0-py3-none-any.whl\nfixture-1.0-py3-none-any.whl"]
)
def test_select_rejects_untrusted_manifest(
    artifact: tuple[Path, Path], tmp_path: Path, action_scripts: Path, name: str
) -> None:
    dist, manifest = artifact
    manifest.write_text(f"{name}\n")
    result = select(tmp_path, action_scripts, dist, manifest, tmp_path / "selected")
    assert result.returncode != 0


def test_select_rejects_overlap(artifact: tuple[Path, Path], tmp_path: Path, action_scripts: Path) -> None:
    dist, manifest = artifact
    result = select(tmp_path, action_scripts, dist, manifest, dist / "selected")
    assert result.returncode != 0
    assert "overlaps" in result.stderr


def test_select_rejects_count_mismatch(artifact: tuple[Path, Path], tmp_path: Path, action_scripts: Path) -> None:
    dist, manifest = artifact
    result = select(tmp_path, action_scripts, dist, manifest, tmp_path / "selected", "2")
    assert result.returncode != 0


def test_select_rejects_symlink(artifact: tuple[Path, Path], tmp_path: Path, action_scripts: Path) -> None:
    dist, manifest = artifact
    (dist / "fixture-1.0-py3-none-any.whl").unlink()
    (dist / "fixture-1.0-py3-none-any.whl").symlink_to(tmp_path / "outside")
    result = select(tmp_path, action_scripts, dist, manifest, tmp_path / "selected")
    assert result.returncode != 0
