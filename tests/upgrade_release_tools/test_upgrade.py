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


def test_upgrade_pull_request_uses_repository_app() -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/upgrade-release-tools.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    publish = workflow["jobs"]["publish"]
    assert workflow["on"]["workflow_call"]["inputs"]["lock-groups"]["required"] == "true"
    assert workflow["jobs"]["generate-lock"]["steps"][2]["with"]["lock-groups"] == "${{ inputs.lock-groups }}"
    assert publish["environment"] == "release-auth"
    assert publish["permissions"] == {"contents": "read"}
    token = next(step for step in publish["steps"] if step.get("id") == "token")
    assert token["with"]["repositories"] == "${{ steps.repository.outputs.name }}"
    assert token["with"]["permission-contents"] == "write"
    assert token["with"]["permission-pull-requests"] == "write"
    steps = publish["steps"]
    assert next(index for index, step in enumerate(steps) if step.get("uses") == "$/verify-nab-cutoff-patch") < next(
        index for index, step in enumerate(steps) if step.get("id") == "token"
    )
    for step in publish["steps"]:
        if step.get("name") in {
            "Push dependency branch",
            "Find dependency pull request",
            "Update dependency pull request",
            "Open dependency pull request",
        }:
            assert step["env"]["GH_TOKEN"] == "${{ steps.token.outputs.token }}"


@pytest.fixture
def lock_repository(tmp_path: Path, test_package_index: str) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "0.1.0"\nrequires-python = ">=3.15"\n'
        "[dependency-groups]\nrelease = []\ntest = []\n"
        '[tool.nab]\nmode = "universal"\nuploaded-prior-to = "P7D"\n'
        'decision-order = "stable"\nbase-group = "project-runtime"\ndefault-groups = []\n'
        '[tool.nab.matrix]\npython = ">=3.15,<3.16"\n'
        'platforms = ["linux_x86_64", "linux_aarch64", "macos_arm64", "windows_amd64"]\n'
        f'[[tool.nab.indexes]]\nname = "fixture"\nurl = "{test_package_index}"\nserialization = "html"\n',
    )
    run(repository, "git", "init", "-b", "main")
    run(repository, "git", "config", "user.name", "Release test")
    run(repository, "git", "config", "user.email", "release@example.org")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Initial files")
    return repository


def test_upgrade_locks_only_selected_groups(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    project = lock_repository / "pyproject.toml"
    project.write_text(project.read_text().replace("release = []", 'release-check = ["prek>=0.2"]'))
    installed = action(lock_repository, tmp_path, upgrade_scripts, "install-nab", version="")
    assert installed.returncode == 0, installed.stderr
    resolved = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        LOCK_GROUPS="release-check",
        MODE="refresh",
    )
    assert resolved.returncode == 0, resolved.stderr
    lock = tomllib.loads((lock_repository / "pylock.toml").read_text())
    assert lock["dependency-groups"] == ["project-runtime", "release-check"]
    assert "test" not in {package["name"] for package in lock["packages"]}


def test_upgrade_check_mode_preserves_lock_bytes(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    project = lock_repository / "pyproject.toml"
    project.write_text(
        project.read_text().replace("release = []", 'release-check = ["prek>=0.2"]')
        + '[tool.nab.packages.old]\nuploaded-prior-to = "2020-01-01T00:00:00Z"\n'
    )
    installed = action(lock_repository, tmp_path, upgrade_scripts, "install-nab", version="")
    assert installed.returncode == 0, installed.stderr
    refreshed = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        LOCK_GROUPS="release-check",
        MODE="refresh",
    )
    assert refreshed.returncode == 0, refreshed.stderr
    expected = (lock_repository / "pylock.toml").read_bytes()
    project_bytes = project.read_bytes()
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Record lock")
    (lock_repository / "pylock.toml").write_bytes(expected.replace(b'"release-check"', b'"release-news"', 1))
    stale = (lock_repository / "pylock.toml").read_bytes()
    checked = action(
        lock_repository,
        tmp_path,
        upgrade_scripts,
        "refresh-release-lock",
        version="",
        LOCK_GROUPS="release-check",
        MODE="check",
    )
    assert checked.returncode != 0
    assert "regenerated Nab lock differs" in checked.stderr
    assert (lock_repository / "pylock.toml").read_bytes() != stale
    assert project.read_bytes() == project_bytes


