from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import runpy
import ssl
from email.message import Message
from http.client import IncompleteRead
from pathlib import Path
from socket import gaierror
from typing import TYPE_CHECKING, TypedDict, cast
from urllib.error import HTTPError, URLError

import certifi
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

type _Json = None | bool | int | float | str | list[_Json] | dict[str, _Json]


class _ListingFile(TypedDict):
    filename: str
    hashes: dict[str, str]
    yanked: bool | str


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


def test_verify_files_uses_pinned_trust_store(distribution: Path, mocker: MockerFixture) -> None:
    request = mocker.patch.object(_MODULE, "urlopen", return_value=_body(_listing(distribution)))
    context = mocker.patch.object(ssl, "create_default_context", autospec=True)

    verify_files("fixture", "1.0", distribution, 0)

    assert request.call_args.kwargs["context"] is context.return_value
    assert context.call_args.kwargs == {"cafile": certifi.where()}


def test_verify_files_rejects_unsupported_simple_api(distribution: Path, mocker: MockerFixture) -> None:
    mocker.patch.object(
        _MODULE,
        "urlopen",
        return_value=io.BytesIO(json.dumps({"meta": {"api-version": "2.0"}, "files": _listing(distribution)}).encode()),
    )
    with pytest.raises(ValueError, match="unsupported PyPI Simple API version"):
        verify_files("fixture", "1.0", distribution, 0)


def test_main_prints_distribution_paths(
    distribution: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    _serve(mocker, distribution)
    mocker.patch("sys.argv", ["verify_pypi_files", "fixture", "1.0", str(distribution)])

    cast("Callable[[], None]", _MODULE.main)()

    assert capsys.readouterr().out.splitlines() == [
        str(distribution / "fixture-1.0-py3-none-any.whl"),
        str(distribution / "fixture-1.0.tar.gz"),
    ]


def test_main_reports_invalid_directory(
    tmp_path: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    mocker.patch("sys.argv", ["verify_pypi_files", "fixture", "1.0", str(tmp_path / "missing")])

    with pytest.raises(SystemExit) as raised:
        cast("Callable[[], None]", _MODULE.main)()

    assert raised.value.code == 2
    assert "release files require a directory" in capsys.readouterr().err


def test_script_entrypoint_prints_distribution_paths(
    distribution: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    mocker.patch("urllib.request.urlopen", return_value=_body(_listing(distribution)))
    mocker.patch("sys.argv", ["verify_pypi_files", "fixture", "1.0", str(distribution)])

    runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/verify_pypi_files.py"), run_name="__main__")

    assert capsys.readouterr().out.splitlines() == [
        str(distribution / "fixture-1.0-py3-none-any.whl"),
        str(distribution / "fixture-1.0.tar.gz"),
    ]


@pytest.mark.parametrize(
    "change", [pytest.param("negative-wait", id="negative-wait"), pytest.param("missing-dir", id="missing-dir")]
)
def test_verify_files_rejects_invalid_arguments(tmp_path: Path, change: str) -> None:
    directory = tmp_path if change == "negative-wait" else tmp_path / "missing"

    with pytest.raises(ValueError, match="release files require a directory and nonnegative wait"):
        verify_files("fixture", "1.0", directory, -1 if change == "negative-wait" else 0)


def test_verify_files_rejects_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="distribution directory is empty"):
        verify_files("fixture", "1.0", tmp_path, 0)


def test_verify_files_rejects_directory_entry(distribution: Path) -> None:
    (distribution / "nested").mkdir()

    with pytest.raises(ValueError, match="invalid distribution path"):
        verify_files("fixture", "1.0", distribution, 0)


def test_verify_files_ignores_other_release_wheel(distribution: Path, mocker: MockerFixture) -> None:
    files = _listing(distribution)
    files.append({"filename": "fixture-0.9-py3-none-any.whl", "hashes": {"sha256": "0" * 64}, "yanked": False})
    mocker.patch.object(_MODULE, "urlopen", return_value=_body(files))

    assert verify_files("fixture", "1.0", distribution, 0) == [
        distribution / "fixture-1.0-py3-none-any.whl",
        distribution / "fixture-1.0.tar.gz",
    ]


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(400, id="client-error"),
        pytest.param(403, id="forbidden"),
        pytest.param(503, id="server-timeout"),
    ],
)
def test_verify_files_propagates_http_error(distribution: Path, mocker: MockerFixture, status: int) -> None:
    mocker.patch.object(
        _MODULE, "urlopen", side_effect=HTTPError("https://pypi.org/simple/fixture/", status, "error", Message(), None)
    )

    with pytest.raises(HTTPError) as raised:
        verify_files("fixture", "1.0", distribution, 0)

    assert raised.value.code == status


