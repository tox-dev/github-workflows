from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("workflow_name", ["prepare-release", "prepare-towncrier-release"])
def test_prepare_jobs_transfer_the_uploaded_patch(workflow_name: str) -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / f".github/workflows/{workflow_name}.yaml").read_text()
    )
    jobs = workflow["jobs"]
    assert jobs["assemble"]["outputs"]["artifact-id"] == "${{ steps.patch.outputs.artifact-id }}"
    assert (
        next(step for step in jobs["assemble"]["steps"] if step.get("id") == "patch")["with"]["name"] == "release-patch"
    )
    for job_name in ("validate", "push"):
        assert (
            next(step for step in jobs[job_name]["steps"] if "download-artifact" in step.get("uses", ""))["with"][
                "artifact-ids"
            ]
            == "${{ needs.assemble.outputs.artifact-id }}"
        )


def test_changelog_checkout_fetches_the_base_branch() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/check.yaml").read_text())
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
    assert notes["steps"][0]["with"]["fetch-depth"] == 0
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
