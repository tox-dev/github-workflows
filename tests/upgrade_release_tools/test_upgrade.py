from __future__ import annotations

import os
import subprocess
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from conftest import run


@pytest.fixture(scope="session")
def upgrade_scripts(action_scripts: Path) -> Path:
    return action_scripts


@pytest.fixture(scope="session")
def publish_scripts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    source = Path(__file__).resolve().parents[2]
    scripts = tmp_path_factory.mktemp("publish-steps")
    workflow = yaml.safe_load((source / ".github/workflows/upgrade-release-tools.yaml").read_text())
    for step in workflow["jobs"]["publish"]["steps"]:
        if "run" in step:
            name = step.get("id", step.get("name", "step")).replace(" ", "-").lower()
            (scripts / f"publish-{name}.sh").write_text(step["run"])
    return scripts


@pytest.fixture
def lock_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "0.1.0"\nrequires-python = ">=3.15"\n'
        "[dependency-groups]\nrelease = []\ntest = []\n"
    )
    run(repository, "git", "init", "-b", "main")
    run(repository, "git", "config", "user.name", "Release test")
    run(repository, "git", "config", "user.email", "release@example.org")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Initial files")
    return repository


def test_upgrade_exports_every_group(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    installed = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-0.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
    )
    assert installed.returncode == 0, installed.stderr
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-2.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
    )
    assert result.returncode == 0, result.stderr
    lock = tomllib.loads((lock_repository / "pylock.toml").read_text())
    assert (lock["requires-python"], lock["dependency-groups"]) == (">=3.15", ["project-runtime", "release", "test"])


def test_upgrade_sets_seven_day_cutoff(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-1.sh",
        tmp_path,
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    assert result.returncode == 0, result.stderr
    cutoff = datetime.fromisoformat((tmp_path / "output").read_text().removeprefix("timestamp=").strip())
    assert abs(datetime.now(UTC) - cutoff - timedelta(days=7)) < timedelta(minutes=1)


@pytest.mark.parametrize("changed_path", [None, "pylock.toml", "uv.lock"], ids=["unchanged", "pylock", "uv-lock"])
def test_upgrade_emits_patch_only_for_change(
    lock_repository: Path, tmp_path: Path, upgrade_scripts: Path, changed_path: str | None
) -> None:
    lock = lock_repository / "pylock.toml"
    lock.write_text('lock-version = "1.0"\n')
    (lock_repository / "uv.lock").write_text("before\n")
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add lock")
    if changed_path is not None:
        (lock_repository / changed_path).write_text("after\n")
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-6.sh",
        tmp_path,
        LOCK="pylock.toml",
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    assert result.returncode == 0
    lock_changed = changed_path == "pylock.toml"
    assert (tmp_path / "output").read_text() == f"changed={str(lock_changed).lower()}\n"
    assert (tmp_path / "lock.patch").exists() == lock_changed
    if lock_changed:
        assert f"diff --git a/{changed_path} b/{changed_path}" in (tmp_path / "lock.patch").read_text()


@pytest.mark.parametrize("unrelated", [None, "other.txt", "uv.lock"], ids=["clean", "unrelated-file", "uv-lock"])
def test_upgrade_checks_refreshed_lock(
    lock_repository: Path, tmp_path: Path, upgrade_scripts: Path, unrelated: str | None
) -> None:
    project = lock_repository / "pyproject.toml"
    project.write_text(project.read_text().replace("release = []", 'release = ["prek"]'))
    (lock_repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: check\n"
        "        name: check\n        entry: 'true'\n        language: system\n        pass_filenames: false\n"
    )
    (lock_repository / "other.txt").write_text("before\n")
    run(
        lock_repository,
        "uv",
        "pip",
        "compile",
        "--preview-features",
        "pylock",
        "--group",
        "pyproject.toml:release",
        "--python-version",
        "3.15",
        "--output-file",
        "pylock.toml",
    )
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add release tools")
    if unrelated is not None:
        (lock_repository / unrelated).write_text("after\n")
    installed = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
    )
    assert installed.returncode == 0, installed.stderr
    checked = execute(lock_repository, upgrade_scripts / "refresh-release-lock-4.sh", tmp_path)
    assert checked.returncode == 0, checked.stderr
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-5.sh",
        tmp_path,
        LOCK="pylock.toml",
    )
    assert (result.returncode == 0) == (unrelated is None), result.stderr
    assert ("prek changed file outside the lock file" in result.stderr) == (unrelated is not None)


