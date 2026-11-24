import hashlib
import json
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from conftest import WORKFLOWS, JsonObject, at, load_yaml, mapping, run, run_workflow_step, steps, text

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Mapping

_WORKFLOW: Final[str] = "open-maintenance-pr.yaml"
_CHECK: Final[str] = "🔍 Check patch paths and modes"
_ALLOWED: Final[str] = "pylock.toml\npyproject.toml\ndiagrams/*.svg\n"


@pytest.fixture
def workflow() -> JsonObject:
    return load_yaml(WORKFLOWS / _WORKFLOW)


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
    assert (result.returncode == 0) is accepted, result.stderr


def make_patch(repo: Path, tmp_path: Path, change: Mapping[str, str | None], *, mode: int | None = None) -> Path:
    for path, content in change.items():
        target = repo / path
        if content is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        if mode is not None:
            target.chmod(mode)
    return stage_patch(repo, tmp_path)


def stage_patch(repo: Path, tmp_path: Path) -> Path:
    run(repo, "git", "add", "-A")
    patch = tmp_path / "maintenance-patch" / "maintenance.patch"
    patch.parent.mkdir(exist_ok=True)
    patch.write_text(run(repo, "git", "diff", "--cached", "--binary", "--no-renames").stdout)
    run(repo, "git", "reset", "-q", "--hard", "HEAD")
    run(repo, "git", "clean", "-fdq")
    return patch


def check_patch(repo: Path, tmp_path: Path, allowed: str = _ALLOWED) -> subprocess.CompletedProcess[str]:
    for name in ("⚙️ Apply maintenance patch to a scratch index", _CHECK):
        result, _ = run_workflow_step(
            _WORKFLOW, "validate", name, cwd=repo, runner_temp=tmp_path, values=values(tmp_path, allowed), env={}
        )
        if result.returncode:
            return result
    return result


def values(tmp_path: Path, allowed: str = _ALLOWED, **extra: str) -> dict[str, str]:
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


def test_check_reports_a_disallowed_change_as_an_error(repository: Path, tmp_path: Path) -> None:
    make_patch(repository, tmp_path, {"docs/readme.md": "changed\n"})
    result = check_patch(repository, tmp_path)
    assert "::error::" in result.stderr


def test_check_rejects_symlink_replacing_a_regular_file(repository: Path, tmp_path: Path) -> None:
    (repository / "pylock.toml").unlink()
    (repository / "pylock.toml").symlink_to("pyproject.toml")
    stage_patch(repository, tmp_path)
    result = check_patch(repository, tmp_path)
    assert result.returncode != 0
    assert "unexpected maintenance path status T for pylock.toml" in result.stderr


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


def test_writer_trusts_the_validated_digest(workflow: JsonObject) -> None:
    assert _CHECK not in [item.get("name") for item in steps(workflow, "open")]


def test_digest_step_records_sha256(repository: Path, tmp_path: Path) -> None:
    patch = make_patch(repository, tmp_path, {"pylock.toml": "x\n"})
    result, outputs = run_workflow_step(
        _WORKFLOW,
        "validate",
        "⚙️ Record the validated patch digest",
        cwd=repository,
        runner_temp=tmp_path,
        values=values(tmp_path),
        env={},
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"sha256": hashlib.sha256(patch.read_bytes()).hexdigest()}


def test_writer_rejects_patch_that_differs_from_validated_digest(repository: Path, tmp_path: Path) -> None:
    make_patch(repository, tmp_path, {"pylock.toml": "x\n"})
    result, _ = run_workflow_step(
        _WORKFLOW,
        "open",
        "🔍 Verify the validated patch digest",
        cwd=repository,
        runner_temp=tmp_path,
        values=values(tmp_path, **{"needs.validate.outputs.patch-sha256": "0" * 64}),
        env={},
    )
    assert result.returncode != 0


@pytest.mark.parametrize(
    ("checkout", "returncode", "diagnostic", "output_keys"),
    [
        pytest.param(("-b", "next"), 0, "", ("sha",), id="advanced"),
        pytest.param(("--orphan", "replacement"), 1, "no longer in the target branch", (), id="rewritten"),
    ],
)
def test_validate_selects_the_current_target(
    repository: Path,
    tmp_path: Path,
    checkout: tuple[str, str],
    returncode: int,
    diagnostic: str,
    output_keys: tuple[str, ...],
) -> None:
    source = run(repository, "git", "rev-parse", "HEAD").stdout.strip()
    run(repository, "git", "checkout", *checkout)
    run(repository, "git", "commit", "--allow-empty", "-m", "Advance base")
    result, outputs = run_workflow_step(
        _WORKFLOW,
        "validate",
        "🔍 Verify the patch source is in the target branch",
        cwd=repository,
        runner_temp=tmp_path,
        values={"github.sha": source},
        env={},
    )
    assert result.returncode == returncode, result.stderr
    assert diagnostic in result.stderr
    assert outputs == dict.fromkeys(output_keys, run(repository, "git", "rev-parse", "HEAD").stdout.strip())


