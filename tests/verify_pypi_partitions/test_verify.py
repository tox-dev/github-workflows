from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def verify(tmp_path: Path, action_scripts: Path, names: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("alpha.whl\nbeta.whl\n")
    partitions = tmp_path / "partitions"
    partitions.mkdir()
    for index, name in enumerate(names):
        (partitions / f"{index}.txt").write_text(name)
    return subprocess.run(
        ["bash", str(action_scripts / "verify-pypi-partitions-0.sh")],
        cwd=tmp_path,
        env=os.environ
        | {
            "MANIFEST": str(manifest),
            "PARTITIONS_DIR": str(partitions),
            "EXPECTED_PARTITIONS": "2",
            "RUNNER_TEMP": str(tmp_path),
        },
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("names", "accepted"),
    [
        pytest.param(("alpha.whl\n", "beta.whl\n"), True, id="complete"),
        pytest.param(("alpha.whl\n", "alpha.whl\n"), False, id="duplicate-missing"),
        pytest.param(("alpha.whl\n", ""), False, id="missing"),
        pytest.param(("alpha.whl\n", "beta.whl\nextra.whl\n"), False, id="extra"),
    ],
)
def test_verify_partitions_requires_exact_unique_union(
    tmp_path: Path, action_scripts: Path, names: tuple[str, ...], accepted: bool
) -> None:
    result = verify(tmp_path, action_scripts, names)
    assert (result.returncode == 0) is accepted
