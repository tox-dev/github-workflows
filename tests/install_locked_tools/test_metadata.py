from __future__ import annotations

import json
import runpy
import ssl
import sys
from email.message import Message
from io import BytesIO
from pathlib import Path
from textwrap import dedent
from typing import NotRequired, TypedDict
from urllib.error import HTTPError, URLError

import certifi
import pytest
from pytest_mock import MockerFixture

_PyPIFile = TypedDict(
    "_PyPIFile",
    {
        "filename": str,
        "url": str,
        "upload-time": NotRequired[str],
        "hashes": dict[str, str],
        "yanked": NotRequired[bool],
    },
)


class _PyPIListing(TypedDict):
    meta: dict[str, str]
    name: str
    files: list[_PyPIFile]


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
def pypi_listing() -> _PyPIListing:
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
    lock_case: tuple[Path, Path], pypi_listing: _PyPIListing, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = mocker.patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(pypi_listing).encode()))
    context = mocker.patch.object(ssl, "create_default_context", autospec=True)

    _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert request.call_args.args[0].full_url == "https://pypi.org/simple/six/"
    assert context.call_args.kwargs == {"cafile": certifi.where()}


@pytest.mark.parametrize(
    ("producer", "uploaded", "accepted"),
    [
        pytest.param("release-creator (uv)", "2021-05-05T14:18:17Z", True, id="uv-whole-second"),
        pytest.param("release-creator (uv)", "2021-05-05T14:18:16Z", False, id="uv-earlier-second"),
        pytest.param("test", "2021-05-05T14:18:17Z", False, id="nab-needs-fraction"),
    ],
)
def test_lock_metadata_checks_producer_timestamp_precision(
    lock_case: tuple[Path, Path],
    pypi_listing: _PyPIListing,
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    producer: str,
    uploaded: str,
    accepted: bool,
) -> None:
    lock = lock_case[0]
    text = lock.read_text().replace('created-by = "test"', f'created-by = "{producer}"')
    if producer == "release-creator (uv)":
        text = text.replace("[tool.nab]", "[tool.release-creator]")
    lock.write_text(text.replace("2021-05-05T14:18:17.237677Z", uploaded))
    request = mocker.patch(
        "urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: BytesIO(json.dumps(pypi_listing).encode())
    )
    mocker.patch("time.sleep")

    if accepted:
        _run_check(lock_case, monkeypatch, "--verify-pypi")
        assert request.call_count == 1
    else:
        with pytest.raises(SystemExit, match="2"):
            _run_check(lock_case, monkeypatch, "--verify-pypi")
        assert "release lock differs from PyPI metadata" in capsys.readouterr().err


