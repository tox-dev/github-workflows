from __future__ import annotations

import importlib
import runpy
import subprocess
import sys
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FunctionType
from typing import cast

import pytest
import tomlkit
from pytest_mock import MockerFixture

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.check_nab_lock import main as check_nab_lock
from tools.nab_cutoffs import (
    remove_expired_cutoffs,
    remove_expired_release_creator_cutoffs,
    validate_release_creator_cutoffs,
)


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


@pytest.mark.parametrize(
    "reviewed",
    [
        pytest.param("2026-10-23T19:54:50Z", id="0.6.5"),
        pytest.param("2026-10-23T20:48:24Z", id="0.6.6"),
        pytest.param("2026-10-23T21:40:06Z", id="0.6.7"),
        pytest.param("2026-10-24T06:07:46Z", id="1.0.0"),
        pytest.param("2026-10-24T09:08:40Z", id="1.1.0"),
    ],
)
def test_expire_cutoffs_removes_each_reviewed_release_creator_floor(reviewed: str) -> None:
    project = (
        '[tool.nab]\nuploaded-prior-to = "P7D"\n'
        f'[tool.nab.packages.release-creator]\nuploaded-prior-to = "{reviewed}"\n'
    )

    updated = remove_expired_cutoffs(project, datetime(2026, 11, 1, tzinfo=UTC))

    assert "packages" not in tomllib.loads(updated)["tool"]["nab"]


@pytest.mark.parametrize(
    ("seconds_before", "expired"),
    [
        pytest.param(1, False, id="before-threshold"),
        pytest.param(0, True, id="at-threshold"),
    ],
)
def test_expire_cutoffs_uses_reviewed_threshold(seconds_before: int, expired: bool) -> None:
    project = (
        '[tool.nab]\nuploaded-prior-to = "P7D"\n'
        '[tool.nab.packages.release-creator]\nuploaded-prior-to = "2026-10-23T19:54:50Z"\n'
    )
    threshold = datetime(2026, 10, 23, 19, 54, 50, tzinfo=UTC) - timedelta(seconds=seconds_before)
    updated = remove_expired_cutoffs(project, threshold)
    assert ("packages" not in tomllib.loads(updated)["tool"]["nab"]) is expired


def test_expire_cutoffs_accepts_toml_datetime(cutoff_project: Path) -> None:
    cutoff_project.write_text(
        cutoff_project.read_text().replace(
            '[tool.nab.packages.nab]\nuploaded-prior-to = "2026-01-01T00:00:00Z"',
            "[tool.nab.packages.nab]\nuploaded-prior-to = 2026-10-18T05:45:09Z",
        ),
    )
    updated = remove_expired_cutoffs(cutoff_project.read_text(), datetime(2026, 11, 1, tzinfo=UTC))

    assert "nab" not in tomllib.loads(updated)["tool"]["nab"]["packages"]


@pytest.mark.parametrize(
    ("cutoff", "accepted"),
    [
        pytest.param("2026-10-24T09:08:40Z", True, id="reviewed"),
        pytest.param("2026-10-24T09:08:41Z", False, id="unreviewed"),
    ],
)
def test_release_creator_cutoffs_require_review(cutoff: str, accepted: bool) -> None:
    project = f'[tool.release-creator.locks.exclude-newer-package]\nrelease-creator = "{cutoff}"\n'

    if accepted:
        validate_release_creator_cutoffs(project, datetime(2026, 10, 17, tzinfo=UTC))
    else:
        with pytest.raises(ValueError, match="unreviewed recent release-creator cutoff"):
            validate_release_creator_cutoffs(project, datetime(2026, 10, 17, tzinfo=UTC))


@pytest.mark.parametrize(
    ("project_text", "accepted"),
    [
        pytest.param("[tool.release-creator.locks]\n", True, id="release-creator-only"),
        pytest.param("[tool.other]\n", False, id="no-policy"),
    ],
)
def test_recent_cutoff_cli_checks_project_provider(tmp_path: Path, project_text: str, accepted: bool) -> None:
    project = tmp_path / "pyproject.toml"
    project.write_text(project_text)
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "tools/check_recent_cutoffs.py"), str(project)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode == 0) is accepted
    if not accepted:
        assert "project has no lock cutoff policy" in result.stderr


