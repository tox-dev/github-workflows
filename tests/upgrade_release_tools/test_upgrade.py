from __future__ import annotations

import os
import subprocess
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from conftest import run
from pytest_httpserver import HTTPServer


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


def test_upgrade_pull_request_uses_repository_app() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/upgrade-release-tools.yaml").read_text()
    )
    publish = workflow["jobs"]["publish"]
    assert publish["environment"] == "release-auth"
    assert publish["permissions"] == {"contents": "read"}
    token = next(step for step in publish["steps"] if step.get("id") == "token")
    assert token["with"]["repositories"] == "${{ steps.repository.outputs.name }}"
    assert token["with"]["permission-contents"] == "write"
    assert token["with"]["permission-pull-requests"] == "write"
    for step in publish["steps"]:
        if step.get("name") in {
            "Push dependency branch",
            "Find dependency pull request",
            "Update dependency pull request",
            "Open dependency pull request",
        }:
            assert step["env"]["GH_TOKEN"] == "${{ steps.token.outputs.token }}"


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
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
    )
    assert result.returncode == 0, result.stderr
    lock = tomllib.loads((lock_repository / "pylock.toml").read_text())
    assert (lock["requires-python"], lock["dependency-groups"]) == (
        ">=3.15",
        ["project-runtime", "release", "test", "build"],
    )


def test_upgrade_refreshes_backend_constraints(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    installed = execute(lock_repository, upgrade_scripts / "refresh-release-lock-0.sh", tmp_path, PYTHON_VERSION="3.15")
    assert installed.returncode == 0, installed.stderr
    locked = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
    )
    assert locked.returncode == 0, locked.stderr
    generated = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-5.sh",
        tmp_path,
        LOCK="pylock.toml",
        BUILD_CONSTRAINTS="release-build-constraints.txt",
        PYTHON_VERSION="3.15",
    )
    assert generated.returncode == 0, generated.stderr
    constraints = (lock_repository / "release-build-constraints.txt").read_text()
    assert "cython==" in constraints
    assert "setuptools==" in constraints


def test_upgrade_does_not_force_shared_build_requirements(
    lock_repository: Path, tmp_path: Path, upgrade_scripts: Path
) -> None:
    installed = execute(lock_repository, upgrade_scripts / "refresh-release-lock-0.sh", tmp_path, PYTHON_VERSION="3.15")
    assert installed.returncode == 0, installed.stderr
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
        BUILD_REQUIREMENTS="",
    )
    assert result.returncode == 0, result.stderr
    packages = {item["name"] for item in tomllib.loads((lock_repository / "pylock.toml").read_text())["packages"]}
    assert "cython" not in packages
    assert "setuptools" not in packages


@pytest.mark.parametrize(
    "path",
    ["pyproject.toml", "../build-constraints.txt", "/tmp/build-constraints.txt", ".git/build-constraints.txt"],
    ids=["project-file", "parent", "absolute", "git-internals"],
)
def test_upgrade_rejects_unsafe_constraints_path(
    lock_repository: Path, tmp_path: Path, upgrade_scripts: Path, path: str
) -> None:
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-5.sh",
        tmp_path,
        BUILD_CONSTRAINTS=path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
    )
    assert result.returncode != 0
    assert "backend constraints" in result.stderr


def test_upgrade_includes_new_constraints_file_in_patch(
    lock_repository: Path, tmp_path: Path, upgrade_scripts: Path
) -> None:
    (lock_repository / "pylock.toml").write_text('lock-version = "1.0"\n')
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add lock")
    (lock_repository / "release-build-constraints.txt").write_text("new\n")
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-9.sh",
        tmp_path,
        BUILD_CONSTRAINTS="release-build-constraints.txt",
        LOCK="pylock.toml",
        KEEP_UV_LOCK="false",
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    assert result.returncode == 0, result.stderr
    assert "new file mode 100644" in (tmp_path / "lock.patch").read_text()


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


