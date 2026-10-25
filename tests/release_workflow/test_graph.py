from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def test_prepare_workflow_calls_reusable_preparation() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-release.yaml").read_text()
    )
    assert list(workflow["jobs"]) == ["prepare"]
    assert workflow["jobs"]["prepare"]["uses"] == "$/.github/workflows/prepare-towncrier-release.yaml"


def test_tagged_release_checks_the_committed_lock() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/release.yaml").read_text())
    assert "check" in workflow["jobs"]["publish"]["needs"]


def test_prepare_jobs_transfer_the_uploaded_patch() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text()
    )
    jobs = workflow["jobs"]
    assert list(jobs) == ["assemble", "validate", "push"]
    assert jobs["assemble"]["outputs"]["artifact-id"] == "${{ steps.patch.outputs.artifact-id }}"
    assert (
        next(step for step in jobs["assemble"]["steps"] if step.get("id") == "patch")["with"]["name"] == "release-patch"
    )
    for job in ("validate", "push"):
        assert (
            next(step for step in jobs[job]["steps"] if "download-artifact" in step.get("uses", ""))["with"][
                "artifact-ids"
            ]
            == "${{ needs.assemble.outputs.artifact-id }}"
        )


def test_prepare_validates_uploaded_patch_before_writer() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text()
    )
    jobs = workflow["jobs"]
    assert jobs["validate"]["permissions"] == {"contents": "read"}
    assert jobs["validate"]["needs"] == "assemble"
    assert jobs["push"]["needs"] == ["assemble", "validate"]
    assert not any(step.get("uses") == "$/validate-release-patch" for step in jobs["assemble"]["steps"])
    assert any(step.get("uses") == "$/validate-release-patch" for step in jobs["validate"]["steps"])
    assert (
        next(step for step in jobs["push"]["steps"] if step.get("uses") == "$/validate-release-patch")["with"]["checks"]
        == "false"
    )


@pytest.mark.parametrize(
    ("version", "prefix", "accepted"),
    [
        pytest.param("1.2.3", "", True, id="calculated-version"),
        pytest.param("v1.2.3", "v", True, id="prefixed-version"),
        pytest.param("9.9.9", "", False, id="forged-version"),
    ],
)
def test_prepare_validation_calculates_version_independently(
    tmp_path: Path, version: str, prefix: str, accepted: bool
) -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text()
    )
    steps = workflow["jobs"]["validate"]["steps"]
    verify = next(step for step in steps if step.get("name") == "Verify selected release version")
    command = tmp_path / "bin/release-creator"
    command.parent.mkdir()
    expected_arguments = ["tags", "--next", "auto", "--directory", "changelog.d"]
    if prefix:
        expected_arguments.extend(["--prefix", prefix])
    command.write_text(
        f"#!{sys.executable}\nimport sys\nassert sys.argv[1:] == {expected_arguments!r}\nprint({f'{prefix}1.2.3'!r})\n"
    )
    command.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", verify["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{command.parent}{os.pathsep}{os.environ['PATH']}",
            "BUMP": "auto",
            "TAG_PREFIX": prefix,
            "FRAGMENTS": "changelog.d",
            "VERSION": version,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode == 0) is accepted
    if not accepted:
        assert "assembled release version differs from 1.2.3" in result.stderr


@pytest.mark.parametrize("job", ["assemble", "validate"])
def test_prepare_builds_local_tool_with_locked_backends(job: str) -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text()
    )
    steps = workflow["jobs"][job]["steps"]
    builds = [step for step in steps if step.get("name") == "Build local release tool wheel"]
    assert len(builds) == 1
    assert builds[0]["env"]["BUILD_CONSTRAINTS"] == "${{ steps.tools.outputs.build-constraints }}"
    assert '--build-constraints "$BUILD_CONSTRAINTS"' in builds[0]["run"]
    assert "--require-build-hashes" in builds[0]["run"]
    assert any(
        step.get("name") == "Install local release tool wheel" and '"$RUNNER_TEMP/local-tool-dist/"*.whl' in step["run"]
        for step in steps
    )


def test_prepare_exposes_local_command_without_shadowing_python(tmp_path: Path) -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text()
    )
    steps = workflow["jobs"]["assemble"]["steps"]
    expose = next(step for step in steps if step.get("name") == "Expose local release command")
    assert expose["if"] == "inputs.local-tool-source"
    assert steps.index(expose) > next(
        index for index, step in enumerate(steps) if step.get("name") == "Install local release tool wheel"
    )
    assert steps.index(expose) < next(index for index, step in enumerate(steps) if step.get("id") == "prepare")
    command = tmp_path / ".venv/bin/release-creator"
    command.parent.mkdir(parents=True)
    command.symlink_to(sys.executable)
    output = tmp_path / "github-path"

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", expose["run"]],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_WORKSPACE": str(tmp_path), "RUNNER_TEMP": str(tmp_path), "GITHUB_PATH": str(output)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    overlay = Path(output.read_text().strip())
    assert (overlay / "release-creator").resolve() == command.resolve()
    assert not (overlay / "python").exists()
    assert (
        subprocess.run([str(overlay / "release-creator"), "--version"], check=False, capture_output=True).returncode
        == 0
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
    assert hooks["run"].splitlines()[-1] == "prek install-hooks --config .pre-commit-config.yaml"
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