@pytest.mark.parametrize("path", ["pylock.toml", "uv.lock", "other.txt"], ids=["pylock", "uv-lock", "unrelated-file"])
def test_upgrade_rejects_unrelated_patch(
    lock_repository: Path, tmp_path: Path, publish_scripts: Path, path: str
) -> None:
    (lock_repository / path).write_text("before\n")
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add file")
    (lock_repository / path).write_text("after\n")
    patch = run(lock_repository, "git", "diff", "--binary", "--", path).stdout
    run(lock_repository, "git", "restore", path)
    patch_dir = tmp_path / "release-tools-lock"
    patch_dir.mkdir()
    (patch_dir / "lock.patch").write_text(patch)
    applied = execute(lock_repository, publish_scripts / "publish-apply-lock-patch.sh", tmp_path)
    assert applied.returncode == 0, applied.stderr
    result = execute(
        lock_repository, publish_scripts / "publish-check-lock-patch-paths.sh", tmp_path, LOCK="pylock.toml"
    )
    assert (result.returncode == 0) == (path == "pylock.toml")
    assert ("unexpected lock path" in result.stderr) == (path != "pylock.toml")


def test_upgrade_rejects_executable_lock(lock_repository: Path, tmp_path: Path, publish_scripts: Path) -> None:
    lock = lock_repository / "pylock.toml"
    lock.write_text('lock-version = "1.0"\n')
    run(lock_repository, "git", "add", "pylock.toml")
    run(lock_repository, "git", "commit", "-m", "Add lock")
    lock.chmod(0o755)
    patch = run(lock_repository, "git", "diff", "--binary", "--", "pylock.toml").stdout
    run(lock_repository, "git", "restore", "pylock.toml")
    patch_dir = tmp_path / "release-tools-lock"
    patch_dir.mkdir()
    (patch_dir / "lock.patch").write_text(patch)
    applied = execute(lock_repository, publish_scripts / "publish-apply-lock-patch.sh", tmp_path)
    assert applied.returncode == 0, applied.stderr
    result = execute(lock_repository, publish_scripts / "publish-check-lock-patch-file-mode.sh", tmp_path)
    assert result.returncode != 0
    assert "unexpected lock file mode" in result.stderr


@pytest.mark.parametrize(
    ("branch", "base", "accepted"),
    [("automation/update-release-tools", "main", True), ("main", "main", False), ("bad branch", "main", False)],
    ids=["automation-branch", "base-branch", "invalid-ref"],
)
def test_upgrade_rejects_unsafe_branch(
    lock_repository: Path, tmp_path: Path, publish_scripts: Path, branch: str, base: str, accepted: bool
) -> None:
    result = execute(
        lock_repository,
        publish_scripts / "publish-check-dependency-branch.sh",
        tmp_path,
        BRANCH=branch,
        BASE=base,
    )
    assert (result.returncode == 0) == accepted


def execute(repository: Path, script: Path, tmp_path: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    command = ["bash", str(script)]
    if script.name.startswith("refresh-release-lock-") and (coverage_binary := os.environ.get("KCOV_BIN")) is not None:
        output = Path(os.environ["KCOV_OUTPUT"])
        output.mkdir(parents=True, exist_ok=True)
        command = [coverage_binary, f"--include-path={script.parent}", str(output / uuid4().hex), str(script)]
    return subprocess.run(
        command,
        cwd=repository,
        env=os.environ
        | {
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "refresh-release-lock"),
        }
        | environment,
        text=True,
        capture_output=True,
        check=False,
    )
