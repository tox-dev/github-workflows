from __future__ import annotations

import os
import subprocess
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


def test_upgrade_emits_patch_for_lock_change(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    (lock_repository / "pylock.toml").write_text('lock-version = "1.0"\n')
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add lock")
    (lock_repository / "pylock.toml").write_text((lock_repository / "pylock.toml").read_text() + "\n")
    result = execute(
        lock_repository,
        refresh_script(upgrade_scripts, "lock"),
        tmp_path,
        MODE="refresh",
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "changed=true\n"
    assert "diff --git a/pylock.toml b/pylock.toml" in (tmp_path / "lock.patch").read_text()


@pytest.mark.parametrize(
    ("path", "additional_lock", "accepted"),
    [
        pytest.param("pylock.toml", "", True, id="lock"),
        pytest.param("pyproject.toml", "", False, id="project"),
        pytest.param("pylock.zipapp.toml", "pylock.zipapp.toml", True, id="secondary-lock"),
        pytest.param(".pre-commit-config.yaml", "", False, id="hook-config"),
        pytest.param("uv.lock", "", False, id="uv-lock"),
        pytest.param("other.txt", "", False, id="unrelated-file"),
    ],
)
def test_upgrade_checks_lock_patch_path(
    lock_repository: Path,
    tmp_path: Path,
    publish_scripts: Path,
    path: str,
    additional_lock: str,
    accepted: bool,
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
    result = execute(
        lock_repository,
        publish_scripts / "publish-check-artifact-patch-paths.sh",
        tmp_path,
        ADDITIONAL_LOCK=additional_lock,
    )
    assert (result.returncode == 0) == accepted
    assert (f"unexpected lock patch path: {path}" in result.stderr) == (not accepted)
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
    )

    assert result.returncode != 0
    assert "invalid additional lock" in result.stderr


@pytest.mark.parametrize("unsafe_mode", ["executable", "symlink"])
def test_upgrade_rejects_unsafe_file_mode(
    lock_repository: Path, tmp_path: Path, publish_scripts: Path, unsafe_mode: str
) -> None:
    target = lock_repository / "pylock.toml"
    target.write_text("before\n")
    run(lock_repository, "git", "add", "pylock.toml")
    run(lock_repository, "git", "commit", "-m", "Add lock")
    if unsafe_mode == "executable":
        target.chmod(0o755)
    else:
        target.unlink()
        target.symlink_to("other.txt")
    patch = run(lock_repository, "git", "diff", "--binary", "--", "pylock.toml").stdout
    run(lock_repository, "git", "restore", "pylock.toml")
    patch_dir = tmp_path / "release-tools-lock"
    patch_dir.mkdir()
    (patch_dir / "lock.patch").write_text(patch)
    applied = execute(lock_repository, publish_scripts / "publish-apply-lock-patch.sh", tmp_path)
    assert applied.returncode == 0, applied.stderr
    result = execute(lock_repository, publish_scripts / "publish-check-dependency-patch-file-mode.sh", tmp_path)
    assert result.returncode != 0
    assert "unexpected dependency file mode" in result.stderr


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
