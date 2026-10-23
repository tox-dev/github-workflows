from __future__ import annotations

import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.nab_cutoffs import remove_expired_cutoffs


@pytest.fixture
def cutoff_project(tmp_path: Path) -> Path:
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[project]\nname = "example"\nversion = "0.1"\n'
        '[tool.nab]\nuploaded-prior-to = "P7D"\n'
        '[tool.nab.packages.nab]\nuploaded-prior-to = "2026-01-01T00:00:00Z"\n'
        '[tool.nab.packages.old]\nuploaded-prior-to = "2026-01-01T00:00:00Z"\n'
        '[tool.nab.packages.new]\nuploaded-prior-to = "2999-01-01T00:00:00Z"\n'
        '[[tool.nab.package-rules]]\nmatch = ["nab-index"]\nuploaded-prior-to = "2026-01-01T00:00:00Z"\n'
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


def test_expire_cutoffs_preserves_older_deliberate_holds(cutoff_project: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "tools"
    result = subprocess.run(
        [sys.executable, str(source / "expire_cutoffs.py"), str(cutoff_project)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    nab = tomllib.loads(cutoff_project.read_text())["tool"]["nab"]
    assert set(nab["packages"]) == {"nab", "old", "new"}
    assert [rule["match"] for rule in nab["package-rules"]] == [["nab-index"], ["old-rule"], ["new-rule"]]


def test_expire_cutoffs_removes_empty_package_table(cutoff_project: Path) -> None:
    project = cutoff_project.read_text().replace(
        '[tool.nab.packages.nab]\nuploaded-prior-to = "2026-01-01T00:00:00Z"\n',
        '[tool.nab.packages.nab]\nuploaded-prior-to = "2026-10-18T05:45:09Z"\n',
    )
    project = project.replace('[tool.nab.packages.old]\nuploaded-prior-to = "2026-01-01T00:00:00Z"\n', "")
    project = project.replace('[tool.nab.packages.new]\nuploaded-prior-to = "2999-01-01T00:00:00Z"\n', "")

    updated = remove_expired_cutoffs(project, datetime(2026, 11, 1, tzinfo=UTC))

    assert "packages" not in tomllib.loads(updated)["tool"]["nab"]


@pytest.mark.parametrize("reviewed", ["2026-10-23T02:44:40Z", "2026-10-23T16:52:06Z"])
def test_expire_cutoffs_removes_each_reviewed_release_creator_floor(reviewed: str) -> None:
    project = (
        '[tool.nab]\nuploaded-prior-to = "P7D"\n'
        f'[tool.nab.packages.release-creator]\nuploaded-prior-to = "{reviewed}"\n'
    )

    updated = remove_expired_cutoffs(project, datetime(2026, 11, 1, tzinfo=UTC))

    assert "packages" not in tomllib.loads(updated)["tool"]["nab"]


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
    assert "nab" in tomllib.loads(cutoff_project.read_text())["tool"]["nab"]["packages"]


def test_verify_cutoff_patch_rejects_deliberate_hold_removal(cutoff_project: Path) -> None:
    cutoff_project.write_text(
        cutoff_project.read_text().replace('[tool.nab.packages.nab]\nuploaded-prior-to = "2026-01-01T00:00:00Z"\n', "")
    )
    source = Path(__file__).resolve().parents[2] / "tools"
    result = subprocess.run(
        [sys.executable, str(source / "verify_cutoff_patch.py")],
        cwd=cutoff_project.parent,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "changes beyond expired Nab cutoffs" in result.stderr


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
        pytest.param("nab", "2026-10-18T05:45:09Z", True, id="reviewed-nab"),
        pytest.param("nab", "2026-10-19T00:00:00Z", False, id="unreviewed-nab"),
        pytest.param("nab", "2026-10-20T00:00:00Z", False, id="extended-nab"),
        pytest.param("release-creator", "2026-10-23T02:44:40Z", True, id="reviewed-release-creator"),
        pytest.param("release-creator", "2026-10-23T16:52:07Z", False, id="extended-release-creator"),
        pytest.param("unreviewed", "2026-10-22T00:00:00Z", False, id="new-package"),
    ],
)
def test_recent_cutoff_requires_review(package: str, timestamp: str, accepted: bool) -> None:
    project = (
        f'[tool.nab]\nuploaded-prior-to = "P7D"\n[tool.nab.packages.{package}]\nuploaded-prior-to = "{timestamp}"\n'
    )
    result = _check_recent_cutoffs(project)
    assert (result.returncode == 0) == accepted
    if not accepted:
        assert "unreviewed recent Nab cutoff" in result.stderr


@pytest.mark.parametrize(
    ("cutoff", "message"),
    [
        pytest.param('uploaded-prior-to = "P0D"', "global Nab cutoff", id="zero-days"),
        pytest.param('uploaded-prior-to = "P6D"', "global Nab cutoff", id="six-days"),
        pytest.param("uploaded-prior-to = false", "global Nab cutoff", id="disabled"),
    ],
)
def test_recent_cutoff_rejects_weak_global_policy(cutoff: str, message: str) -> None:
    result = _check_recent_cutoffs(f"[tool.nab]\n{cutoff}\n")
    assert result.returncode != 0
    assert message in result.stderr


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        pytest.param('"P0D"', False, id="zero-days"),
        pytest.param('"P6D"', False, id="six-days"),
        pytest.param("false", False, id="disabled"),
        pytest.param('"P7D"', True, id="seven-days"),
        pytest.param('"P14D"', True, id="fourteen-days"),
    ],
)
def test_recent_cutoff_checks_package_duration(value: str, accepted: bool) -> None:
    project = f'[tool.nab]\nuploaded-prior-to = "P7D"\n[tool.nab.packages.example]\nuploaded-prior-to = {value}\n'
    result = _check_recent_cutoffs(project)
    assert (result.returncode == 0) is accepted
    if not accepted:
        assert "weakens the seven-day policy" in result.stderr