def test_verify_files_propagates_exhausted_connection_error(distribution: Path, mocker: MockerFixture) -> None:
    mocker.patch.object(_MODULE, "urlopen", side_effect=URLError("offline"))

    with pytest.raises(URLError, match="offline"):
        verify_files("fixture", "1.0", distribution, 0)


def test_verify_files_reports_missing_release_after_404(distribution: Path, mocker: MockerFixture) -> None:
    mocker.patch.object(
        _MODULE, "urlopen", side_effect=HTTPError("https://pypi.org/simple/fixture/", 404, "missing", Message(), None)
    )

    with pytest.raises(ValueError, match="PyPI is missing files"):
        verify_files("fixture", "1.0", distribution, 0)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([], id="not-object"),
        pytest.param({"meta": {"api-version": "1.0"}, "files": {}}, id="files-not-list"),
        pytest.param({"meta": None, "files": []}, id="missing-metadata"),
        pytest.param({"meta": {"api-version": "2.0"}, "files": []}, id="unsupported-version"),
    ],
)
def test_verify_files_rejects_invalid_listing(distribution: Path, mocker: MockerFixture, payload: _Json) -> None:
    mocker.patch.object(_MODULE, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode()))

    with pytest.raises(
        (TypeError, ValueError), match="invalid Simple API response|unsupported PyPI Simple API version"
    ):
        verify_files("fixture", "1.0", distribution, 0)


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(None, id="not-object"),
        pytest.param({"hashes": {"sha256": "0" * 64}}, id="missing-filename"),
        pytest.param({"filename": "fixture-1.0.tar.gz", "hashes": None}, id="missing-hashes"),
        pytest.param({"filename": "fixture-1.0.tar.gz", "hashes": {"sha256": None}}, id="missing-sha256"),
    ],
)
def test_verify_files_rejects_invalid_file_entry(distribution: Path, mocker: MockerFixture, entry: _Json) -> None:
    mocker.patch.object(
        _MODULE,
        "urlopen",
        return_value=io.BytesIO(json.dumps({"meta": {"api-version": "1.0"}, "files": [entry]}).encode()),
    )

    with pytest.raises(TypeError, match="invalid file entry"):
        verify_files("fixture", "1.0", distribution, 0)


def test_verify_files_ignores_legacy_egg_from_older_release(distribution: Path, mocker: MockerFixture) -> None:
    files = _listing(distribution)
    files.append({"filename": "fixture-0.8.1-py2.4.egg", "hashes": {"sha256": "0" * 64}, "yanked": False})
    mocker.patch.object(_MODULE, "urlopen", return_value=_body(files))

    assert verify_files("fixture", "1.0", distribution, 0) == [
        distribution / "fixture-1.0-py3-none-any.whl",
        distribution / "fixture-1.0.tar.gz",
    ]


@pytest.mark.parametrize(
    "filename",
    [
        pytest.param("fixture-0.9.1-py2.7.egg", id="next-release"),
        pytest.param("fixture-0.9.post1-py2.7.egg", id="post-release"),
        pytest.param("fixture-0.9.dev1.tar.bz2", id="development-release"),
    ],
)
def test_verify_files_ignores_legacy_files_from_other_versions(
    distribution: Path, mocker: MockerFixture, filename: str
) -> None:
    for path in distribution.iterdir():
        path.rename(path.with_name(path.name.replace("1.0", "0.9")))
    files = _listing(distribution)
    files.append({"filename": filename, "hashes": {"sha256": "0" * 64}, "yanked": False})
    mocker.patch.object(_MODULE, "urlopen", return_value=_body(files))

    assert verify_files("fixture", "0.9", distribution, 0) == [
        distribution / "fixture-0.9-py3-none-any.whl",
        distribution / "fixture-0.9.tar.gz",
    ]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param("extra", "unexpected files", id="extra"),
        pytest.param("digest", "different SHA256", id="digest"),
        pytest.param("yanked", "yanked PyPI file", id="yanked"),
        pytest.param("yanked-empty", "yanked PyPI file", id="yanked-empty-reason"),
        pytest.param("missing", "missing files", id="missing"),
        pytest.param("duplicate", "duplicate or yanked", id="duplicate"),
        pytest.param("invalid-name", "unrecognized distribution filename", id="invalid-name"),
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


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(
            HTTPError("https://pypi.org/simple/fixture/", 429, "rate limit", Message(), None), id="rate-limit"
        ),
        pytest.param(
            HTTPError("https://pypi.org/simple/fixture/", 503, "unavailable", Message(), None), id="server-error"
        ),
        pytest.param(URLError(TimeoutError("timeout")), id="timeout"),
        pytest.param(URLError(gaierror("DNS failure")), id="dns"),
        pytest.param(ConnectionResetError("connection reset"), id="reset"),
        pytest.param(TimeoutError("read timeout"), id="read-timeout"),
        pytest.param(IncompleteRead(b"partial", 10), id="incomplete-read"),
        pytest.param(ssl.SSLError("TLS failure"), id="tls"),
        pytest.param(json.JSONDecodeError("truncated", "{", 1), id="truncated-json"),
    ],
)
def test_verify_files_retries_transient_listing_failure(
    distribution: Path, mocker: MockerFixture, failure: OSError | IncompleteRead | json.JSONDecodeError
) -> None:
    response = mocker.patch.object(_MODULE, "urlopen", side_effect=[failure, _body(_listing(distribution))])
    mocker.patch.object(_MODULE.time, "sleep")

    assert verify_files("fixture", "1.0", distribution, 2) == [
        distribution / "fixture-1.0-py3-none-any.whl",
        distribution / "fixture-1.0.tar.gz",
    ]
    assert response.call_count == 2


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(TimeoutError("read timeout"), id="timeout"),
        pytest.param(IncompleteRead(b"partial", 10), id="incomplete-read"),
    ],
)
def test_verify_files_retries_response_read_failure(
    distribution: Path, mocker: MockerFixture, failure: TimeoutError | IncompleteRead
) -> None:
    response = mocker.create_autospec(io.BytesIO, instance=True)
    response.__enter__.return_value.read.side_effect = failure
    mocker.patch.object(_MODULE, "urlopen", side_effect=[response, _body(_listing(distribution))])
    mocker.patch.object(_MODULE.time, "sleep")

    assert verify_files("fixture", "1.0", distribution, 2) == [
        distribution / "fixture-1.0-py3-none-any.whl",
        distribution / "fixture-1.0.tar.gz",
    ]


