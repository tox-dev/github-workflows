from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> dict[str, Any]:
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def _steps(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step["name"]: step for step in job["steps"]}


def test_release_notes_exposes_inputs_and_artifact_id() -> None:
    workflow = _workflow("release-notes.yaml")
    call = workflow["on"]["workflow_call"]

    assert {name: definition.get("required") for name, definition in call["inputs"].items()} == {
        "tag": "true",
        "changelog": None,
        "artifact-url": None,
        "artifact-label": None,
        "package": None,
    }
    assert call["outputs"]["artifact-id"]["value"] == "${{ jobs.notes.outputs.artifact-id }}"
    assert workflow["permissions"] == {}
    assert workflow["jobs"]["notes"]["permissions"] == {"contents": "read"}


def test_release_notes_render_without_a_separate_previous_tag_step() -> None:
    steps = _steps(_workflow("release-notes.yaml")["jobs"]["notes"])

    assert list(steps) == [
        "📥 Check out repository",
        "🐍 Install uv and Python",
        "⚙️ Read Towncrier configuration",
        "📦 Install locked release tools",
        "📝 Render release notes",
        "📤 Upload release notes",
    ]
    assert all("select-previous-tag" not in step.get("uses", "") for step in steps.values())


def test_release_notes_default_changelog_comes_from_towncrier_config() -> None:
    steps = _steps(_workflow("release-notes.yaml")["jobs"]["notes"])

    assert steps["📝 Render release notes"]["with"] == {
        "tag": "${{ inputs.tag }}",
        "changelog": "${{ inputs.changelog || steps.towncrier.outputs.changelog }}",
        "artifact-url": "${{ inputs.artifact-url }}",
        "artifact-label": "${{ inputs.artifact-label }}",
        "package": "${{ inputs.package }}",
    }


def test_release_notes_uploads_artifact_per_run_attempt() -> None:
    upload = _steps(_workflow("release-notes.yaml")["jobs"]["notes"])["📤 Upload release notes"]

    assert upload["with"]["name"] == "github-release-notes-${{ github.run_attempt }}"
    assert upload["with"]["if-no-files-found"] == "error"


@pytest.mark.parametrize("path", sorted((ROOT / ".github/workflows").glob("*.y*ml")), ids=lambda path: path.name)
def test_local_action_references_resolve(path: Path) -> None:
    references = [line.split("uses: $/", 1)[1].strip() for line in path.read_text().splitlines() if "uses: $/" in line]

    assert all((ROOT / reference / "action.yml").is_file() or (ROOT / reference).is_file() for reference in references)
