from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from conftest import WORKFLOWS, run, run_workflow_step, workflow_step

if TYPE_CHECKING:
    from collections.abc import Mapping

WORKFLOW = "open-maintenance-pr.yaml"
CHECK = "🔍 Check patch paths and modes"
APPLY = "⚙️ Apply maintenance patch to a scratch index"
ALLOWED = "pylock.toml\npyproject.toml\ndiagrams/*.svg\n"


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repository"
    repo.mkdir()
    run(repo, "git", "init", "-b", "main")
    run(repo, "git", "config", "user.name", "Release test")
    run(repo, "git", "config", "user.email", "release@example.org")
    (repo / "pylock.toml").write_text("lock-version = '1.0'\n")
    (repo / "pyproject.toml").write_text('[project]\nname = "example"\n')
    (repo / "docs").mkdir()
    (repo / "docs/readme.md").write_text("Docs.\n")
    (repo / "diagrams").mkdir()
    (repo / "diagrams/a.svg").write_text("<svg/>\n")
    (repo / "diagrams/a.txt").write_text("text\n")
    (repo / "pylockXtoml").write_text("not the lock\n")
    run(repo, "git", "add", ".")
    run(repo, "git", "commit", "-m", "Initial files")
    return repo


def make_patch(repo: Path, tmp_path: Path, change: Mapping[str, str | None], *, mode: int | None = None) -> Path:
    for path, text in change.items():
        target = repo / path
        if text is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        if mode is not None:
            target.chmod(mode)
    run(repo, "git", "add", "-A")
    patch = tmp_path / "maintenance-patch" / "maintenance.patch"
    patch.parent.mkdir(exist_ok=True)
    patch.write_text(run(repo, "git", "diff", "--cached", "--binary", "--no-renames").stdout)
    run(repo, "git", "reset", "-q", "--hard", "HEAD")
    run(repo, "git", "clean", "-fdq")
    return patch


def values(tmp_path: Path, allowed: str = ALLOWED, **extra: str) -> dict[str, str]:
    return {
        "inputs.allowed-paths": allowed,
        "inputs.artifact-id": "1",
        "inputs.base": "main",
        "inputs.body": "Body.",
        "inputs.branch": "automation/maintenance",
        "inputs.labels": "",
        "inputs.title": "Maintain things",
        "needs.validate.outputs.patch-sha256": "",
        "runner.temp": str(tmp_path),
        "steps.token.outputs.token": "token",
    } | extra


def check_patch(repo: Path, tmp_path: Path, allowed: str = ALLOWED) -> subprocess.CompletedProcess[str]:
    for name in (APPLY, CHECK):
        result, _ = run_workflow_step(
            WORKFLOW, "validate", name, cwd=repo, runner_temp=tmp_path, values=values(tmp_path, allowed)
        )
        if result.returncode:
            return result
    return result


@pytest.mark.parametrize(
    ("change", "mode", "accepted"),
    [
        pytest.param({"pylock.toml": "changed\n"}, None, True, id="modify-allowed"),
        pytest.param({"diagrams/new.svg": "<svg/>\n"}, None, True, id="add-glob-match"),
        pytest.param({"pyproject.toml": None}, None, True, id="delete-allowed"),
        pytest.param({"docs/readme.md": "changed\n"}, None, False, id="modify-disallowed"),
        pytest.param({"diagrams/a.txt": "changed\n"}, None, False, id="glob-misses-other-suffix"),
        pytest.param({"pylock.toml": "x\n"}, 0o755, False, id="executable-mode"),
        pytest.param({"pylockXtoml": "changed\n"}, None, False, id="dot-is-literal"),
    ],
)
def test_check_accepts_only_allowed_regular_changes(
    repository: Path, tmp_path: Path, change: dict[str, str | None], mode: int | None, accepted: bool
) -> None:
    make_patch(repository, tmp_path, change, mode=mode)
    result = check_patch(repository, tmp_path)
    assert (result.returncode == 0) == accepted, result.stderr
    if not accepted:
        assert "::error::" in result.stderr


def test_check_rejects_symlink_replacing_a_regular_file(repository: Path, tmp_path: Path) -> None:
    (repository / "pylock.toml").unlink()
    (repository / "pylock.toml").symlink_to("pyproject.toml")
    make_patch_from_working_tree(repository, tmp_path)
    result = check_patch(repository, tmp_path)
    assert result.returncode != 0
    assert "unexpected maintenance path status T for pylock.toml" in result.stderr


def make_patch_from_working_tree(repo: Path, tmp_path: Path) -> None:
    run(repo, "git", "add", "-A")
    patch = tmp_path / "maintenance-patch" / "maintenance.patch"
    patch.parent.mkdir(exist_ok=True)
    patch.write_text(run(repo, "git", "diff", "--cached", "--binary", "--no-renames").stdout)
    run(repo, "git", "reset", "-q", "--hard", "HEAD")


def test_check_rejects_empty_patch(repository: Path, tmp_path: Path) -> None:
    patch = tmp_path / "maintenance-patch" / "maintenance.patch"
    patch.parent.mkdir()
    patch.write_text("")
    result = check_patch(repository, tmp_path)
    assert result.returncode != 0