@pytest.mark.parametrize("package", ["nab", "release-creator", "uv-build"], ids=["nab", "creator", "uv-build"])
@pytest.mark.parametrize("value", ['"P0D"', "false"], ids=["zero-days", "disabled"])
def test_reviewed_cutoff_rejects_unbounded_override(package: str, value: str) -> None:
    project = f'[tool.nab]\nuploaded-prior-to = "P7D"\n[tool.nab.packages.{package}]\nuploaded-prior-to = {value}\n'
    result = _check_recent_cutoffs(project)
    assert result.returncode != 0
    assert "weakens the seven-day policy" in result.stderr


def test_recent_cutoff_rejects_index_override() -> None:
    result = _check_recent_cutoffs(
        '[tool.nab]\nuploaded-prior-to = "P7D"\n'
        '[[tool.nab.indexes]]\nname = "pypi"\nurl = "https://pypi.org/simple/"\n'
        "[tool.nab.index.pypi]\nuploaded-prior-to = false\n"
    )
    assert result.returncode != 0
    assert "Nab index cutoff for pypi" in result.stderr


def test_recent_cutoff_rejects_project_nab_toml(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.nab]\nuploaded-prior-to = "P7D"\n')
    (tmp_path / "nab.toml").write_text("[packages.example]\nuploaded-prior-to = false\n")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "tools/check_recent_cutoffs.py"), "pyproject.toml"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "project nab.toml can override" in result.stderr


def test_verify_cutoff_patch_reports_invalid_boolean(cutoff_project: Path) -> None:
    cutoff_project.write_text(cutoff_project.read_text().replace('"2026-01-01T00:00:00Z"', "true", 1))
    subprocess.run(["git", "add", "pyproject.toml"], cwd=cutoff_project.parent, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Release test", "-c", "user.email=release@example.org", "commit", "-m", "Invalid"],
        cwd=cutoff_project.parent,
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "tools/verify_cutoff_patch.py")],
        cwd=cutoff_project.parent,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "invalid Nab cutoff: True" in result.stderr


def test_expire_cutoffs_preserves_disabled_package(cutoff_project: Path) -> None:
    cutoff_project.write_text(cutoff_project.read_text().replace('"2999-01-01T00:00:00Z"', "false"))
    source = Path(__file__).resolve().parents[2] / "tools"
    result = subprocess.run(
        [sys.executable, str(source / "expire_cutoffs.py"), str(cutoff_project)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert tomllib.loads(cutoff_project.read_text())["tool"]["nab"]["packages"]["new"]["uploaded-prior-to"] is False


def _check_recent_cutoffs(project: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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