@pytest.mark.parametrize(
    ("locks", "error"),
    [
        pytest.param("unexpected = true", ValueError, id="unknown-setting"),
        pytest.param('exclude-newer-package = "recent"', TypeError, id="non-table"),
        pytest.param("[tool.release-creator.locks.exclude-newer-package]\nexample = false", TypeError, id="non-time"),
    ],
)
def test_release_creator_cutoffs_reject_invalid_policy(locks: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        validate_release_creator_cutoffs(f"[tool.release-creator.locks]\n{locks}\n", datetime(2026, 10, 17, tzinfo=UTC))


def test_expire_release_creator_cutoff_keeps_deliberate_hold() -> None:
    project = (
        "[tool.release-creator.locks.exclude-newer-package]\n"
        'release-creator = "2026-10-24T06:07:46Z"\n'
        'bad-package = "2026-01-01T00:00:00Z"\n'
    )

    updated = remove_expired_release_creator_cutoffs(project, datetime(2026, 11, 1, tzinfo=UTC))

    assert tomllib.loads(updated)["tool"]["release-creator"]["locks"]["exclude-newer-package"] == {
        "bad-package": "2026-01-01T00:00:00Z"
    }


def test_expire_release_creator_cutoff_removes_empty_override() -> None:
    project = '[tool.release-creator.locks.exclude-newer-package]\nrelease-creator = "2026-10-24T09:08:40Z"\n'
    updated = remove_expired_release_creator_cutoffs(project, datetime(2026, 11, 1, tzinfo=UTC))

    assert "exclude-newer-package" not in updated


def test_expire_release_creator_cutoff_keeps_unexpired_override() -> None:
    project = '[tool.release-creator.locks.exclude-newer-package]\nrelease-creator = "2026-10-24T09:08:40Z"\n'

    assert remove_expired_release_creator_cutoffs(project, datetime(2026, 10, 17, tzinfo=UTC)) == project


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


def test_verify_cutoff_patch_accepts_only_unchanged_metadata(
    cutoff_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = Path(__file__).resolve().parents[2] / "tools"
    monkeypatch.syspath_prepend(str(source))
    script = source / "verify_cutoff_patch.py"
    command = runpy.run_path(str(script), run_name="verify_cutoff_imported")
    monkeypatch.chdir(cutoff_project.parent)
    monkeypatch.setattr(sys, "argv", [str(script)])
    main = cast("Callable[[], None]", command["main"])

    main()
    cutoff_project.write_text(cutoff_project.read_text().replace('name = "example"', 'name = "intruder"'))

    with pytest.raises(SystemExit, match="2"):
        main()

    assert "changes beyond expired Nab cutoffs" in capsys.readouterr().err


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


@pytest.mark.parametrize(
    ("remove", "accepted"),
    [pytest.param("release-creator", True, id="reviewed-expired"), pytest.param("bad-package", False, id="hold")],
)
def test_verify_cutoff_patch_limits_release_creator_removal(
    cutoff_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
    remove: str,
    accepted: bool,
) -> None:
    cutoff_project.write_text(
        cutoff_project.read_text()
        + "[tool.release-creator.locks.exclude-newer-package]\n"
        + 'release-creator = "2026-10-24T06:07:46Z"\n'
        + 'bad-package = "2026-01-01T00:00:00Z"\n'
    )
    subprocess.run(["git", "add", "pyproject.toml"], cwd=cutoff_project.parent, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Release test",
            "-c",
            "user.email=release@example.org",
            "commit",
            "-m",
            "Add release policy",
        ],
        cwd=cutoff_project.parent,
        check=True,
        capture_output=True,
    )
    cutoff_project.write_text(cutoff_project.read_text().replace(f'{remove} = "', f'# {remove} = "'))
    script = Path(__file__).resolve().parents[2] / "tools/verify_cutoff_patch.py"
    monkeypatch.syspath_prepend(str(script.parent))
    main = cast("FunctionType", runpy.run_path(str(script), run_name="cutoff_patch_test")["main"])
    clock = mocker.create_autospec(datetime)
    clock.now.return_value = datetime(2026, 11, 1, tzinfo=UTC)
    main.__globals__["datetime"] = clock
    monkeypatch.chdir(cutoff_project.parent)
    monkeypatch.setattr(sys, "argv", [str(script)])

    if accepted:
        main()
    else:
        with pytest.raises(SystemExit, match="2"):
            main()
        assert "changes beyond expired package cutoffs" in capsys.readouterr().err


def test_verify_cutoff_patch_accepts_release_creator_only_policy(
    cutoff_project: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    cutoff_project.write_text(
        '[tool.release-creator.locks.exclude-newer-package]\nrelease-creator = "2026-10-24T09:08:40Z"\n'
    )
    subprocess.run(["git", "add", "pyproject.toml"], cwd=cutoff_project.parent, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Release test",
            "-c",
            "user.email=release@example.org",
            "commit",
            "-m",
            "Add release policy",
        ],
        cwd=cutoff_project.parent,
        check=True,
        capture_output=True,
    )
    cutoff_project.write_text("[tool.release-creator.locks]\n")
    script = Path(__file__).resolve().parents[2] / "tools/verify_cutoff_patch.py"
    monkeypatch.syspath_prepend(str(script.parent))
    main = cast("FunctionType", runpy.run_path(str(script), run_name="cutoff_patch_test")["main"])
    clock = mocker.create_autospec(datetime)
    clock.now.return_value = datetime(2026, 11, 1, tzinfo=UTC)
    main.__globals__["datetime"] = clock
    monkeypatch.chdir(cutoff_project.parent)
    monkeypatch.setattr(sys, "argv", [str(script)])

    main()


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


@pytest.mark.parametrize(
    ("package", "timestamp", "accepted"),
    [
        pytest.param("nab", "2026-10-18T05:45:09Z", True, id="reviewed-nab"),
        pytest.param("nab", "2026-10-19T00:00:00Z", False, id="unreviewed-nab"),
        pytest.param("nab", "2026-10-20T00:00:00Z", False, id="extended-nab"),
        pytest.param("release-creator", "2026-10-23T02:44:40Z", False, id="stale-release-creator-0.6.0"),
        pytest.param("release-creator", "2026-10-23T16:52:06Z", False, id="stale-release-creator-0.6.4"),
        pytest.param("release-creator", "2026-10-23T16:52:07Z", False, id="extended-release-creator"),
        pytest.param("release-creator", "2026-10-23T19:54:50Z", True, id="reviewed-release-creator-0.6.5"),
        pytest.param("release-creator", "2026-10-23T19:54:51Z", False, id="extended-release-creator-0.6.5"),
        pytest.param("release-creator", "2026-10-23T20:48:24Z", True, id="reviewed-release-creator-0.6.6"),
        pytest.param("release-creator", "2026-10-23T20:48:25Z", False, id="extended-release-creator-0.6.6"),
        pytest.param("release-creator", "2026-10-23T21:40:06Z", True, id="reviewed-release-creator-0.6.7"),
        pytest.param("release-creator", "2026-10-23T21:40:07Z", False, id="extended-release-creator-0.6.7"),
        pytest.param("release-creator", "2026-10-24T06:07:46Z", True, id="reviewed-release-creator-1.0.0"),
        pytest.param("release-creator", "2026-10-24T06:07:47Z", False, id="extended-release-creator-1.0.0"),
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


def test_recent_cutoff_rejects_custom_index() -> None:
    result = _check_recent_cutoffs(
        '[tool.nab]\nuploaded-prior-to = "P7D"\n'
        '[[tool.nab.indexes]]\nname = "other"\nurl = "https://example.org/simple/"\n'
    )
    assert result.returncode != 0
    assert "custom Nab indexes" in result.stderr


def test_recent_cutoff_rejects_index_settings_without_cutoff() -> None:
    result = _check_recent_cutoffs(
        '[tool.nab]\nuploaded-prior-to = "P7D"\n[tool.nab.index.pypi]\nallow-insecure-host = true\n'
    )
    assert result.returncode != 0
    assert "custom Nab indexes" in result.stderr


def test_recent_cutoff_rejects_project_nab_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.nab]\nuploaded-prior-to = "P7D"\n')
    (tmp_path / "nab.toml").write_text("[packages.example]\nuploaded-prior-to = false\n")
    source = Path(__file__).resolve().parents[2] / "tools"
    monkeypatch.syspath_prepend(str(source))
    script = source / "check_recent_cutoffs.py"
    command = runpy.run_path(str(script), run_name="recent_cutoffs_imported")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(script), "pyproject.toml"])

    with pytest.raises(SystemExit, match="2"):
        cast("Callable[[], None]", command["main"])()

    assert "project nab.toml can override" in capsys.readouterr().err


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
    assert "invalid cutoff for Nab: True" in result.stderr


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


