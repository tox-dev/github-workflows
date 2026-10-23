from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml


def test_prepare_workflow_calls_reusable_preparation() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-release.yaml").read_text()
    )
    assert list(workflow["jobs"]) == ["prepare"]
    assert workflow["jobs"]["prepare"]["uses"] == "$/.github/workflows/prepare-towncrier-release.yaml"


def test_prepare_jobs_transfer_the_uploaded_patch() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text()
    )
    jobs = workflow["jobs"]
    assert list(jobs) == ["assemble", "push"]
    assert jobs["assemble"]["outputs"]["artifact-id"] == "${{ steps.patch.outputs.artifact-id }}"
    assert (
        next(step for step in jobs["assemble"]["steps"] if step.get("id") == "patch")["with"]["name"] == "release-patch"
    )
    assert (
        next(step for step in jobs["push"]["steps"] if "download-artifact" in step.get("uses", ""))["with"][
            "artifact-ids"
        ]
        == "${{ needs.assemble.outputs.artifact-id }}"
    )


def test_prepare_validates_patch_in_fresh_worktree() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text()
    )
    steps = workflow["jobs"]["assemble"]["steps"]
    worktree = next(step for step in steps if step.get("name") == "Create a fresh validation worktree")
    validation = next(step for step in steps if step.get("uses") == "$/validate-release-patch")
    assert "git worktree add --detach" in worktree["run"]
    assert validation["with"]["working-directory"] == "${{ runner.temp }}/release-validation"
    assert (
        steps.index(worktree)
        < steps.index(validation)
        < next(index for index, step in enumerate(steps) if step.get("id") == "patch")
    )


def test_prepare_builds_local_tool_once_with_locked_backends() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text()
    )
    steps = workflow["jobs"]["assemble"]["steps"]
    builds = [step for step in steps if step.get("name") == "Build local release tool wheel"]
    assert len(builds) == 1
    assert builds[0]["env"]["BUILD_CONSTRAINTS"] == "${{ steps.tools.outputs.build-constraints }}"
    assert '--build-constraints "$BUILD_CONSTRAINTS"' in builds[0]["run"]
    assert "--require-build-hashes" in builds[0]["run"]
    assert any(
        step.get("name") == "Install local release tool wheel" and '"$RUNNER_TEMP/local-tool-dist/"*.whl' in step["run"]
        for step in steps
    )


def test_prepare_installs_hooks_while_building_changelog() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text()
    )
    steps = workflow["jobs"]["assemble"]["steps"]
    hooks = next(step for step in steps if step.get("id") == "hooks")
    build = next(step for step in steps if step.get("id") == "prepare")
    wait = next(step for step in steps if step.get("wait") == "hooks")
    finalize = next(step for step in steps if step.get("name") == "Finalize release patch")
    assert hooks["background"] is True
    assert hooks["run"] == "prek install-hooks"
    assert [build["with"]["phase"], finalize["with"]["phase"]] == ["build", "finalize"]
    assert steps.index(hooks) < steps.index(build) < steps.index(wait) < steps.index(finalize)


def test_changelog_checkout_fetches_the_base_branch() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/news.yaml").read_text())
    checkout = next(step for step in workflow["jobs"]["changelog"]["steps"] if "checkout" in step.get("uses", ""))
    assert checkout["with"]["fetch-depth"] == 0


def test_release_writer_has_only_notes_and_reconciler() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/release.yaml").read_text())
    publish = workflow["jobs"]["publish"]
    assert publish["permissions"] == {"contents": "write"}
    assert publish["needs"] == ["check", "source", "notes"]
    assert [step["uses"] for step in publish["steps"]] == [
        "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
        "$/publish-github-release",
    ]
    assert publish["steps"][-1]["with"]["commit"] == "${{ needs.source.outputs.commit }}"
    assert publish["steps"][0]["with"]["artifact-ids"] == "${{ needs.notes.outputs.artifact-id }}"


def test_release_notes_run_without_write_access() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/release.yaml").read_text())
    notes = workflow["jobs"]["notes"]
    assert notes["permissions"] == {"contents": "read"}
    assert notes["steps"][0]["with"]["fetch-depth"] == 1
    assert "$/render-release-notes" in [step.get("uses") for step in notes["steps"]]
    assert notes["outputs"]["artifact-id"] == "${{ steps.artifact.outputs.artifact-id }}"
    assert (
        next(step for step in notes["steps"] if "download-artifact" in step.get("uses", ""))["with"]["artifact-ids"]
        == "${{ needs.contributors.outputs.artifact-id }}"
    )


def test_release_contributors_job_has_no_checkout() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/release.yaml").read_text())
    contributors = workflow["jobs"]["contributors"]
    assert contributors["permissions"] == {"contents": "write"}
    assert not any("checkout" in step.get("uses", "") for step in contributors["steps"])
    assert not any("setup-uv" in step.get("uses", "") for step in contributors["steps"])


def test_release_contributors_job_uploads_generated_notes() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/release.yaml").read_text())
    contributors = workflow["jobs"]["contributors"]
    assert contributors["steps"][0]["name"] == "Fetch contributor metadata"
    assert "releases/generate-notes" in contributors["steps"][0]["run"]
    assert contributors["steps"][1]["with"]["path"] == "${{ runner.temp }}/generated-notes.md"
    assert contributors["outputs"]["artifact-id"] == "${{ steps.artifact.outputs.artifact-id }}"


def test_shfmt_hook_rejects_unformatted_inline_shell(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    script = tmp_path / "inline-shell-check.sh"
    script.write_text("#!/usr/bin/env bash\nif true\nthen\necho x\nfi\n")
    executable = shutil.which("prek")
    assert executable is not None
    result = subprocess.run(
        [
            executable,
            "run",
            "shfmt",
            "--config",
            str(Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"),
            "--files",
            str(script),
        ],
        cwd=tmp_path,
        env={name: os.environ[name] for name in ("HOME", "PATH")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "diff" in result.stdout


def test_action_manifests_have_no_empty_environment_mapping() -> None:
    root = Path(__file__).resolve().parents[2]
    for path in root.glob("*/action.yml"):
        action = yaml.safe_load(path.read_text())
        assert all("env" not in step or isinstance(step["env"], dict) for step in action["runs"]["steps"]), path
