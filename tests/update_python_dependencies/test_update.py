from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from conftest import WORKFLOWS, run, run_workflow_step, workflow_env

if TYPE_CHECKING:
    import subprocess

WORKFLOW = "update-python-dependencies.yaml"
INPUTS = "⚙️ Validate inputs and set the cutoffs"
BUMP = "📦 Bump dependency floors"
PATCH = "📝 Write maintenance patch"
TIMESTAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
DEFAULTS = {
    "inputs.allowed-paths": "docs/*.md",
    "inputs.cooldown": "7 days",
    "inputs.exclude-newer": "7 days",
    "inputs.exclude-newer-package": "",
    "inputs.expedite": "",
    "inputs.files": "pyproject.toml tox.toml",
    "inputs.fresh-groups": "project test",
    "inputs.kind": "app",
}


def validate(
    repository: Path, tmp_path: Path, **inputs: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    values = DEFAULTS | {f"inputs.{key.replace('_', '-')}": value for key, value in inputs.items()}
    return run_workflow_step(
        WORKFLOW,
        "generate",
        INPUTS,
        cwd=repository,
        runner_temp=tmp_path,
        values=values,
        env={"ALLOWED_EXTRA": values["inputs.allowed-paths"]},
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repository"
    repo.mkdir()
    run(repo, "git", "init", "-b", "main")
    run(repo, "git", "config", "user.name", "Release test")
    run(repo, "git", "config", "user.email", "release@example.org")
    (repo / "pylock.toml").write_text("lock-version = '1.0'\n")
    (repo / "pyproject.toml").write_text('[project]\nname = "example"\n')
    run(repo, "git", "add", ".")
    run(repo, "git", "commit", "-m", "Initial files")
    return repo


def test_defaults_build_cutoffs_groups_and_allowed_paths(repository: Path, tmp_path: Path) -> None:
    result, outputs = validate(repository, tmp_path, expedite="release-creator\nnab", files="pyproject.toml tox.toml\n")
    assert result.returncode == 0, result.stderr
    assert re.fullmatch(TIMESTAMP, outputs["cutoff"])
    assert outputs["allowed-paths"].splitlines() == ["pylock.toml", "pyproject.toml", "tox.toml", "docs/*.md"]
    assert (tmp_path / "expedite").read_text() == "release-creator\nnab\n"
    assert (tmp_path / "file-groups").read_text() == "pyproject.toml tox.toml\n"
    assert (tmp_path / "fresh-groups").read_text() == ""


def test_library_keeps_fresh_groups_and_app_keeps_none(repository: Path, tmp_path: Path) -> None:
    result, _ = validate(repository, tmp_path, kind="library", fresh_groups="project\ntest")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "fresh-groups").read_text() == "project\ntest\n"


def test_zero_days_turns_the_bump_cooldown_off(repository: Path, tmp_path: Path) -> None:
    result, outputs = validate(repository, tmp_path, cooldown="0 days")
    assert result.returncode == 0, result.stderr
    assert outputs["cutoff"] == "none"


def test_empty_extra_paths_add_no_pattern(repository: Path, tmp_path: Path) -> None:
    result, outputs = validate(repository, tmp_path, **{"allowed-paths": ""})
    assert result.returncode == 0, result.stderr
    assert outputs["allowed-paths"].splitlines() == ["pylock.toml", "pyproject.toml", "tox.toml"]


@pytest.mark.parametrize(
    ("options", "message"),
    [
        pytest.param({"kind": "tool"}, "kind must be app or library", id="unknown-kind"),
        pytest.param({"cooldown": "P7D"}, "cooldown must be N days", id="iso-duration"),
        pytest.param({"cooldown": "7 weeks"}, "cooldown must be N days", id="weeks"),
        pytest.param({"expedite": "bad name!"}, "is not a package name", id="expedite-name"),
        pytest.param({"kind": "library", "fresh_groups": "bad group!"}, "is not a dependency group", id="group-name"),
        pytest.param({"kind": "library", "fresh_groups": ""}, "needs at least one fresh-groups", id="no-groups"),
        pytest.param({"files": "../pyproject.toml"}, "is not a plain relative path", id="parent-path"),
        pytest.param({"files": "/etc/pyproject.toml"}, "is not a plain relative path", id="absolute-path"),
        pytest.param({"files": "a*.toml"}, "is not a plain relative path", id="glob-path"),
        pytest.param({"files": "\n\n"}, "lists no dependency file", id="no-files"),
    ],
)
def test_rejects_invalid_inputs(repository: Path, tmp_path: Path, options: dict[str, str], message: str) -> None:
    result, _ = validate(repository, tmp_path, **options)
    assert result.returncode != 0
    assert message in result.stderr


def fake_uvx(bin_dir: Path) -> Path:
    script = bin_dir / "uvx"
    script.write_text('#!/usr/bin/env bash\n(IFS=$\'\\t\'; echo "$*") >>"$UVX_LOG"\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return bin_dir / "uvx.log"


def bump(
    repository: Path, tmp_path: Path, outputs: dict[str, str], **inputs: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = fake_uvx(bin_dir)
    values = DEFAULTS | {"steps.inputs.outputs.cutoff": outputs["cutoff"]}
    values |= {f"inputs.{key.replace('_', '-')}": value for key, value in inputs.items()}
    result, _ = run_workflow_step(
        WORKFLOW,
        "generate",
        BUMP,
        cwd=repository,
        runner_temp=tmp_path,
        values=values,
        env={"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "UVX_LOG": str(log)},
    )
    return result, log.read_text().splitlines() if log.exists() else []


def test_bump_runs_each_group_with_expedite(repository: Path, tmp_path: Path) -> None:
    result, outputs = validate(
        repository, tmp_path, expedite="release-creator", files="pyproject.toml tox.toml\ndocs/a.toml"
    )
    assert result.returncode == 0, result.stderr
    result, calls = bump(repository, tmp_path, outputs)
    assert result.returncode == 0, result.stderr
    prefix = ["--exclude-newer", "7 days", "bump-deps-index>=1.19", "--exclude-newer", outputs["cutoff"]]
    assert calls == [
        "\t".join(
            [*prefix, "--exclude-newer-package", "release-creator=false", "--file", "pyproject.toml", "tox.toml"]
        ),
        "\t".join([*prefix, "--exclude-newer-package", "release-creator=false", "--file", "docs/a.toml"]),
    ]


def test_tool_install_takes_the_exclude_newer_inputs(repository: Path, tmp_path: Path) -> None:
    result, outputs = validate(repository, tmp_path, cooldown="0 days")
    assert result.returncode == 0, result.stderr
    result, calls = bump(
        repository,
        tmp_path,
        outputs,
        exclude_newer="2026-10-01T00:00:00Z",
        exclude_newer_package="bump-deps-index=2026-11-01T00:00:00Z",
    )
    assert result.returncode == 0, result.stderr
    assert calls == [
        "--exclude-newer\t2026-10-01T00:00:00Z\t--exclude-newer-package\tbump-deps-index=2026-11-01T00:00:00Z\tbump-deps-index>=1.19\t--no-exclude-newer\t--file\tpyproject.toml\ttox.toml"
    ]


def test_library_bump_keeps_fresh_groups_fresh(repository: Path, tmp_path: Path) -> None:
    result, outputs = validate(repository, tmp_path, kind="library")
    assert result.returncode == 0, result.stderr
    result, calls = bump(repository, tmp_path, outputs)
    assert result.returncode == 0, result.stderr
    assert calls == [
        "\t".join(
            [
                "--exclude-newer",
                "7 days",
                "bump-deps-index>=1.19",
                "--exclude-newer",
                outputs["cutoff"],
                "--exclude-newer-group",
                "project=false",
                "--exclude-newer-group",
                "test=false",
                "--file",
                "pyproject.toml",
                "tox.toml",
            ]
        )
    ]


def test_bump_without_cooldown_passes_no_cutoff(repository: Path, tmp_path: Path) -> None:
    result, outputs = validate(repository, tmp_path, cooldown="0 days")
    assert result.returncode == 0, result.stderr
    result, calls = bump(repository, tmp_path, outputs)
    assert result.returncode == 0, result.stderr
    assert calls[0].split("\t")[-4:] == ["--no-exclude-newer", "--file", "pyproject.toml", "tox.toml"]
    assert len(calls) == 1


def test_bump_uses_the_workflow_requirement_constant() -> None:
    assert workflow_env(WORKFLOW) == {"BUMP_DEPS_INDEX": "bump-deps-index>=1.19"}


def test_patch_step_reports_no_change(repository: Path, tmp_path: Path) -> None:
    result, outputs = run_workflow_step(
        WORKFLOW, "generate", PATCH, cwd=repository, runner_temp=tmp_path, values=DEFAULTS
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"changed": "false"}
    assert not (tmp_path / "maintenance.patch").exists()


def test_patch_step_writes_every_change_including_new_files(repository: Path, tmp_path: Path) -> None:
    (repository / "pylock.toml").write_text("lock-version = '2.0'\n")
    (repository / "docs").mkdir()
    (repository / "docs/new.md").write_text("New.\n")
    result, outputs = run_workflow_step(
        WORKFLOW, "generate", PATCH, cwd=repository, runner_temp=tmp_path, values=DEFAULTS
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"changed": "true"}
    patch = (tmp_path / "maintenance.patch").read_text()
    assert "diff --git a/pylock.toml b/pylock.toml" in patch
    assert "diff --git a/docs/new.md b/docs/new.md" in patch


def test_generate_is_read_only_and_hands_off_to_the_writer() -> None:
    jobs = yaml.safe_load((WORKFLOWS / WORKFLOW).read_text())["jobs"]
    assert jobs["generate"]["permissions"] == {"contents": "read"}
    assert jobs["open"]["needs"] == "generate"
    assert jobs["open"]["if"] == "needs.generate.outputs.changed == 'true'"
    assert jobs["open"]["uses"] == "$/.github/workflows/open-maintenance-pr.yaml"
    assert jobs["open"]["secrets"] == {"RELEASE_APP_PRIVATE_KEY": "${{ secrets.RELEASE_APP_PRIVATE_KEY }}"}


def test_uses_are_pinned_or_local_and_no_cargo_or_uv_lock() -> None:
    text = (WORKFLOWS / WORKFLOW).read_text()
    for reference in re.findall(r"uses: (\S+)", text):
        assert reference.startswith("$/") or re.search(r"@[0-9a-f]{40}$", reference), reference
    assert "peter-evans" not in text
    assert "uv lock" not in text
    assert "cargo" not in text
