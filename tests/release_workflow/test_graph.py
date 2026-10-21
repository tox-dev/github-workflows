from __future__ import annotations

from pathlib import Path

import yaml


def test_release_writer_has_only_notes_and_reconciler() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/release.yaml").read_text())
    publish = workflow["jobs"]["publish"]
    assert publish["permissions"] == {"contents": "write"}
    assert publish["needs"] == ["source", "notes"]
    assert [step["uses"] for step in publish["steps"]] == [
        "actions/download-artifact@4a24838f3d5608b9bc57bc3f57db43f16310d098",
        "$/publish-github-release",
    ]
    assert publish["steps"][-1]["with"]["commit"] == "${{ needs.source.outputs.commit }}"


def test_release_notes_run_without_write_access() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/release.yaml").read_text())
    notes = workflow["jobs"]["notes"]
    assert notes["permissions"] == {"contents": "read"}
    assert "$/render-release-notes" in [step.get("uses") for step in notes["steps"]]


def test_release_contributors_job_has_no_checkout() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/release.yaml").read_text())
    contributors = workflow["jobs"]["contributors"]
    assert contributors["permissions"] == {"contents": "write"}
    assert not any("checkout" in step.get("uses", "") for step in contributors["steps"])
    assert not any("setup-uv" in step.get("uses", "") for step in contributors["steps"])
