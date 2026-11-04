from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final

import pytest
import yaml
from conftest import run, workflow_step

WORKFLOW: Final[str] = "publish-pre-commit-mirror.yaml"
ROOT: Final = Path(__file__).resolve().parents[2]
PREK_STUB: Final[str] = """\
#!/usr/bin/env bash
count=$(cat "$RUNNER_TEMP/prek-count" 2>/dev/null || echo 0)
echo $((count + 1)) >"$RUNNER_TEMP/prek-count"
read -r -a statuses <<<"$PREK_STATUSES"
exit "${statuses[count]}"
"""


def _workflow() -> dict[str, Any]:
    return yaml.load((ROOT / ".github/workflows" / WORKFLOW).read_text(), Loader=yaml.BaseLoader)


def _step(name: str) -> dict[str, Any]:
    return next(step for step in _workflow()["jobs"]["mirror"]["steps"] if step.get("name") == name)


@pytest.fixture
def prek_stub(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "uvx"
    script.write_text(PREK_STUB)
    script.chmod(0o755)
    return bin_dir


@pytest.mark.parametrize(
    ("statuses", "accepted", "invocations"),
    [
        pytest.param("0", True, 1, id="clean-tree"),
        pytest.param("1 0", True, 2, id="rewritten-then-clean"),
        pytest.param("1 1", False, 2, id="rewritten-then-failing"),
        pytest.param("2", False, 1, id="hook-crashed"),
    ],
)
def test_format_step_accepts_only_a_clean_second_pass(
    tmp_path: Path,
    prek_stub: Path,
    statuses: str,
    accepted: bool,
    invocations: int,
) -> None:
    result = workflow_step(
        WORKFLOW,
        "mirror",
        "💅 Format generated files",
        tmp_path,
        {
            "RUNNER_TEMP": str(tmp_path),
            "PREK_STATUSES": statuses,
            "PATH": f"{prek_stub}:{os.environ['PATH']}",
        },
    )
    assert (result.returncode == 0) is accepted, result.stderr
    assert (tmp_path / "prek-count").read_text().strip() == str(invocations)


def _repository(tmp_path: Path) -> Path:
    clone = tmp_path / "clone"
    run(tmp_path, "git", "init", "-q", "-b", "main", str(clone))
    run(clone, "git", "config", "user.name", "Mirror test")
    run(clone, "git", "config", "user.email", "mirror@example.org")
    (clone / ".version").write_text("1.0.0\n")
    (clone / "README.md").write_text('rev: "v0.0.0"\n')
    run(clone, "git", "add", ".")
    run(clone, "git", "commit", "-q", "-m", "Initial mirror")
    return clone


def test_commit_step_records_version_only_for_changes(tmp_path: Path) -> None:
    clone = _repository(tmp_path)
    output = tmp_path / "output"
    unchanged = workflow_step(WORKFLOW, "mirror", "🔄 Commit mirror changes", clone, {"GITHUB_OUTPUT": str(output)})
    assert unchanged.returncode == 0, unchanged.stderr
    assert not output.exists()

    (clone / ".version").write_text("1.0.1\n")
    changed = workflow_step(WORKFLOW, "mirror", "🔄 Commit mirror changes", clone, {"GITHUB_OUTPUT": str(output)})
    assert changed.returncode == 0, changed.stderr
    assert output.read_text() == "version=1.0.1\n"
    assert run(clone, "git", "log", "-1", "--format=%s").stdout.strip() == "Mirror: 1.0.1"


def _remote_with_tag(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    run(tmp_path, "git", "init", "-q", "--bare", str(remote))
    clone = _repository(tmp_path)
    run(clone, "git", "remote", "add", "origin", str(remote))
    run(clone, "git", "tag", "v1.0.0")
    run(clone, "git", "push", "-q", "origin", "main", "--tags")
    return remote, clone


@pytest.mark.parametrize(
    ("version", "accepted"),
    [
        pytest.param("1.0.0", False, id="published-tag"),
        pytest.param("1.0.1", True, id="new-tag"),
    ],
)
def test_tag_check_refuses_to_move_a_published_tag(tmp_path: Path, version: str, accepted: bool) -> None:
    _, clone = _remote_with_tag(tmp_path)
    result = workflow_step(
        WORKFLOW,
        "mirror",
        "🔍 Check the release tag is new",
        clone,
        {"VERSION": version},
    )
    assert (result.returncode == 0) is accepted, result.stderr


def test_push_step_publishes_branch_and_tag_together(tmp_path: Path) -> None:
    remote, clone = _remote_with_tag(tmp_path)
    (clone / ".version").write_text("1.0.1\n")
    run(clone, "git", "commit", "-q", "-am", "Mirror: 1.0.1")
    result = workflow_step(WORKFLOW, "mirror", "🚀 Push mirror commit and tag", clone, {"VERSION": "1.0.1"})
    assert result.returncode == 0, result.stderr
    head = run(clone, "git", "rev-parse", "HEAD").stdout.strip()
    assert run(tmp_path, "git", "--git-dir", str(remote), "rev-parse", "main").stdout.strip() == head
    assert run(tmp_path, "git", "--git-dir", str(remote), "rev-parse", "v1.0.1^{commit}").stdout.strip() == head


def test_push_is_atomic_and_never_forces() -> None:
    push = _step("🚀 Push mirror commit and tag")["run"]
    assert "--atomic" in push
    assert "--force" not in push
    assert " -f " not in push


def test_checkout_uses_default_credentials_without_token_in_remote() -> None:
    checkout = _step("📥 Check out repository")
    assert checkout["with"] == {"persist-credentials": "true"}
    text = (ROOT / ".github/workflows" / WORKFLOW).read_text()
    assert "set-url" not in text
    assert "x-access-token" not in text


def test_runs_pin_tools_and_never_interpolate_outputs() -> None:
    text = (ROOT / ".github/workflows" / WORKFLOW).read_text()
    assert "pre-commit-mirror-maker==1.14.0" in text
    assert "prek==0.5.5" in text
    assert 'version: "0.13.7"' in text
    for job in _workflow()["jobs"].values():
        for step in job["steps"]:
            script = step.get("run", "")
            assert "${{" not in script, step.get("name")
            assert "|| true" not in script, step.get("name")


def test_concurrency_queues_mirror_runs() -> None:
    assert _workflow()["concurrency"] == {
        "group": "pre-commit-mirror-${{ github.repository }}",
        "cancel-in-progress": "false",
    }


def test_release_steps_run_only_on_main_pushes() -> None:
    for name in ("🔍 Check the release tag is new", "🚀 Push mirror commit and tag", "🎉 Create GitHub release"):
        assert _step(name)["if"] == "${{ github.ref == 'refs/heads/main' && steps.commit.outputs.version != '' }}"
