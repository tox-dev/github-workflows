from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(
    ("failed_result", "accepted"),
    [
        pytest.param(None, True, id="all-succeeded"),
        pytest.param("skipped", False, id="skipped-job"),
        pytest.param("failure", False, id="failed-job"),
    ],
)
def test_required_gate_requires_every_job_to_succeed(failed_result: str | None, accepted: bool) -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/check.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    names = workflow["jobs"]["gate"]["needs"]
    needs = {name: {"result": "success"} for name in names}
    if failed_result is not None:
        needs[names[-1]] = {"result": failed_result}
    result = subprocess.run(
        ["bash", "-c", workflow["jobs"]["gate"]["steps"][0]["run"]],
        env=os.environ | {"NEEDS_JSON": json.dumps(needs)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, result.stderr


def test_required_gate_does_not_repeat_changelog_lock_check() -> None:
    root = Path(__file__).resolve().parents[2]
    check = yaml.load((root / ".github/workflows/check.yaml").read_text(), Loader=yaml.BaseLoader)
    news = yaml.load((root / ".github/workflows/news.yaml").read_text(), Loader=yaml.BaseLoader)

    assert "release-tools-preview" not in check["jobs"]
    assert check["jobs"]["gate"]["needs"] == ["check", "shell", "test", "type"]
    assert news["jobs"]["changelog"]["steps"][-1]["uses"] == "$/validate-news"