@pytest.mark.parametrize(
    ("groups", "selection", "source"),
    [
        pytest.param("", "--build-requirements", "build-or-groups", id="build-only"),
        pytest.param("release-check", "--groups", "build-or-groups", id="selected-group"),
        pytest.param("", "", "project", id="project-runtime"),
    ],
)
def test_upgrade_preserves_secondary_lock_matrix(
    lock_repository: Path, tmp_path: Path, upgrade_scripts: Path, groups: str, selection: str, source: str
) -> None:
    project = lock_repository / "pyproject.toml"
    project.write_text(
        project.read_text()
        .replace('version = "0.1.0"', 'version = "0.1.0"\ndependencies = ["packaging>=26"]')
        .replace("release = []", 'release-check = ["prek>=0.2"]')
        + '[build-system]\nrequires = ["setuptools>=80"]\nbuild-backend = "setuptools.build_meta"\n',
    )
    installed = action(lock_repository, tmp_path, upgrade_scripts, "install-nab", version="")
    assert installed.returncode == 0, installed.stderr
    primary = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        LOCK_GROUPS="release-check",
        MODE="refresh",
    )
    assert primary.returncode == 0, primary.stderr
    additional = lock_repository / "pylock.build.toml"
    command = [
        "uv",
        "run",
        "--no-project",
        "--python",
        str(tmp_path / "lock-tools"),
        "nab",
        "lock",
        "pyproject.toml",
    ]
    if selection:
        command.append(selection)
    if groups:
        command.append(groups)
    command.extend(
        [
            "--project-matrix-python",
            ">=3.15,<3.16",
            "--project-matrix-platforms",
            "linux_x86_64",
            "macos_arm64",
            "--project-matrix-implementations",
            "cpython",
            "--output",
            str(additional),
        ],
    )
    initial = subprocess.run(command, cwd=lock_repository, text=True, capture_output=True, check=False)
    assert initial.returncode == 0, initial.stderr
    expected = additional.read_bytes()
    environment = {
        "LOCK_GROUPS": "release-check",
        "MODE": "check",
        "ADDITIONAL_LOCK": additional.name,
        "ADDITIONAL_GROUPS": groups,
        "ADDITIONAL_SELECTION": source,
        "MATRIX_PYTHON": ">=3.15,<3.16",
        "MATRIX_PLATFORMS": "linux_x86_64 macos_arm64",
        "MATRIX_IMPLEMENTATIONS": "cpython",
    }
    checked = execute(lock_repository, upgrade_scripts / "refresh-release-lock-3.sh", tmp_path, **environment)
    assert checked.returncode == 0, checked.stderr
    assert additional.read_bytes() == expected
    if source == "project":
        names = {package["name"] for package in tomllib.loads(expected.decode())["packages"]}
        assert "packaging" in names
        assert "setuptools" not in names


def test_upgrade_rejects_secondary_matrix_change(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    project = lock_repository / "pyproject.toml"
    project.write_text(project.read_text().replace("release = []", 'release-check = ["prek>=0.2"]'))
    installed = action(lock_repository, tmp_path, upgrade_scripts, "install-nab", version="")
    assert installed.returncode == 0, installed.stderr
    initial = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        LOCK_GROUPS="release-check",
        MODE="refresh",
    )
    assert initial.returncode == 0, initial.stderr
    (lock_repository / "pylock.build.toml").write_bytes((lock_repository / "pylock.toml").read_bytes())
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-3.sh",
        tmp_path,
        LOCK_GROUPS="release-check",
        MODE="refresh",
        ADDITIONAL_LOCK="pylock.build.toml",
        ADDITIONAL_GROUPS="release-check",
        MATRIX_PYTHON=">=3.15,<3.16",
        MATRIX_PLATFORMS="linux_x86_64",
        MATRIX_IMPLEMENTATIONS="cpython",
    )
    assert result.returncode != 0
    assert "changed its target environments" in result.stderr