@pytest.mark.parametrize(
    ("target", "returncode", "diagnostic", "published"),
    [
        pytest.param(
            "HEAD^", 0, "Pushing automation/maintenance", "{commit}\trefs/heads/automation/maintenance\n", id="current"
        ),
        pytest.param("HEAD", 1, "target branch advanced", "", id="advanced"),
    ],
)
def test_push_requires_the_validated_target(
    repository: Path, tmp_path: Path, target: str, returncode: int, diagnostic: str, published: str
) -> None:
    remote = tmp_path / "remote.git"
    run(repository, "git", "clone", "--bare", ".", str(remote))
    run(repository, "git", "remote", "add", "origin", str(remote))
    run(repository, "git", "switch", "-c", "maintenance")
    (repository / "pylock.toml").write_text("lock-version = '2.0'\n")
    run(repository, "git", "commit", "-am", "Update lock")
    run(repository, "git", "push", "origin", f"{target}:refs/heads/main")
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\nexit 0\n")
    gh.chmod(stat.S_IRWXU)
    result, _ = run_workflow_step(
        _WORKFLOW,
        "open",
        "⬆️ Push maintenance branch",
        cwd=repository,
        runner_temp=tmp_path,
        values={"inputs.base": "main", "inputs.branch": "automation/maintenance"},
        env={"GH_TOKEN": "", "PATH": f"{tmp_path}:{os.environ['PATH']}"},
    )
    remote_branch = run(repository, "git", "ls-remote", "origin", "refs/heads/automation/maintenance").stdout
    assert result.returncode == returncode, result.stderr
    assert diagnostic in result.stdout + result.stderr
    commit = run(repository, "git", "rev-parse", "HEAD").stdout.strip()
    assert remote_branch == published.format(commit=commit)


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


def pull(number: int, *, branch: str = "automation/maintenance", repo: str = "tox-dev/fixture") -> JsonObject:
    return {"number": number, "head": {"repo": {"full_name": repo}, "ref": branch}, "base": {"ref": "main"}}


def open_pull_request(
    repository: Path, tmp_path: Path, pulls: list[JsonObject], labels: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = fake_gh(bin_dir)
    pulls_file = tmp_path / "pulls.json"
    pulls_file.write_text(json.dumps(pulls))
    (tmp_path / "pull-request.md").write_text("Body.\n")
    result, outputs = run_workflow_step(
        _WORKFLOW,
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


def test_only_the_writer_holds_the_app_token(workflow: JsonObject) -> None:
    assert {
        name
        for name in mapping(at(workflow, "jobs"))
        for item in steps(workflow, name)
        if text(item.get("uses", "")).startswith("actions/create-github-app-token@")
    } == {"open"}


def test_validate_job_is_read_only(workflow: JsonObject) -> None:
    assert at(workflow, "jobs", "validate", "permissions") == {"contents": "read"}


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        pytest.param("environment", "release-auth", id="environment"),
        pytest.param("needs", "validate", id="needs"),
        pytest.param("if", "needs.validate.result == 'success'", id="if"),
    ],
)
def test_open_job_is_gated_on_a_clean_validation(workflow: JsonObject, key: str, expected: str) -> None:
    assert at(workflow, "jobs", "open", key) == expected


def test_app_token_is_minted_after_the_digest_is_verified(workflow: JsonObject) -> None:
    names = [item.get("name") for item in steps(workflow, "open")]
    assert names.index("🔑 Create release App token") > names.index("🔍 Verify the validated patch digest")
    assert names.index("🔒 Apply maintenance patch") > names.index("🔍 Verify the validated patch digest")


def test_body_step_writes_the_requested_pull_request_body(repository: Path, tmp_path: Path) -> None:
    result, _ = run_workflow_step(
        _WORKFLOW,
        "open",
        "📝 Write maintenance pull request body",
        cwd=repository,
        runner_temp=tmp_path,
        values=values(tmp_path, **{"inputs.body": "Refresh release tools."}),
        env={},
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "pull-request.md").read_text() == "Refresh release tools.\n"
