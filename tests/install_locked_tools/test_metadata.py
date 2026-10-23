from __future__ import annotations

import json
import runpy
import sys
from io import BytesIO
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from pytest_mock import MockerFixture


@pytest.fixture
def lock_case(tmp_path: Path) -> tuple[Path, Path]:
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        dedent(
            """\
            lock-version = "1.0"
            requires-python = ">=3.15"
            dependency-groups = ["release-check"]
            created-by = "test"
            [tool.nab]
            created-at = 2026-10-20T00:00:00Z
            [[packages]]
            name = "six"
            version = "1.16.0"
            marker = '"release-check" in dependency_groups'
            index = "https://pypi.org/simple/"
            [[packages.wheels]]
            name = "six-1.16.0-py2.py3-none-any.whl"
            url = "https://files.pythonhosted.org/packages/d9/5a/e7c31adbe875f2abbb91bd84cf2dc52d792b5a01506781dbcf25c91daf11/six-1.16.0-py2.py3-none-any.whl"
            upload-time = 2021-05-05T14:18:17.237677Z
            hashes.sha256 = "8abb2f1d86890a2dfb989f9a77cfcfd3e47c2a354b01111771326f8aa26e0254"
            """
        )
    )
    project = tmp_path / "pyproject.toml"
    project.write_text('[tool.nab]\nuploaded-prior-to = "P7D"\n')
    return lock, project


@pytest.fixture
def pypi_listing() -> dict[str, Any]:
    return {
        "meta": {"api-version": "1.4"},
        "name": "six",
        "files": [
            {
                "filename": "six-1.16.0-py2.py3-none-any.whl",
                "url": "https://files.pythonhosted.org/packages/d9/5a/e7c31adbe875f2abbb91bd84cf2dc52d792b5a01506781dbcf25c91daf11/six-1.16.0-py2.py3-none-any.whl",
                "upload-time": "2021-05-05T14:18:17.237677Z",
                "hashes": {"sha256": "8abb2f1d86890a2dfb989f9a77cfcfd3e47c2a354b01111771326f8aa26e0254"},
            }
        ],
    }


def test_lock_metadata_matches_pypi(
    lock_case: tuple[Path, Path], pypi_listing: dict[str, Any], mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = mocker.patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(pypi_listing).encode()))

    _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert request.call_args.args[0].full_url == "https://pypi.org/simple/six/"


@pytest.mark.parametrize(
    "change",
    ["missing-file", "missing-hash", "wrong-hash", "missing-date", "forged-date", "wrong-url"],
)
def test_lock_metadata_rejects_pypi_mismatch(
    lock_case: tuple[Path, Path],
    pypi_listing: dict[str, Any],
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    change: str,
) -> None:
    file = pypi_listing["files"][0]
    if change == "missing-file":
        pypi_listing["files"] = []
    elif change == "missing-hash":
        file["hashes"] = {}
    elif change == "wrong-hash":
        file["hashes"]["sha256"] = "0" * 64
    elif change == "missing-date":
        del file["upload-time"]
    elif change == "forged-date":
        lock = lock_case[0]
        lock.write_text(lock.read_text().replace("2021-05-05T14:18:17.237677Z", "2020-05-05T14:18:17.237677Z"))
    else:
        file["url"] = "https://files.pythonhosted.org/other.whl"
    mocker.patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(pypi_listing).encode()))

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert "release lock differs from PyPI metadata" in capsys.readouterr().err


@pytest.mark.parametrize(
    "change", ["lock-index", "project-index", "package-index", "rule-index", "index-settings", "nab-toml"]
)
def test_lock_metadata_rejects_unapproved_indexes(
    lock_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    lock, project = lock_case
    if change == "lock-index":
        lock.write_text(
            lock.read_text().replace('index = "https://pypi.org/simple/"', 'index = "https://example.org/"')
        )
    elif change == "project-index":
        project.write_text(project.read_text() + '[[tool.nab.indexes]]\nname = "other"\nurl = "https://example.org/"\n')
    elif change == "package-index":
        project.write_text(project.read_text() + '[tool.nab.packages.six]\nindex = "other"\n')
    elif change == "rule-index":
        project.write_text(project.read_text() + '[[tool.nab.package-rules]]\nmatch = ["six"]\nindex = "other"\n')
    elif change == "index-settings":
        project.write_text(project.read_text() + "[tool.nab.index.pypi]\nallow-insecure-host = true\n")
    else:
        (project.parent / "nab.toml").write_text("[tool.nab]\nuploaded-prior-to = false\n")

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--project", str(project))

    assert "index" in capsys.readouterr().err


def _run_check(lock_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, *options: str) -> None:
    source = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(source / "tools"))
    monkeypatch.setattr(sys, "argv", ["check_lock_groups.py", str(lock_case[0]), "release-check", *options])
    runpy.run_path(str(source / "tools/check_lock_groups.py"), run_name="__main__")
