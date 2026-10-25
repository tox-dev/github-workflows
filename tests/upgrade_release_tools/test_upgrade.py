from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from conftest import action, run
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


@pytest.fixture
def lock_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "0.1.0"\nrequires-python = ">=3.15"\n'
        "[dependency-groups]\nrelease = []\ntest = []\n"
        '[tool.nab]\nmode = "universal"\nuploaded-prior-to = "P7D"\n'
        'decision-order = "stable"\nbase-group = "project-runtime"\ndefault-groups = []\n'
        '[tool.nab.matrix]\npython = ">=3.15,<3.16"\n'
        'platforms = ["linux_x86_64", "linux_aarch64", "macos_arm64", "windows_amd64"]\n',
    )
    run(repository, "git", "init", "-b", "main")
    run(repository, "git", "config", "user.name", "Release test")
    run(repository, "git", "config", "user.email", "release@example.org")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Initial files")
    return repository


def test_upgrade_preserves_deliberate_nab_hold(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    project = lock_repository / "pyproject.toml"
    project.write_text(
        project.read_text()
        + '[[tool.nab.package-rules]]\nmatch = ["nab"]\nuploaded-prior-to = "2026-01-01T00:00:00Z"\n',
    )
    installed = action(
        lock_repository,
        tmp_path,
        upgrade_scripts,
        "install-locked-tools",
        version="",
        GROUPS="lock-tools",
        LOCK_SOURCE="shared",
        VENV=str(tmp_path / "lock-tools"),
    )
    assert installed.returncode == 0, installed.stderr
    expired = execute(lock_repository, refresh_script(upgrade_scripts, "Expire reviewed package cutoffs"), tmp_path)
    assert expired.returncode == 0, expired.stderr
    assert tomllib.loads(project.read_text())["tool"]["nab"]["package-rules"][0]["uploaded-prior-to"] == (
        "2026-01-01T00:00:00Z"
    )


@pytest.mark.parametrize(
    "changed_path",
    [pytest.param("pylock.toml", id="lock"), pytest.param("pyproject.toml", id="expired-floor")],
)
def test_upgrade_emits_patch_for_allowed_change(
    lock_repository: Path, tmp_path: Path, upgrade_scripts: Path, changed_path: str
) -> None:
    (lock_repository / "pylock.toml").write_text('lock-version = "1.0"\n')
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add lock")
    (lock_repository / changed_path).write_text((lock_repository / changed_path).read_text() + "\n")
    result = execute(
        lock_repository,
        refresh_script(upgrade_scripts, "lock"),
        tmp_path,
        MODE="refresh",
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "changed=true\n"
    assert f"diff --git a/{changed_path} b/{changed_path}" in (tmp_path / "lock.patch").read_text()


@pytest.mark.parametrize(
    ("path", "artifact", "additional_lock", "keep_uv_lock", "accepted"),
    [
        pytest.param("pylock.toml", "lock", "", False, True, id="lock"),
        pytest.param("pyproject.toml", "lock", "", False, True, id="nab-policy"),
        pytest.param("pylock.zipapp.toml", "lock", "pylock.zipapp.toml", False, True, id="secondary-lock"),
        pytest.param(".pre-commit-config.yaml", "hooks", "", False, True, id="hooks"),
        pytest.param(".pre-commit-config.yaml", "lock", "", False, False, id="hook-in-lock-artifact"),
        pytest.param("pylock.toml", "hooks", "", False, False, id="lock-in-hook-artifact"),
        pytest.param("pyproject.toml", "hooks", "", False, False, id="policy-in-hook-artifact"),
        pytest.param("uv.lock", "lock", "", False, False, id="uv-lock-disabled"),
        pytest.param("uv.lock", "lock", "", True, True, id="uv-lock-enabled"),
        pytest.param("other.txt", "lock", "", False, False, id="unrelated-file"),
    ],
)
def test_upgrade_checks_each_artifact_path(
    lock_repository: Path,
    tmp_path: Path,
    publish_scripts: Path,
    path: str,
    artifact: str,
    additional_lock: str,
    keep_uv_lock: bool,
    accepted: bool,
) -> None:
    (lock_repository / path).write_text("before\n")
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add file")
    (lock_repository / path).write_text("after\n")
    patch = run(lock_repository, "git", "diff", "--binary", "--", path).stdout
    run(lock_repository, "git", "restore", path)
    patch_dir = tmp_path / f"release-tools-{artifact}"
    patch_dir.mkdir()
    (patch_dir / f"{artifact}.patch").write_text(patch)
    result = execute(
        lock_repository,
        publish_scripts / "publish-check-artifact-patch-paths.sh",
        tmp_path,
        ADDITIONAL_LOCK=additional_lock,
        KEEP_UV_LOCK=str(keep_uv_lock).lower(),
        LOCK_CHANGED=str(artifact == "lock").lower(),
        HOOKS_CHANGED=str(artifact == "hooks").lower(),
    )
    assert (result.returncode == 0) == accepted
    assert (f"unexpected {artifact} patch path: {path}" in result.stderr) == (not accepted)
    assert run(lock_repository, "git", "status", "--porcelain").stdout == ""


@pytest.mark.parametrize("additional_lock", ["other.txt", "../pylock.other.toml"], ids=["arbitrary", "parent"])
def test_upgrade_rejects_unsafe_additional_lock(
    lock_repository: Path, tmp_path: Path, publish_scripts: Path, additional_lock: str
) -> None:
    (lock_repository / "pylock.toml").write_text("before\n")
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add lock")
    (lock_repository / "pylock.toml").write_text("after\n")
    run(lock_repository, "git", "add", "pylock.toml")

    result = execute(
        lock_repository,
        publish_scripts / "publish-check-artifact-patch-paths.sh",
        tmp_path,
        ADDITIONAL_LOCK=additional_lock,
        LOCK_CHANGED="true",
        HOOKS_CHANGED="false",
    )

    assert result.returncode != 0
    assert "invalid additional lock" in result.stderr


@pytest.mark.parametrize(
    ("path", "unsafe_mode"),
    [
        pytest.param("pylock.toml", "executable", id="executable-lock"),
        pytest.param(".pre-commit-config.yaml", "symlink", id="symlink-hook-config"),
    ],
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

    checked = execute(
        lock_repository,
        publish_scripts / "publish-check-artifact-patch-paths.sh",
        tmp_path,
        LOCK_CHANGED="true",
        HOOKS_CHANGED="true",
    )
    applied_lock = execute(lock_repository, publish_scripts / "publish-apply-lock-patch.sh", tmp_path)
    applied_hooks = execute(lock_repository, publish_scripts / "publish-apply-hook-patch.sh", tmp_path)

    assert (applied_lock.returncode, applied_hooks.returncode, checked.returncode) == (0, 0, 0)
    assert run(lock_repository, "git", "diff", "--cached", "--name-only").stdout.splitlines() == [
        ".pre-commit-config.yaml",
        "pylock.toml",
    ]


def test_upgrade_preserves_requested_pull_request_body(
    lock_repository: Path, tmp_path: Path, publish_scripts: Path
) -> None:
    result = execute(
        lock_repository,
        publish_scripts / "publish-write-dependency-pull-request-body.sh",
        tmp_path,
        PR_BODY="Refresh release tools.",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "pull-request.md").read_text() == "Refresh release tools.\n"


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
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "number=18\n"


def execute(repository: Path, script: Path, tmp_path: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        cwd=repository,
        env=os.environ
        | {
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "refresh-release-lock"),
            "ADDITIONAL_LOCK": "",
            "ADDITIONAL_GROUPS": "",
            "ADDITIONAL_SELECTION": "build-or-groups",
            "MATRIX_PYTHON": "",
            "MATRIX_PLATFORMS": "",
            "MATRIX_IMPLEMENTATIONS": "",
            "KEEP_UV_LOCK": "false",
        }
        | environment,
        text=True,
        capture_output=True,
        check=False,
    )


def refresh_script(scripts: Path, name: str) -> Path:
    source = Path(__file__).resolve().parents[2]
    steps = yaml.safe_load((source / "refresh-release-lock/action.yml").read_text())["runs"]["steps"]
    index = next(index for index, step in enumerate(steps) if step.get("name", step.get("id")) == name)
    return scripts / f"refresh-release-lock-{index}.sh"
