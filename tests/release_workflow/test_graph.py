from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml


def test_release_writer_has_only_notes_and_reconciler() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/release.yaml").read_text())
    publish = workflow["jobs"]["publish"]
    assert publish["permissions"] == {"contents": "write"}
    assert publish["needs"] == "notes"
    assert [step.get("uses", step.get("name")) for step in publish["steps"]] == [
        "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
        "$/publish-github-release",
    ]
    assert publish["steps"][-1]["with"]["commit"] == "${{ github.sha }}"
    assert publish["steps"][0]["with"]["artifact-ids"] == "${{ needs.notes.outputs.artifact-id }}"


def test_shfmt_hook_rejects_unformatted_inline_shell(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    script = tmp_path / "inline-shell-check.sh"
    script.write_text("#!/usr/bin/env bash\nif true\nthen\necho x\nfi\n")
    tools = Path(__file__).resolve().parents[2] / ".release-tools/bin"
    executable = shutil.which("prek", path=f"{tools}{os.pathsep}{os.environ['PATH']}")
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


def test_release_notes_render_read_only_from_full_history() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/release.yaml").read_text())
    notes = workflow["jobs"]["notes"]
    checkout = next(step for step in notes["steps"] if "checkout" in step.get("uses", ""))

    assert notes["permissions"] == {"contents": "read"}
    assert "needs" not in notes
    assert checkout["with"]["fetch-depth"] == 0
    assert set(workflow["jobs"]) == {"notes", "publish"}