@pytest.mark.parametrize(
    ("value", "message"),
    [
        pytest.param("true", "invalid cutoff for example", id="boolean"),
        pytest.param('"2026-01-01T00:00:00"', "has no timezone", id="naive-time"),
    ],
)
def test_recent_cutoff_rejects_invalid_package_time(value: str, message: str) -> None:
    result = _check_recent_cutoffs(
        f'[tool.nab]\nuploaded-prior-to = "P7D"\n[tool.nab.packages.example]\nuploaded-prior-to = {value}\n'
    )
    assert result.returncode != 0
    assert message in result.stderr


def test_recent_cutoff_cli_rejects_missing_project(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "tools/check_recent_cutoffs.py"),
            str(tmp_path / "missing"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "No such file" in result.stderr


def test_expire_cutoffs_removes_reviewed_rule() -> None:
    project = (
        '[tool.nab]\nuploaded-prior-to = "P7D"\n'
        '[[tool.nab.package-rules]]\nmatch = ["release-creator"]\n'
        'uploaded-prior-to = "2026-10-23T19:54:50Z"\n'
    )
    updated = remove_expired_cutoffs(project, datetime(2026, 11, 1, tzinfo=UTC))
    assert "package-rules" not in tomllib.loads(updated)["tool"]["nab"]


def test_expire_cutoffs_rejects_naive_reviewed_time() -> None:
    project = "[tool.nab]\n[tool.nab.packages.nab]\nuploaded-prior-to = 2026-10-18T05:45:09\n"
    with pytest.raises(ValueError, match="has no timezone"):
        remove_expired_cutoffs(project, datetime(2026, 11, 1, tzinfo=UTC))


def test_expire_cutoffs_keeps_disabled_reviewed_package() -> None:
    project = "[tool.nab]\n[tool.nab.packages.nab]\nuploaded-prior-to = false\n"
    assert remove_expired_cutoffs(project, datetime(2026, 11, 1, tzinfo=UTC)) == project


def test_expire_cutoffs_cli_writes_expired_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    module = importlib.import_module("expire_cutoffs")
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[tool.nab]\nuploaded-prior-to = "P7D"\n'
        '[[tool.nab.package-rules]]\nmatch = ["release-creator"]\n'
        'uploaded-prior-to = "2026-10-23T19:54:50Z"\n'
    )
    mocker.patch.object(
        module, "datetime", mocker.Mock(now=mocker.Mock(return_value=datetime(2026, 11, 1, tzinfo=UTC)))
    )
    monkeypatch.setattr(sys, "argv", ["expire_cutoffs", str(project)])

    module.main()

    assert "package-rules" not in tomllib.loads(project.read_text())["tool"]["nab"]