def test_upgrade_exempts_only_named_young_package(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    project = lock_repository / "pyproject.toml"
    project.write_text(
        project.read_text().replace("release = []", 'release = ["release-creator>=0.4.1,<0.4.2", "certifi"]')
    )
    installed = execute(lock_repository, upgrade_scripts / "refresh-release-lock-0.sh", tmp_path, PYTHON_VERSION="3.15")
    assert installed.returncode == 0, installed.stderr
    blocked = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
        UV_EXCLUDE_NEWER="2026-10-14T00:00:00Z",
        EXCLUDE_NEWER_PACKAGES="",
    )
    assert blocked.returncode != 0
    allowed = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
        UV_EXCLUDE_NEWER="2026-10-14T00:00:00Z",
        EXCLUDE_NEWER_PACKAGES="release-creator=2026-10-19T20:26:31Z",
    )
    assert allowed.returncode == 0, allowed.stderr
    packages = {
        package["name"]: package for package in tomllib.loads((lock_repository / "pylock.toml").read_text())["packages"]
    }
    assert packages["release-creator"]["version"] == "0.4.1"
    assert packages["certifi"]["version"] == "2026.7.22"


@pytest.mark.parametrize(
    "entry",
    [
        "release-creator; true=2026-10-19T20:26:31Z",
        "release-creator",
        "release-creator=tomorrow",
        "release-creator=2999-01-01T00:00:00Z",
    ],
    ids=["invalid-name", "missing-date", "invalid-date", "future-date"],
)
def test_upgrade_rejects_invalid_exception(
    lock_repository: Path, tmp_path: Path, upgrade_scripts: Path, entry: str
) -> None:
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-2.sh",
        tmp_path,
        EXCLUDE_NEWER_PACKAGES=entry,
    )
    assert result.returncode != 0
    assert "invalid package cutoff" in result.stderr


def test_upgrade_refreshes_uv_lock_with_same_exception(
    lock_repository: Path, tmp_path: Path, upgrade_scripts: Path
) -> None:
    project = lock_repository / "pyproject.toml"
    project.write_text(
        project.read_text().replace("release = []", 'release = ["release-creator>=0.4.1,<0.4.2", "certifi"]')
    )
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-4.sh",
        tmp_path,
        UV_EXCLUDE_NEWER="2026-10-14T00:00:00Z",
        EXCLUDE_NEWER_PACKAGES="release-creator=2026-10-19T20:26:31Z",
    )
    assert result.returncode == 0, result.stderr
    packages = {
        package["name"]: package for package in tomllib.loads((lock_repository / "uv.lock").read_text())["package"]
    }
    assert packages["release-creator"]["version"] == "0.4.1"
    assert packages["certifi"]["version"] == "2026.7.22"