def test_verify_files_retries_truncated_json_response(distribution: Path, mocker: MockerFixture) -> None:
    response = mocker.patch.object(
        _MODULE, "urlopen", side_effect=[io.BytesIO(b'{"meta":'), _body(_listing(distribution))]
    )
    mocker.patch.object(_MODULE.time, "sleep")

    assert verify_files("fixture", "1.0", distribution, 2) == [
        distribution / "fixture-1.0-py3-none-any.whl",
        distribution / "fixture-1.0.tar.gz",
    ]
    assert response.call_count == 2


def test_main_reports_exhausted_incomplete_read(
    distribution: Path, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    mocker.patch.object(_MODULE, "urlopen", side_effect=IncompleteRead(b"partial", 10))
    mocker.patch.object(_MODULE.time, "monotonic", side_effect=[0, 121])
    mocker.patch("sys.argv", ["verify_pypi_files", "fixture", "1.0", str(distribution)])

    with pytest.raises(SystemExit) as raised:
        cast("Callable[[], None]", _MODULE.main)()

    assert raised.value.code == 2
    assert "IncompleteRead" in capsys.readouterr().err


def test_verify_files_backs_off_between_retries(distribution: Path, mocker: MockerFixture) -> None:
    mocker.patch.object(
        _MODULE,
        "urlopen",
        side_effect=[
            URLError(TimeoutError("timeout")),
            URLError(TimeoutError("timeout")),
            _body(_listing(distribution)),
        ],
    )
    sleep = mocker.patch.object(_MODULE.time, "sleep")

    verify_files("fixture", "1.0", distribution, 5)

    assert [call.args for call in sleep.call_args_list] == [(1,), (2,)]


def _serve(mocker: MockerFixture, distribution: Path, *, change: str = "") -> None:
    files = _listing(distribution)
    if change == "extra":
        files.append({"filename": "fixture-1.0-py2-none-any.whl", "hashes": {"sha256": "0" * 64}, "yanked": False})
    elif change == "digest":
        files[0]["hashes"]["sha256"] = "0" * 64
    elif change == "yanked":
        files[0]["yanked"] = True
    elif change == "yanked-empty":
        files[0]["yanked"] = ""
    elif change == "missing":
        files.pop()
    elif change == "duplicate":
        files.append(files[0].copy())
    elif change == "invalid-name":
        files.append({"filename": "fixture-1.0.invalid", "hashes": {"sha256": "0" * 64}, "yanked": False})
    mocker.patch.object(_MODULE, "urlopen", return_value=_body(files))


def _listing(distribution: Path) -> list[_ListingFile]:
    return [
        {"filename": path.name, "hashes": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, "yanked": False}
        for path in distribution.iterdir()
    ]


def _body(files: list[_ListingFile]) -> io.BytesIO:
    return io.BytesIO(json.dumps({"meta": {"api-version": "1.0"}, "files": files}).encode())