def test_check_rejects_empty_allowed_paths(repository: Path, tmp_path: Path) -> None:
    make_patch(repository, tmp_path, {"pylock.toml": "x\n"})
    result = check_patch(repository, tmp_path, allowed="\n")
    assert result.returncode != 0
    assert "allowed-paths lists no pattern" in result.stderr


def test_writer_repeats_the_validation_step() -> None:
    assert workflow_step(WORKFLOW, "validate", CHECK)["run"] == workflow_step(WORKFLOW, "open", CHECK)["run"]


def test_digest_step_records_sha256(repository: Path, tmp_path: Path) -> None:
    patch = make_patch(repository, tmp_path, {"pylock.toml": "x\n"})
    result, outputs = run_workflow_step(
        WORKFLOW,
        "validate",
        "⚙️ Record the validated patch digest",
        cwd=repository,
        runner_temp=tmp_path,
        values=values(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"sha256": hashlib.sha256(patch.read_bytes()).hexdigest()}


def test_writer_rejects_patch_that_differs_from_validated_digest(repository: Path, tmp_path: Path) -> None:
    make_patch(repository, tmp_path, {"pylock.toml": "x\n"})
    result, _ = run_workflow_step(
        WORKFLOW,
        "open",
        "🔍 Verify the validated patch digest",
        cwd=repository,
        runner_temp=tmp_path,
        values=values(tmp_path, **{"needs.validate.outputs.patch-sha256": "0" * 64}),
    )
    assert result.returncode != 0


def fake_gh(bin_dir: Path) -> Path:
    script = bin_dir / "gh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        '(IFS=$\'\\t\'; echo "$*") >>"$GH_LOG"\n'
        'case "$1" in\n'
        'api) cat "$FAKE_PULLS" ;;\n'
        'pr) if [[ "$2" == create ]]; then echo https://github.com/tox-dev/fixture/pull/21; fi ;;\n'
        "esac\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return bin_dir / "gh.log"


def pull(number: int, *, branch: str = "automation/maintenance", repo: str = "tox-dev/fixture") -> dict[str, object]:
    return {"number": number, "head": {"repo": {"full_name": repo}, "ref": branch}, "base": {"ref": "main"}}


def open_pull_request(
    repository: Path, tmp_path: Path, pulls: list[dict[str, object]], labels: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = fake_gh(bin_dir)
    pulls_file = tmp_path / "pulls.json"
    pulls_file.write_text(json.dumps(pulls))
    (tmp_path / "pull-request.md").write_text("Body.\n")
    result, outputs = run_workflow_step(
        WORKFLOW,
        "open",
        "🔀 Write maintenance pull request",
        cwd=repository,
        runner_temp=tmp_path,
        values=values(tmp_path, **{"inputs.labels": labels}),
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GH_LOG": str(log),
            "FAKE_PULLS": str(pulls_file),
        },
    )
    calls = [line for line in log.read_text().splitlines() if line.startswith("pr\t")] if log.exists() else []
    return result, outputs, calls


def test_existing_pull_request_is_updated(repository: Path, tmp_path: Path) -> None:
    result, outputs, calls = open_pull_request(
        repository, tmp_path, [pull(17, repo="attacker/fork"), pull(18)], "skip news\n\ndependencies\n"
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"number": "18"}
    body = str(tmp_path / "pull-request.md")
    assert calls == [
        (
            f"pr\tedit\t18\t--title\tMaintain things\t--body-file\t{body}"
            "\t--add-label\tskip news\t--add-label\tdependencies"
        )
    ]


def test_missing_pull_request_is_opened(repository: Path, tmp_path: Path) -> None:
    result, outputs, calls = open_pull_request(repository, tmp_path, [], "skip news\n")
    assert result.returncode == 0, result.stderr
    assert outputs == {"number": "21"}
    body = str(tmp_path / "pull-request.md")
    assert calls == [
        (
            f"pr\tcreate\t--base\tmain\t--head\tautomation/maintenance\t--title\tMaintain things"
            f"\t--body-file\t{body}\t--label\tskip news"
        )
    ]


def test_multiple_open_pull_requests_fail(repository: Path, tmp_path: Path) -> None:
    result, _, calls = open_pull_request(repository, tmp_path, [pull(18), pull(19)], "")
    assert result.returncode != 0
    assert "multiple maintenance pull requests" in result.stderr
    assert calls == []


def test_only_the_writer_holds_the_app_token() -> None:
    jobs = yaml.safe_load((WORKFLOWS / WORKFLOW).read_text())["jobs"]
    token_jobs = {
        name
        for name, job in jobs.items()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/create-github-app-token@")
    }
    assert token_jobs == {"open"}
    assert jobs["validate"]["permissions"] == {"contents": "read"}
    assert jobs["open"]["environment"] == "release-auth"
    assert jobs["open"]["needs"] == "validate"
    assert jobs["open"]["if"] == "needs.validate.result == 'success'"
    names = [step.get("name") for step in jobs["open"]["steps"]]
    assert names.index("🔑 Create release App token") > names.index(CHECK)