def test_upgrade_expires_old_nab_floor(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    project = lock_repository / "pyproject.toml"
    project.write_text(
        project.read_text()
        + '[[tool.nab.package-rules]]\nmatch = ["nab"]\nuploaded-prior-to = "2026-01-01T00:00:00Z"\n',
    )
    installed = action(lock_repository, tmp_path, upgrade_scripts, "install-nab", version="")
    assert installed.returncode == 0, installed.stderr
    expired = execute(lock_repository, upgrade_scripts / "refresh-release-lock-2.sh", tmp_path)
    assert expired.returncode == 0, expired.stderr
    assert "package-rules" not in tomllib.loads(project.read_text())["tool"]["nab"]


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
        upgrade_scripts / "refresh-release-lock-7.sh",
        tmp_path,
        MODE="refresh",
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "changed=true\n"
    assert f"diff --git a/{changed_path} b/{changed_path}" in (tmp_path / "lock.patch").read_text()


def test_upgrade_check_mode_rejects_lock_drift(lock_repository: Path, tmp_path: Path, upgrade_scripts: Path) -> None:
    (lock_repository / "pylock.toml").write_text('lock-version = "1.0"\n')
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add lock")
    (lock_repository / "pylock.toml").write_text('lock-version = "1.1"\n')
    result = execute(
        lock_repository,
        upgrade_scripts / "refresh-release-lock-7.sh",
        tmp_path,
        MODE="check",
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    assert result.returncode != 0


@pytest.mark.parametrize(
    "path",
    [pytest.param("other.txt", id="unrelated-file"), pytest.param("uv.lock", id="uv-lock")],
)
def test_upgrade_rejects_unrelated_change(
    lock_repository: Path, tmp_path: Path, upgrade_scripts: Path, path: str
) -> None:
    (tmp_path / "project-after-expiry.toml").write_bytes((lock_repository / "pyproject.toml").read_bytes())
    (lock_repository / path).write_text("changed\n")
    result = execute(lock_repository, upgrade_scripts / "refresh-release-lock-6.sh", tmp_path)
    assert result.returncode != 0
    assert "outside the lock and cutoff policy" in result.stderr


@pytest.mark.parametrize(
    ("path", "accepted"),
    [
        pytest.param("pylock.toml", True, id="lock"),
        pytest.param("pyproject.toml", True, id="nab-policy"),
        pytest.param(".pre-commit-config.yaml", True, id="hooks"),
        pytest.param("uv.lock", False, id="uv-lock"),
        pytest.param("other.txt", False, id="unrelated-file"),
    ],
)
def test_upgrade_rejects_unrelated_patch(
    lock_repository: Path, tmp_path: Path, publish_scripts: Path, path: str, accepted: bool
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
    result = execute(lock_repository, publish_scripts / "publish-check-dependency-patch-paths.sh", tmp_path)
    assert (result.returncode == 0) == accepted
    assert ("unexpected dependency path" in result.stderr) == (not accepted)


def test_upgrade_allows_only_named_secondary_lock(lock_repository: Path, tmp_path: Path, publish_scripts: Path) -> None:
    for name in ("pylock.build.toml", "pylock.pgo.toml"):
        (lock_repository / name).write_text("before\n")
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add secondary locks")
    (lock_repository / "pylock.build.toml").write_text("after\n")
    patch = run(lock_repository, "git", "diff", "--binary", "--", "pylock.build.toml").stdout
    run(lock_repository, "git", "restore", "pylock.build.toml")
    patch_dir = tmp_path / "release-tools-lock"
    patch_dir.mkdir()
    (patch_dir / "lock.patch").write_text(patch)
    applied = execute(lock_repository, publish_scripts / "publish-apply-lock-patch.sh", tmp_path)
    assert applied.returncode == 0, applied.stderr
    accepted = execute(
        lock_repository,
        publish_scripts / "publish-check-dependency-patch-paths.sh",
        tmp_path,
        ADDITIONAL_LOCK="pylock.build.toml",
    )
    assert accepted.returncode == 0, accepted.stderr
    rejected = execute(
        lock_repository,
        publish_scripts / "publish-check-dependency-patch-paths.sh",
        tmp_path,
        ADDITIONAL_LOCK="pylock.pgo.toml",
    )
    assert rejected.returncode != 0
    assert "unexpected dependency path: pylock.build.toml" in rejected.stderr


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

    applied_lock = execute(lock_repository, publish_scripts / "publish-apply-lock-patch.sh", tmp_path)
    applied_hooks = execute(lock_repository, publish_scripts / "publish-apply-hook-patch.sh", tmp_path)
    checked = execute(
        lock_repository,
        publish_scripts / "publish-check-dependency-patch-paths.sh",
        tmp_path,
    )

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
        }
        | environment,
        text=True,
        capture_output=True,
        check=False,
    )
