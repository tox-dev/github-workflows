from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


@pytest.fixture
def cutoff_project(tmp_path: Path) -> Path:
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[project]\nname = "example"\nversion = "0.1"\n'
        '[tool.nab]\nuploaded-prior-to = "P7D"\n'
        '[tool.nab.packages.old]\nuploaded-prior-to = "2026-01-01T00:00:00Z"\n'
        '[tool.nab.packages.new]\nuploaded-prior-to = "2999-01-01T00:00:00Z"\n'
        '[[tool.nab.package-rules]]\nmatch = ["old-rule"]\nuploaded-prior-to = "2026-01-01T00:00:00Z"\n'
        '[[tool.nab.package-rules]]\nmatch = ["new-rule"]\nuploaded-prior-to = "2999-01-01T00:00:00Z"\n',
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "pyproject.toml"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Release test", "-c", "user.email=release@example.org", "commit", "-m", "Add policy"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return project


def test_expire_cutoffs_removes_only_expired_rules(cutoff_project: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "tools"
    result = subprocess.run(
        [sys.executable, str(source / "expire_cutoffs.py"), str(cutoff_project)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    nab = tomllib.loads(cutoff_project.read_text())["tool"]["nab"]
    assert set(nab["packages"]) == {"new"}
    assert [rule["match"] for rule in nab["package-rules"]] == [["new-rule"]]


def test_expire_cutoffs_removes_empty_package_table(cutoff_project: Path) -> None:
    cutoff_project.write_text(
        cutoff_project.read_text().replace('[tool.nab.packages.new]\nuploaded-prior-to = "2999-01-01T00:00:00Z"\n', "")
    )
    source = Path(__file__).resolve().parents[2] / "tools"
    result = subprocess.run(
        [sys.executable, str(source / "expire_cutoffs.py"), str(cutoff_project)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "packages" not in tomllib.loads(cutoff_project.read_text())["tool"]["nab"]


def test_expire_cutoffs_accepts_toml_datetime(cutoff_project: Path) -> None:
    cutoff_project.write_text(cutoff_project.read_text().replace('"2026-01-01T00:00:00Z"', "2026-01-01T00:00:00Z"))
    source = Path(__file__).resolve().parents[2] / "tools"
    result = subprocess.run(
        [sys.executable, str(source / "expire_cutoffs.py"), str(cutoff_project)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "old" not in tomllib.loads(cutoff_project.read_text())["tool"]["nab"]["packages"]


def test_verify_cutoff_patch_accepts_expired_only(cutoff_project: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "tools"
    subprocess.run([sys.executable, str(source / "expire_cutoffs.py"), str(cutoff_project)], check=True)
    result = subprocess.run(
        [sys.executable, str(source / "verify_cutoff_patch.py")],
        cwd=cutoff_project.parent,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_verify_cutoff_patch_accepts_subset_expired(cutoff_project: Path) -> None:
    cutoff_project.write_text(
        cutoff_project.read_text().replace('[tool.nab.packages.old]\nuploaded-prior-to = "2026-01-01T00:00:00Z"\n', "")
    )
    source = Path(__file__).resolve().parents[2] / "tools"
    result = subprocess.run(
        [sys.executable, str(source / "verify_cutoff_patch.py")],
        cwd=cutoff_project.parent,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_verify_cutoff_patch_rejects_other_metadata(cutoff_project: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "tools"
    subprocess.run([sys.executable, str(source / "expire_cutoffs.py"), str(cutoff_project)], check=True)
    cutoff_project.write_text(cutoff_project.read_text().replace('name = "example"', 'name = "intruder"'))
    result = subprocess.run(
        [sys.executable, str(source / "verify_cutoff_patch.py")],
        cwd=cutoff_project.parent,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "changes beyond expired Nab cutoffs" in result.stderr


def test_verify_cutoff_patch_rejects_early_floor_removal(cutoff_project: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "tools"
    text = cutoff_project.read_text()
    cutoff_project.write_text(text.replace('[tool.nab.packages.new]\nuploaded-prior-to = "2999-01-01T00:00:00Z"\n', ""))
    result = subprocess.run(
        [sys.executable, str(source / "verify_cutoff_patch.py")],
        cwd=cutoff_project.parent,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "changes beyond expired Nab cutoffs" in result.stderr


def test_check_nab_lock_rejects_package_change(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "tools/check_nab_lock.py"
    committed = tmp_path / "committed.toml"
    generated = tmp_path / "generated.toml"
    committed.write_text('packages = ["safe"]\n[tool.nab]\ncommand-line = ["--upgrade"]\n')
    generated.write_text('packages = ["changed"]\n[tool.nab]\ncommand-line = []\n')
    result = subprocess.run(
        [sys.executable, str(source), str(committed), str(generated)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "regenerated Nab lock differs" in result.stderr


@pytest.mark.parametrize(
    ("package", "timestamp", "accepted"),
    [
        pytest.param("nab", "2026-10-19T00:00:00Z", True, id="reviewed-nab"),
        pytest.param("nab", "2026-10-20T00:00:00Z", False, id="extended-nab"),
        pytest.param("unreviewed", "2026-10-22T00:00:00Z", False, id="new-package"),
    ],
)
def test_recent_cutoff_requires_review(package: str, timestamp: str, accepted: bool) -> None:
    project = (
        f'[tool.nab]\nuploaded-prior-to = "P7D"\n[tool.nab.packages.{package}]\nuploaded-prior-to = "{timestamp}"\n'
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from datetime import UTC, datetime; from nab_cutoffs import validate_recent_cutoffs; "
                "import sys; validate_recent_cutoffs(sys.stdin.read(), datetime(2026, 10, 16, tzinfo=UTC))"
            ),
        ],
        cwd=Path(__file__).resolve().parents[2] / "tools",
        input=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == accepted
    if not accepted:
        assert "unreviewed recent Nab cutoff" in result.stderr