def test_expire_cutoffs_cli_writes_release_creator_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    module = importlib.import_module("expire_cutoffs")
    project = tmp_path / "pyproject.toml"
    project.write_text('[tool.release-creator.locks.exclude-newer-package]\nrelease-creator = "2026-10-24T09:08:40Z"\n')
    mocker.patch.object(
        module, "datetime", mocker.Mock(now=mocker.Mock(return_value=datetime(2026, 11, 1, tzinfo=UTC)))
    )
    monkeypatch.setattr(sys, "argv", ["expire_cutoffs", str(project)])

    module.main()

    assert "exclude-newer-package" not in project.read_text()


def test_expire_cutoffs_cli_rejects_missing_project(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "tools/expire_cutoffs.py"),
            str(tmp_path / "missing"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "No such file" in result.stderr


def test_expire_cutoffs_retains_other_rule_settings() -> None:
    project = (
        '[tool.nab]\nuploaded-prior-to = "P7D"\n'
        '[tool.nab.packages.nab]\nuploaded-prior-to = "2026-10-18T05:45:09Z"\nindex = "pypi"\n'
        '[[tool.nab.package-rules]]\nmatch = ["nab-index"]\n'
        'uploaded-prior-to = "2026-10-18T05:45:09Z"\npriority = 1\n'
    )

    updated = tomllib.loads(remove_expired_cutoffs(project, datetime(2026, 11, 1, tzinfo=UTC)))

    assert updated["tool"]["nab"]["packages"]["nab"] == {"index": "pypi"}
    assert updated["tool"]["nab"]["package-rules"] == [{"match": ["nab-index"], "priority": 1}]


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
