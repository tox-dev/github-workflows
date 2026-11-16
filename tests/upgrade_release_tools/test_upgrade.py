import os
import subprocess
from pathlib import Path
from typing import Final

import pytest
from conftest import WORKFLOWS, JsonObject, at, load_yaml, run, step, step_list, steps

ROOT: Final = Path(__file__).resolve().parents[2]


@pytest.fixture
def workflow() -> JsonObject:
    return load_yaml(WORKFLOWS / "upgrade-release-tools.yaml")


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


def test_upgrade_emits_patch_for_lock_change(lock_repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (lock_repository / "pylock.toml").write_text('lock-version = "1.0"\n')
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add lock")
    (lock_repository / "pylock.toml").write_text((lock_repository / "pylock.toml").read_text() + "\n")
    result = execute(
        lock_repository,
        refresh_script(action_scripts, "lock"),
        tmp_path,
        MODE="refresh",
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "changed=true\n"
    assert "diff --git a/pylock.toml b/pylock.toml" in (tmp_path / "maintenance.patch").read_text()


def test_upgrade_hands_the_patch_to_the_maintenance_writer(workflow: JsonObject) -> None:
    assert at(workflow, "jobs", "open") == {
        "name": "🔀 Open release tools PR",
        "needs": "generate-lock",
        "if": "needs.generate-lock.outputs.changed == 'true'",
        "permissions": {"contents": "read"},
        "uses": "$/.github/workflows/open-maintenance-pr.yaml",
        "with": {
            "artifact-id": "${{ needs.generate-lock.outputs.artifact-id }}",
            "allowed-paths": "pylock.toml\npyproject.toml\nnab.toml\n${{ inputs.additional-lock }}\n",
            "branch": "automation/update-release-tools",
            "title": "${{ inputs.pull-request-title }}",
            "body": "${{ inputs.pull-request-body }}",
            "labels": "dependencies\nskip news\n",
        },
        "secrets": {"RELEASE_APP_PRIVATE_KEY": "${{ secrets.RELEASE_APP_PRIVATE_KEY }}"},
    }


def test_upgrade_checks_cutoff_exceptions_after_dropping_the_redundant_ones(workflow: JsonObject) -> None:
    names = [item["name"] for item in steps(workflow, "generate-lock")]

    assert step(workflow, "generate-lock", "📅 Check cutoff exception expiry")["uses"] == "$/check-nab-exceptions"
    assert at(step(workflow, "generate-lock", "🔒 Refresh release lock"), "with", "drop-redundant-exceptions") == "true"
    assert (
        names.index("🔒 Refresh release lock")
        < names.index("📅 Check cutoff exception expiry")
        < names.index("📤 Upload maintenance patch")
    )


def test_upgrade_restores_a_lock_whose_only_change_is_its_anchor(
    anchored_lock: Path, tmp_path: Path, action_scripts: Path
) -> None:
    result = execute(
        anchored_lock,
        refresh_script(action_scripts, "lock"),
        tmp_path,
        MODE="refresh",
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "changed=false\n"
    assert run(anchored_lock, "git", "status", "--porcelain").stdout == ""


def test_upgrade_keeps_the_lock_anchor_that_dropped_exceptions_need(
    anchored_lock: Path, tmp_path: Path, action_scripts: Path
) -> None:
    project = anchored_lock / "pyproject.toml"
    project.write_text(project.read_text() + "\n")

    result = execute(
        anchored_lock,
        refresh_script(action_scripts, "lock"),
        tmp_path,
        MODE="refresh",
        DROPPED="pyproject.toml",
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "changed=true\n"
    patch = (tmp_path / "maintenance.patch").read_text()
    assert [line for line in patch.splitlines() if line.startswith("diff --git")] == [
        "diff --git a/pylock.toml b/pylock.toml",
        "diff --git a/pyproject.toml b/pyproject.toml",
    ]
    assert "+created-at = 2026-11-17T00:00:00Z" in patch


@pytest.fixture
def anchored_lock(lock_repository: Path) -> Path:
    lock = lock_repository / "pylock.toml"
    lock.write_text('lock-version = "1.0"\n[tool.nab]\ncreated-at = 2026-11-03T00:00:00Z\n')
    run(lock_repository, "git", "add", ".")
    run(lock_repository, "git", "commit", "-m", "Add lock")
    lock.write_text(lock.read_text().replace("2026-11-03", "2026-11-17"))
    return lock_repository


def execute(repository: Path, script: Path, tmp_path: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        cwd=repository,
        env=os.environ
        | {
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ACTION_PATH": str(ROOT / "refresh-release-lock"),
            "ADDITIONAL_LOCK": "",
            "ADDITIONAL_GROUPS": "",
            "ADDITIONAL_SELECTION": "build-or-groups",
            "MATRIX_PYTHON": "",
            "MATRIX_PLATFORMS": "",
            "MATRIX_IMPLEMENTATIONS": "",
            "DROPPED": "",
        }
        | environment,
        text=True,
        capture_output=True,
        check=False,
    )


def refresh_script(scripts: Path, name: str) -> Path:
    action_steps = step_list(at(load_yaml(ROOT / "refresh-release-lock/action.yml"), "runs", "steps"))
    index = next(index for index, item in enumerate(action_steps) if item.get("id") == name)
    return scripts / f"refresh-release-lock-{index}.sh"
