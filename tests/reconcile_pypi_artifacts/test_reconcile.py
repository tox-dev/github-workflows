from __future__ import annotations

import hashlib
from pathlib import Path
from textwrap import dedent

import pytest
from conftest import action
from pytest_httpserver import HTTPServer


@pytest.mark.parametrize(
    ("project", "version", "distribution_exists"),
    [
        pytest.param("", "1.0", True, id="missing-project"),
        pytest.param("fixture", "", True, id="missing-version"),
        pytest.param("fixture", "1.0", False, id="missing-distribution"),
    ],
)
def test_reconcile_rejects_invalid_inputs(
    tmp_path: Path,
    action_scripts: Path,
    project: str,
    version: str,
    distribution_exists: bool,
) -> None:
    distribution = tmp_path / "dist"
    if distribution_exists:
        distribution.mkdir()
    result = action(
        Path(__file__).resolve().parents[2],
        tmp_path,
        action_scripts,
        "reconcile-pypi-artifacts",
        version=version,
        PROJECT=project,
        DIST=str(distribution),
    )
    assert result.returncode != 0


@pytest.mark.parametrize(
    ("remote_extra", "wrong_digest", "expected_error"),
    [
        pytest.param(False, False, "Provenance for file", id="matching-files-require-attestation"),
        pytest.param(True, False, "PyPI has unexpected files", id="unexpected-remote-file"),
        pytest.param(False, True, "PyPI has different SHA256 digests", id="digest-mismatch"),
    ],
)
def test_reconcile_checks_complete_release_before_attestations(
    tmp_path: Path,
    action_scripts: Path,
    httpserver: HTTPServer,
    remote_extra: bool,
    wrong_digest: bool,
    expected_error: str,
) -> None:
    distribution = tmp_path / "dist"
    distribution.mkdir()
    wheel_name = "fixture-1.0-py3-none-any.whl"
    wheel = distribution / wheel_name
    wheel.write_bytes(b"wheel contents")
    url = f"https://files.pythonhosted.org/packages/a/{wheel_name}"
    sdist_name = "fixture-1.0.tar.gz"
    sdist_url = f"https://files.pythonhosted.org/packages/b/{sdist_name}"
    if not remote_extra and not wrong_digest:
        (distribution / sdist_name).write_bytes(b"sdist contents")
    files = [
        {
            "filename": wheel_name,
            "url": url,
            "hashes": {"sha256": "0" * 64 if wrong_digest else hashlib.sha256(wheel.read_bytes()).hexdigest()},
            "yanked": False,
        },
    ]
    if not wrong_digest:
        files.append(
            {
                "filename": sdist_name,
                "url": sdist_url,
                "hashes": {
                    "sha256": "1" * 64
                    if remote_extra
                    else hashlib.sha256((distribution / sdist_name).read_bytes()).hexdigest()
                },
                "yanked": False,
            },
        )
    httpserver.expect_request("/simple/fixture/").respond_with_json({"meta": {"api-version": "1.0"}, "files": files})
    if not remote_extra and not wrong_digest:
        httpserver.expect_request(f"/packages/a/{wheel_name}").respond_with_data(wheel.read_bytes())
        httpserver.expect_request(f"/integrity/fixture/1.0/{wheel_name}/provenance").respond_with_json(
            {"message": "missing"}, status=404
        )
    python_path = tmp_path / "pythonpath"
    python_path.mkdir()
    (python_path / "sitecustomize.py").write_text(
        dedent(
            """
            import os
            from urllib.parse import urlsplit
            import urllib.request

            base = os.environ["TEST_PYPI_SERVER"]
            original_open = urllib.request.urlopen

            def route_open(request, *args, **kwargs):
                parsed = urlsplit(request.full_url)
                if parsed.hostname == "pypi.org":
                    request = urllib.request.Request(f"{base}{parsed.path}", headers=dict(request.header_items()))
                return original_open(request, *args, **kwargs)

            urllib.request.urlopen = route_open

            try:
                import requests
            except ImportError:
                pass
            else:
                original_request = requests.Session.request

                def route_request(self, method, url, *args, **kwargs):
                    parsed = urlsplit(url)
                    if parsed.hostname in {"pypi.org", "files.pythonhosted.org"}:
                        url = f"{base}{parsed.path}"
                    return original_request(self, method, url, *args, **kwargs)

                requests.Session.request = route_request
            """
        ),
    )
    result = action(
        Path(__file__).resolve().parents[2],
        tmp_path,
        action_scripts,
        "reconcile-pypi-artifacts",
        version="1.0",
        PROJECT="fixture",
        DIST=str(distribution),
        PYTHONPATH=str(python_path),
        TEST_PYPI_SERVER=httpserver.url_for("").rstrip("/"),
        NO_PROXY="localhost,127.0.0.1",
    )
    assert result.returncode != 0
    assert expected_error in result.stderr
    if not remote_extra and not wrong_digest:
        assert (
            tmp_path / "pypi-local-files"
        ).read_text() == f"{distribution / wheel_name}\n{distribution / sdist_name}\n"