@pytest.mark.parametrize(
    ("changed_path", "keep_uv_lock", "build_constraints", "expected"),
    [
        (None, False, False, False),
        ("pylock.toml", False, False, True),
        ("uv.lock", False, False, False),
        ("uv.lock", True, False, True),
        ("release-build-constraints.txt", False, True, True),
    ],
    ids=["unchanged", "pylock", "ignored-uv-lock", "retained-uv-lock", "backend-constraints"],
)
def test_upgrade_emits_patch_only_for_change(
    lock_repository: Path,
    tmp_path: Path,
    upgrade_scripts: Path,
    changed_path: str | None,
    keep_uv_lock: bool,
    build_constraints: bool,
    expected: bool,
) -> None:
    lock = lock_repository / "pylock.toml"
    lock.write_text('lock-version = "1.0"\n')
    (lock_repository / "uv.lock").write_text("before\n")
    (lock_repository / "release-build-constraints.txt").write_text("before\n")
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add lock")
    if changed_path is not None:
        (lock_repository / changed_path).write_text("after\n")
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-9.sh",
        tmp_path,
        LOCK="pylock.toml",
        KEEP_UV_LOCK=str(keep_uv_lock).lower(),
        BUILD_CONSTRAINTS="release-build-constraints.txt" if build_constraints else "",
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
        "release-creator",
        "locks",
        "--output",
        "pylock.toml",
        "--tool-python",
        ">=3.15",
        "--build-requirement",
        "Cython>=3.0",
        "--build-requirement",
        "setuptools>=80",
    )
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add release tools")
    if unrelated is not None:
        (lock_repository / unrelated).write_text("after\n")
    exporter = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-0.sh",
        tmp_path,
        PYTHON_VERSION="3.15",
    )
    assert exporter.returncode == 0, exporter.stderr
    source = Path(__file__).resolve().parents[2]
    refresh = yaml.safe_load((source / "refresh-release-lock/action.yml").read_text())
    assert refresh["runs"]["steps"][6]["uses"] == "$/install-locked-tools"
    for index in range(3):
        installed = execute(
            lock_repository,
            upgrade_scripts / f"install-locked-tools-{index}.sh",
            tmp_path,
            GITHUB_ACTION_PATH=str(source / "install-locked-tools"),
            LOCK="pylock.toml",
            DEPENDENCY_GROUPS="release",
            VENV=str(tmp_path / "release-tools"),
            PYTHON_VERSION="3.15",
        )
        assert installed.returncode == 0, installed.stderr
    checked = execute(lock_repository, upgrade_scripts / "refresh-release-lock-7.sh", tmp_path)
    assert checked.returncode == 0, checked.stderr
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-8.sh",
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
        EXCLUDE_NEWER_PACKAGES="release-creator=2026-10-19T20:26:31Z\nuv-build=2026-10-20T15:11:07Z",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "pull-request.md").read_text() == (
        "Refresh release tools.\n\n"
        "Reviewed package cutoff floors:\n"
        "- `release-creator=2026-10-19T20:26:31Z`\n"
        "- `uv-build=2026-10-20T15:11:07Z`\n"
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


def test_upgrade_finds_only_own_dependency_pull_request(
    lock_repository: Path,
    tmp_path: Path,
    publish_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    server, environment = github_api
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/pulls",
        method="GET",
        query_string="base=main&head=tox-dev%3Aautomation%2Fupdate-release-tools&state=open",
    ).respond_with_json(
        [
            {
                "number": 17,
                "head": {"repo": {"full_name": "attacker/fork"}, "ref": "automation/update-release-tools"},
                "base": {"ref": "main"},
            },
            {
                "number": 18,
                "head": {"repo": {"full_name": "tox-dev/fixture"}, "ref": "automation/update-release-tools"},
                "base": {"ref": "main"},
            },
        ]
    )
    result = execute(
        lock_repository,
        publish_scripts / "publish-pr.sh",
        tmp_path,
        **environment,
        GITHUB_REPOSITORY="tox-dev/fixture",
        GITHUB_OUTPUT=str(tmp_path / "output"),
        BRANCH="automation/update-release-tools",
        BASE="main",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "number=18\n"


def execute(repository: Path, script: Path, tmp_path: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    active_cutoffs = tmp_path / "active-package-cutoffs"
    active_cutoffs.write_text(f"{environment.get('EXCLUDE_NEWER_PACKAGES', '')}\n")
    return subprocess.run(
        ["bash", str(script)],
        cwd=repository,
        env=os.environ
        | {
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "refresh-release-lock"),
            "EXCLUDE_NEWER_PACKAGES": "",
            "BUILD_CONSTRAINTS": "",
            "BUILD_REQUIREMENTS": "Cython>=3.0\nsetuptools>=80",
            "HOOK_CONFIG": ".pre-commit-config.yaml",
            "ACTIVE_PACKAGE_CUTOFFS": str(active_cutoffs),
        }
        | environment,
        text=True,
        capture_output=True,
        check=False,
    )
