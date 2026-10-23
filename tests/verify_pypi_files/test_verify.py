from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture

_SPEC = importlib.util.spec_from_file_location(
    "verify_pypi_files", Path(__file__).resolve().parents[2] / "tools/verify_pypi_files.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
verify_files = cast("Callable[[str, str, Path, int], list[Path]]", _MODULE.verify_files)


class _ListingFile(TypedDict):
    filename: str
    hashes: dict[str, str]
    yanked: bool


@pytest.fixture
def distribution(tmp_path: Path) -> Path:
    directory = tmp_path / "dist"
    directory.mkdir()
    (directory / "fixture-1.0-py3-none-any.whl").write_bytes(b"wheel")
    (directory / "fixture-1.0.tar.gz").write_bytes(b"sdist")
    return directory


def test_verify_files_matches_complete_release(distribution: Path, mocker: MockerFixture) -> None:
    _serve(mocker, distribution)

    result = verify_files("fixture", "1.0", distribution, 0)

    assert result == [distribution / "fixture-1.0-py3-none-any.whl", distribution / "fixture-1.0.tar.gz"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param("extra", "unexpected files", id="extra"),
        pytest.param("digest", "different SHA256", id="digest"),
        pytest.param("yanked", "yanked PyPI file", id="yanked"),
        pytest.param("missing", "missing files", id="missing"),
        pytest.param("duplicate", "duplicate or yanked", id="duplicate"),
    ],
)
def test_verify_files_rejects_bad_remote_release(
    distribution: Path, mocker: MockerFixture, change: str, message: str
) -> None:
    _serve(mocker, distribution, change=change)

    with pytest.raises(ValueError, match=message):
        verify_files("fixture", "1.0", distribution, 0)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param("wrong-version", "another release", id="wrong-version"),
        pytest.param("symlink", "invalid distribution path", id="symlink"),
        pytest.param("hidden", "invalid distribution path", id="hidden"),
    ],
)
def test_verify_files_rejects_bad_local_release(distribution: Path, change: str, message: str) -> None:
    if change == "wrong-version":
        (distribution / "fixture-2.0-py3-none-any.whl").write_bytes(b"other")
    elif change == "symlink":
        (distribution / "link.whl").symlink_to(distribution / "fixture-1.0-py3-none-any.whl")
    else:
        (distribution / ".hidden").write_bytes(b"other")

    with pytest.raises(ValueError, match=message):
        verify_files("fixture", "1.0", distribution, 0)


def test_verify_files_waits_for_incomplete_listing(distribution: Path, mocker: MockerFixture) -> None:
    files = _listing(distribution)
    response = mocker.patch.object(
        _MODULE,
        "urlopen",
        side_effect=[_body(files[:-1]), _body(files)],
    )
    mocker.patch.object(_MODULE.time, "sleep")

    result = verify_files("fixture", "1.0", distribution, 2)

    assert result == [distribution / "fixture-1.0-py3-none-any.whl", distribution / "fixture-1.0.tar.gz"]
    assert response.call_count == 2


def _serve(mocker: MockerFixture, distribution: Path, *, change: str = "") -> None:
    files = _listing(distribution)
    if change == "extra":
        files.append({"filename": "fixture-1.0-py2-none-any.whl", "hashes": {"sha256": "0" * 64}, "yanked": False})
    elif change == "digest":
        files[0]["hashes"]["sha256"] = "0" * 64
    elif change == "yanked":
        files[0]["yanked"] = True
    elif change == "missing":
        files.pop()
    elif change == "duplicate":
        files.append(files[0].copy())
    mocker.patch.object(_MODULE, "urlopen", return_value=_body(files))


def _listing(distribution: Path) -> list[_ListingFile]:
    return [
        {"filename": path.name, "hashes": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, "yanked": False}
        for path in distribution.iterdir()
    ]


def _body(files: list[_ListingFile]) -> io.BytesIO:
    return io.BytesIO(json.dumps({"meta": {"api-version": "1.0"}, "files": files}).encode())