def test_lock_metadata_rejects_yanked_artifact(
    lock_case: tuple[Path, Path],
    pypi_listing: _PyPIListing,
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pypi_listing["files"][0]["yanked"] = True
    mocker.patch(
        "urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: BytesIO(json.dumps(pypi_listing).encode())
    )
    mocker.patch("time.sleep")

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert "release lock differs from PyPI metadata" in capsys.readouterr().err


def test_lock_metadata_retries_transient_network_error(
    lock_case: tuple[Path, Path], pypi_listing: _PyPIListing, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = mocker.patch(
        "urllib.request.urlopen",
        side_effect=[URLError("handshake timed out"), BytesIO(json.dumps(pypi_listing).encode())],
    )
    sleep = mocker.patch("time.sleep")

    _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert request.call_count == 2
    sleep.assert_called_once_with(1)


def test_lock_metadata_retries_stale_listing(
    lock_case: tuple[Path, Path], pypi_listing: _PyPIListing, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = {**pypi_listing, "files": []}
    request = mocker.patch(
        "urllib.request.urlopen",
        side_effect=[BytesIO(json.dumps(stale).encode()), BytesIO(json.dumps(pypi_listing).encode())],
    )
    sleep = mocker.patch("time.sleep")

    _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert request.call_count == 2
    sleep.assert_called_once_with(1)


def test_lock_metadata_stops_after_five_network_errors(
    lock_case: tuple[Path, Path],
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = mocker.patch("urllib.request.urlopen", side_effect=URLError("handshake timed out"))
    mocker.patch("time.sleep")

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert request.call_count == 5
    assert "handshake timed out" in capsys.readouterr().err


@pytest.mark.parametrize(
    "status",
    [pytest.param(404, id="not-yet-listed"), pytest.param(429, id="rate-limit"), pytest.param(503, id="server-error")],
)
def test_lock_metadata_retries_transient_http_error(
    lock_case: tuple[Path, Path],
    pypi_listing: _PyPIListing,
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    request = mocker.patch(
        "urllib.request.urlopen",
        side_effect=[
            HTTPError("https://pypi.org/simple/six/", status, "transient", Message(), None),
            BytesIO(json.dumps(pypi_listing).encode()),
        ],
    )
    mocker.patch("time.sleep")

    _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert request.call_count == 2


@pytest.mark.parametrize(
    ("status", "calls"),
    [pytest.param(404, 5, id="not-found"), pytest.param(503, 5, id="repeated-server-error")],
)
def test_lock_metadata_rejects_http_error(
    lock_case: tuple[Path, Path],
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
    calls: int,
) -> None:
    request = mocker.patch(
        "urllib.request.urlopen",
        side_effect=HTTPError("https://pypi.org/simple/six/", status, "unavailable", Message(), None),
    )
    mocker.patch("time.sleep")

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert request.call_count == calls
    assert f"HTTP Error {status}" in capsys.readouterr().err


def test_lock_metadata_requires_group(
    lock_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(source / "tools"))
    monkeypatch.setattr(sys, "argv", ["check_lock_groups.py", str(lock_case[0])])
    command = runpy.run_path(str(source / "tools/check_lock_groups.py"), run_name="lock_check")

    with pytest.raises(SystemExit, match="2"):
        command["main"]()

    assert "at least one dependency group is required" in capsys.readouterr().err


def test_lock_metadata_checks_base_selection_without_groups(
    lock_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = lock_case[0]
    lock.write_text(
        lock.read_text()
        .replace('dependency-groups = ["release-check"]\n', "")
        .replace('"release-check" in dependency_groups', '"build" not in dependency_groups')
        .replace("files.pythonhosted.org", "example.org")
    )

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--build-constraints")

    assert "non-PyPI artifact" in capsys.readouterr().err


@pytest.mark.parametrize(
    "change", [pytest.param("api-version", id="api-version"), pytest.param("project-name", id="project-name")]
)
def test_lock_metadata_rejects_invalid_listing(
    lock_case: tuple[Path, Path],
    pypi_listing: _PyPIListing,
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    change: str,
) -> None:
    if change == "api-version":
        pypi_listing["meta"]["api-version"] = "2.0"
    else:
        pypi_listing["name"] = "other"
    mocker.patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(pypi_listing).encode()))

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert "invalid PyPI listing for six" in capsys.readouterr().err


@pytest.mark.parametrize(
    "listing",
    [
        pytest.param([], id="non-object-root"),
        pytest.param({"meta": [], "files": []}, id="non-object-metadata"),
        pytest.param({"meta": {"api-version": "1.4"}, "name": "six", "files": ["bad"]}, id="non-object-file"),
    ],
)
def test_lock_metadata_rejects_non_object_listing(
    lock_case: tuple[Path, Path],
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    listing: object,
) -> None:
    mocker.patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(listing).encode()))

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert "invalid PyPI listing for six" in capsys.readouterr().err


def test_lock_metadata_allows_local_release_creator(
    lock_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = lock_case[0]
    lock.write_text(
        lock.read_text().split("[[packages]]", 1)[0]
        + '[[packages]]\nname = "release-creator"\nmarker = \'"release-check" in dependency_groups\'\n'
        + 'directory = { path = "." }\n'
    )

    _run_check(lock_case, monkeypatch, "--local-tool-source", "--verify-pypi", "--project", str(lock_case[1]))


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param(
            'archive = { url = "https://evil.invalid/six.whl", hashes = { sha256 = "' + "0" * 64 + '" } }',
            "direct-source",
            id="archive",
        ),
        pytest.param('directory = { path = "." }', "direct-source", id="directory"),
        pytest.param(
            'vcs = { type = "git", url = "https://evil.invalid/six.git", commit-id = "' + "a" * 40 + '" }',
            "direct-source",
            id="vcs",
        ),
    ],
)
def test_lock_metadata_rejects_unchecked_source(
    lock_case: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    source: str,
    message: str,
) -> None:
    lock = lock_case[0]
    lock.write_text(lock.read_text().split('index = "https://pypi.org/simple/"', 1)[0] + source + "\n")

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert message in capsys.readouterr().err


def test_lock_metadata_rejects_indexless_wheel(
    lock_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = lock_case[0]
    lock.write_text(lock.read_text().replace('index = "https://pypi.org/simple/"\n', ""))

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--project", str(lock_case[1]))

    assert "uncooled non-index package" in capsys.readouterr().err


def test_lock_metadata_checks_other_locked_platform(
    lock_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = lock_case[0]
    lock.write_text(
        lock.read_text()
        .replace(
            'dependency-groups = ["release-check"]',
            'dependency-groups = ["release-check"]\nenvironments = [\'sys_platform == "win32"\']',
        )
        .replace(
            "marker = '\"release-check\" in dependency_groups'",
            'marker = \'"release-check" in dependency_groups and sys_platform == "win32"\'',
        )
        .replace("files.pythonhosted.org", "evil.invalid")
    )

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--project", str(lock_case[1]))

    assert "non-PyPI artifact" in capsys.readouterr().err


def test_lock_metadata_checks_nested_group_marker(
    lock_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = lock_case[0]
    lock.write_text(
        lock.read_text()
        .replace(
            "marker = '\"release-check\" in dependency_groups'",
            'marker = \'("release-check" in dependency_groups and sys_platform == "win32") or "test" in dependency_groups\'',
        )
        .replace("files.pythonhosted.org", "evil.invalid")
    )

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--project", str(lock_case[1]))

    assert "non-PyPI artifact" in capsys.readouterr().err


def test_lock_metadata_checks_package_excluding_extras(
    lock_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = lock_case[0]
    lock.write_text(
        lock.read_text()
        .replace("marker = '\"release-check\" in dependency_groups'", "marker = '\"web\" not in extras'")
        .replace("files.pythonhosted.org", "evil.invalid")
    )

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--project", str(lock_case[1]))

    assert "non-PyPI artifact" in capsys.readouterr().err


def test_lock_metadata_checks_each_duplicate_artifact(
    lock_case: tuple[Path, Path],
    pypi_listing: _PyPIListing,
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock = lock_case[0]
    head, package = lock.read_text().split("[[packages]]")
    lock.write_text(
        f"{head}[[packages]]{package.replace(pypi_listing['files'][0]['hashes']['sha256'], '0' * 64)}"
        f"[[packages]]{package}"
    )
    mocker.patch(
        "urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: BytesIO(json.dumps(pypi_listing).encode())
    )
    mocker.patch("time.sleep")

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch, "--verify-pypi", "--project", str(lock_case[1]))

    assert "release lock differs from PyPI metadata" in capsys.readouterr().err


@pytest.mark.parametrize(
    "change",
    ["missing-file", "missing-hash", "wrong-hash", "missing-date", "forged-date", "wrong-url"],
)
def test_lock_metadata_rejects_pypi_mismatch(
    lock_case: tuple[Path, Path],
    pypi_listing: _PyPIListing,
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
    mocker.patch(
        "urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: BytesIO(json.dumps(pypi_listing).encode())
    )
    mocker.patch("time.sleep")

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


@pytest.mark.parametrize(
    ("change", "group"),
    [
        pytest.param("lock", "release-check", id="lock-group"),
        pytest.param("argument", "Release-Check", id="selected-group"),
    ],
)
def test_lock_metadata_rejects_unnormalized_group(
    lock_case: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    change: str,
    group: str,
) -> None:
    lock = lock_case[0]
    if change == "lock":
        lock.write_text(lock.read_text().replace('dependency-groups = ["release-check"]', 'dependency-groups = ["release-check", "project_runtime"]'))
    source = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(source / "tools"))
    monkeypatch.setattr(sys, "argv", ["check_lock_groups.py", str(lock), group])

    with pytest.raises(SystemExit, match="2"):
        runpy.run_path(str(source / "tools/check_lock_groups.py"), run_name="__main__")

    assert "dependency group names must be normalized" in capsys.readouterr().err


def test_lock_metadata_rejects_non_table_producer(
    lock_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = lock_case[0]
    lock.write_text(lock.read_text().replace("[tool.nab]\ncreated-at = 2026-10-20T00:00:00Z\n", '[tool]\nnab = "oops"\n'))

    with pytest.raises(SystemExit, match="2"):
        _run_check(lock_case, monkeypatch)

    assert "lock producer settings must be a table" in capsys.readouterr().err


def _run_check(lock_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, *options: str) -> None:
    source = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(source / "tools"))
    monkeypatch.setattr(sys, "argv", ["check_lock_groups.py", str(lock_case[0]), "release-check", *options])
    runpy.run_path(str(source / "tools/check_lock_groups.py"), run_name="__main__")
