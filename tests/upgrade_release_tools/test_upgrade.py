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
    outputs = dict(line.split("=", maxsplit=1) for line in (tmp_path / "output").read_text().splitlines())
    current = datetime.fromisoformat(outputs["current"])
    cutoff = datetime.fromisoformat(outputs["timestamp"])
    assert abs(datetime.now(UTC) - current) < timedelta(minutes=1)
    assert current - cutoff == timedelta(days=7)


def test_upgrade_exempts_only_named_young_package(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    project = lock_repository / "pyproject.toml"
    project.write_text(
        project.read_text().replace("release = []", 'release = ["release-creator>=0.4.1,<0.4.2", "certifi"]')
    )
    installed = execute(lock_repository, upgrade_scripts / "refresh-release-lock-0.sh", tmp_path, PYTHON_VERSION="3.15")
    assert installed.returncode == 0, installed.stderr
    blocked = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-2.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
        UV_EXCLUDE_NEWER="2026-10-14T00:00:00Z",
        EXCLUDE_NEWER_PACKAGES="",
    )
    assert blocked.returncode != 0
    allowed = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-2.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
        UV_EXCLUDE_NEWER="2026-10-14T00:00:00Z",
        EXCEPTION_TIMESTAMP="2026-10-21T00:00:00Z",
        EXCLUDE_NEWER_PACKAGES="release-creator",
    )
    assert allowed.returncode == 0, allowed.stderr
    packages = {
        package["name"]: package for package in tomllib.loads((lock_repository / "pylock.toml").read_text())["packages"]
    }
    assert packages["release-creator"]["version"] == "0.4.1"
    assert packages["certifi"]["version"] == "2026.7.22"


def test_upgrade_rejects_invalid_exception_name(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-2.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
        EXCEPTION_TIMESTAMP="2026-10-21T00:00:00Z",
        EXCLUDE_NEWER_PACKAGES="release-creator; true",
    )
    assert result.returncode != 0
    assert "invalid exclude-newer package name" in result.stderr


def test_upgrade_refreshes_uv_lock_with_same_exception(
    lock_repository: Path, tmp_path: Path, upgrade_scripts: Path
) -> None:
    project = lock_repository / "pyproject.toml"
    project.write_text(
        project.read_text().replace("release = []", 'release = ["release-creator>=0.4.1,<0.4.2", "certifi"]')
    )
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        UV_EXCLUDE_NEWER="2026-10-14T00:00:00Z",
        EXCEPTION_TIMESTAMP="2026-10-21T00:00:00Z",
        EXCLUDE_NEWER_PACKAGES="release-creator",
    )
    assert result.returncode == 0, result.stderr
    packages = {
        package["name"]: package for package in tomllib.loads((lock_repository / "uv.lock").read_text())["package"]
    }
    assert packages["release-creator"]["version"] == "0.4.1"
    assert packages["certifi"]["version"] == "2026.7.22"


@pytest.mark.parametrize(
    ("changed_path", "keep_uv_lock", "expected"),
    [
        (None, False, False),
        ("pylock.toml", False, True),
        ("uv.lock", False, False),
        ("uv.lock", True, True),
    ],
    ids=["unchanged", "pylock", "ignored-uv-lock", "retained-uv-lock"],
)
def test_upgrade_emits_patch_only_for_change(
    lock_repository: Path,
    tmp_path: Path,
    upgrade_scripts: Path,
    changed_path: str | None,
    keep_uv_lock: bool,
    expected: bool,
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
        upgrade_scripts / "refresh-release-lock-7.sh",
        tmp_path,
        LOCK="pylock.toml",
        KEEP_UV_LOCK=str(keep_uv_lock).lower(),
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    assert result.returncode == 0
    assert (tmp_path / "output").read_text() == f"changed={str(expected).lower()}\n"
    assert (tmp_path / "lock.patch").exists() == expected
    if expected:
        assert f"diff --git a/{changed_path} b/{changed_path}" in (tmp_path / "lock.patch").read_text()


@pytest.mark.parametrize(
    ("unrelated", "keep_uv_lock", "accepted"),
    [(None, False, True), ("other.txt", False, False), ("uv.lock", False, False), ("uv.lock", True, True)],
    ids=["clean", "unrelated-file", "uv-lock-rejected", "uv-lock-retained"],
)
def test_upgrade_checks_refreshed_lock(
    lock_repository: Path,
    tmp_path: Path,
    upgrade_scripts: Path,
    unrelated: str | None,
    keep_uv_lock: bool,
    accepted: bool,
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
        upgrade_scripts / "refresh-release-lock-4.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
    )
    assert installed.returncode == 0, installed.stderr
    checked = execute(lock_repository, upgrade_scripts / "refresh-release-lock-5.sh", tmp_path)
    assert checked.returncode == 0, checked.stderr
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-6.sh",
        tmp_path,
        LOCK="pylock.toml",
        KEEP_UV_LOCK=str(keep_uv_lock).lower(),
    )
    assert (result.returncode == 0) == accepted, result.stderr
    assert ("prek changed file outside the lock file" in result.stderr) == (not accepted)


