from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> dict[str, Any]:
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def _steps(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step["name"]: step for step in job["steps"]}


def test_github_release_publishes_from_a_release_environment_only() -> None:
    workflow = _workflow("github-release.yaml")
    job = workflow["jobs"]["github-release"]

    assert job["environment"] == "release"
    assert job["permissions"] == {"contents": "write"}
    assert workflow["permissions"] == {}


def test_github_release_verifies_pypi_before_publishing() -> None:
    steps = _steps(_workflow("github-release.yaml")["jobs"]["github-release"])

    assert list(steps) == [
        "🐍 Install uv and Python",
        "📩 Download distributions",
        "📩 Download release notes",
        "🔍 Verify PyPI artifacts",
        "🚀 Publish GitHub release",
    ]
    assert steps["🔍 Verify PyPI artifacts"]["with"] == {
        "project": "${{ inputs.project }}",
        "version": "${{ inputs.version }}",
        "dist": "dist",
    }


def test_github_release_title_prefixes_the_tag() -> None:
    publish = _steps(_workflow("github-release.yaml")["jobs"]["github-release"])["🚀 Publish GitHub release"]

    assert publish["with"] == {
        "tag": "${{ inputs.tag }}",
        "commit": "${{ github.sha }}",
        "title": "${{ inputs.title-prefix }}${{ inputs.tag }}",
        "notes-file": "${{ runner.temp }}/release-notes.md",
        "assets-directory": "${{ inputs.assets-directory }}",
    }
