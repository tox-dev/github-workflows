import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        pytest.param(["1", "path"], "1 path", id="singular"),
        pytest.param(["2", "path"], "2 paths", id="regular-plural"),
        pytest.param(["0", "entry", "entries"], "0 entries", id="irregular-plural"),
    ],
)
def test_plural_prints_count_and_noun(arguments: list[str], expected: str) -> None:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "tools/plural.py"), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode, result.stdout) == (0, expected)


def test_plural_requires_arguments() -> None:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "tools/plural.py")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "usage: plural.py" in result.stderr