@pytest.mark.parametrize(
    ("path", "keep_uv_lock", "accepted"),
    [
        ("pylock.toml", False, True),
        (".pre-commit-config.yaml", False, True),
        ("uv.lock", False, False),
        ("uv.lock", True, True),
        ("other.txt", True, False),
    ],
    ids=["pylock", "hooks", "uv-lock-rejected", "uv-lock-retained", "unrelated-file"],
)
def test_upgrade_rejects_unrelated_patch(
    lock_repository: Path, tmp_path: Path, publish_scripts: Path, path: str, keep_uv_lock: bool, accepted: bool
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
        lock_repository,
        publish_scripts / "publish-check-dependency-patch-paths.sh",
        tmp_path,
        LOCK="pylock.toml",
        CONFIG=".pre-commit-config.yaml",
        KEEP_UV_LOCK=str(keep_uv_lock).lower(),
    )
    assert (result.returncode == 0) == accepted
    assert ("unexpected dependency path" in result.stderr) == (not accepted)


@pytest.mark.parametrize(
    ("path", "unsafe_mode"),
    [("pylock.toml", "executable"), (".pre-commit-config.yaml", "symlink")],
    ids=["executable-lock", "symlink-hook-config"],
)
def test_upgrade_rejects_unsafe_file_mode(
    lock_repository: Path, tmp_path: Path, publish_scripts: Path, path: str, unsafe_mode: str
) -> None:
    target = lock_repository / path
    target.write_text("before\n")
    run(lock_repository, "git", "add", path)
    run(lock_repository, "git", "commit", "-m", "Add lock")
    if unsafe_mode == "executable":
        target.chmod(0o755)
    else:
        target.unlink()
        target.symlink_to("other.txt")
    patch = run(lock_repository, "git", "diff", "--binary", "--", path).stdout
    run(lock_repository, "git", "restore", path)
    patch_dir = tmp_path / ("release-tools-lock" if path == "pylock.toml" else "release-tools-hooks")
    patch_dir.mkdir()
    (patch_dir / ("lock.patch" if path == "pylock.toml" else "hooks.patch")).write_text(patch)
    applied = execute(
        lock_repository,
        publish_scripts / ("publish-apply-lock-patch.sh" if path == "pylock.toml" else "publish-apply-hook-patch.sh"),
        tmp_path,
    )
    assert applied.returncode == 0, applied.stderr
    result = execute(lock_repository, publish_scripts / "publish-check-dependency-patch-file-mode.sh", tmp_path)
    assert result.returncode != 0
    assert "unexpected dependency file mode" in result.stderr


def test_upgrade_combines_lock_and_hook_patches(lock_repository: Path, tmp_path: Path, publish_scripts: Path) -> None:
    lock = lock_repository / "pylock.toml"
    config = lock_repository / ".pre-commit-config.yaml"
    lock.write_text('lock-version = "1.0"\n')
    config.write_text("repos: []\n")
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add dependency files")
    lock.write_text('lock-version = "1.1"\n')
    lock_patch = run(lock_repository, "git", "diff", "--binary", "--", "pylock.toml").stdout
    config.write_text("repos: [local]\n")
    hooks_patch = run(lock_repository, "git", "diff", "--binary", "--", ".pre-commit-config.yaml").stdout
    run(lock_repository, "git", "restore", ".")
    lock_artifact = tmp_path / "release-tools-lock"
    lock_artifact.mkdir()
    (lock_artifact / "lock.patch").write_text(lock_patch)
    hooks_artifact = tmp_path / "release-tools-hooks"
    hooks_artifact.mkdir()
    (hooks_artifact / "hooks.patch").write_text(hooks_patch)

    applied_lock = execute(lock_repository, publish_scripts / "publish-apply-lock-patch.sh", tmp_path)
    applied_hooks = execute(lock_repository, publish_scripts / "publish-apply-hook-patch.sh", tmp_path)
    checked = execute(
        lock_repository,
        publish_scripts / "publish-check-dependency-patch-paths.sh",
        tmp_path,
        LOCK="pylock.toml",
        CONFIG=".pre-commit-config.yaml",
        KEEP_UV_LOCK="false",
    )

    assert (applied_lock.returncode, applied_hooks.returncode, checked.returncode) == (0, 0, 0)
    assert run(lock_repository, "git", "diff", "--cached", "--name-only").stdout.splitlines() == [
        ".pre-commit-config.yaml",
        "pylock.toml",
    ]


def test_upgrade_lists_cutoff_exceptions_in_pull_request(
    lock_repository: Path, tmp_path: Path, publish_scripts: Path
) -> None:
    result = execute(
        lock_repository,
        publish_scripts / "publish-write-dependency-pull-request-body.sh",
        tmp_path,
        PR_BODY="Refresh release tools.",
        EXCLUDE_NEWER_PACKAGES="release-creator\nuv-build",
        EXCEPTION_TIMESTAMP="2026-10-21T12:00:00Z",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "pull-request.md").read_text() == (
        "Refresh release tools.\n\n"
        "Seven-day cutoff exceptions at 2026-10-21T12:00:00Z:\n"
        "- `release-creator=2026-10-21T12:00:00Z`\n"
        "- `uv-build=2026-10-21T12:00:00Z`\n"
    )


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
            "EXCLUDE_NEWER_PACKAGES": "",
        }
        | environment,
        text=True,
        capture_output=True,
        check=False,
    )
