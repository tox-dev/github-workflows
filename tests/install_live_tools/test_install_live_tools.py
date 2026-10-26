from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest
from pytest_httpserver import HTTPServer

_SCRIPT: Final = Path(__file__).resolve().parents[2] / "tools/install_live_tools.sh"


@pytest.fixture
def fake_uv(tmp_path: Path) -> Path:
    executable = tmp_path / "bin/uv"
    executable.parent.mkdir()
    executable.write_text(
        f"#!{sys.executable}\nimport json, os, pathlib, sys\n"
        'with pathlib.Path(os.environ["UV_CALLS"]).open("a") as stream:\n'
        "    stream.write(json.dumps({'argv': sys.argv[1:], 'env': dict(os.environ)}) + '\\n')\n"
    )
    executable.chmod(0o755)
    return executable


def _install(tmp_path: Path, fake_uv: Path, **environment: str) -> list[dict[str, Any]]:
    calls = tmp_path / "calls.jsonl"
    subprocess.run(
        [str(_SCRIPT), str(tmp_path / "tools"), "nab>=0.0.22", "packaging>=26.3"],
        env=os.environ
        | {"PATH": f"{fake_uv.parent}{os.pathsep}{os.environ['PATH']}", "UV_CALLS": str(calls)}
        | environment,
        check=True,
    )
    return [json.loads(line) for line in calls.read_text().splitlines()]


def test_install_live_tools_applies_the_cutoff(tmp_path: Path, fake_uv: Path) -> None:
    venv, install = _install(tmp_path, fake_uv, EXCLUDE_NEWER="7 days")

    assert venv["argv"] == ["venv", "--allow-existing", "--python", "3.15", str(tmp_path / "tools")]
    assert install["argv"] == [
        "pip",
        "install",
        "--python",
        str(tmp_path / "tools"),
        "--exclude-newer",
        "7 days",
        "nab>=0.0.22",
        "packaging>=26.3",
    ]


def test_install_live_tools_passes_each_package_cutoff(tmp_path: Path, fake_uv: Path) -> None:
    _, install = _install(
        tmp_path,
        fake_uv,
        EXCLUDE_NEWER="7 days",
        EXCLUDE_NEWER_PACKAGE="nab=2026-10-19T00:00:00Z\n\n  packaging=1 day  \n",
    )

    assert install["argv"][4:10] == [
        "--exclude-newer",
        "7 days",
        "--exclude-newer-package",
        "nab=2026-10-19T00:00:00Z",
        "--exclude-newer-package",
        "packaging=1 day",
    ]


def test_install_live_tools_ignores_inherited_uv_cutoffs(tmp_path: Path, fake_uv: Path) -> None:
    _, install = _install(
        tmp_path,
        fake_uv,
        EXCLUDE_NEWER="7 days",
        UV_EXCLUDE_NEWER="1970-01-01T00:00:00Z",
        UV_EXCLUDE_NEWER_PACKAGE="nab=1970-01-01T00:00:00Z",
    )

    assert not {"UV_EXCLUDE_NEWER", "UV_EXCLUDE_NEWER_PACKAGE"} & install["env"].keys()


def test_install_live_tools_requires_a_cutoff(tmp_path: Path, fake_uv: Path) -> None:
    result = subprocess.run(
        [str(_SCRIPT), str(tmp_path / "tools"), "nab>=0.0.22"],
        env={name: value for name, value in os.environ.items() if name != "EXCLUDE_NEWER"}
        | {"PATH": f"{fake_uv.parent}{os.pathsep}{os.environ['PATH']}", "UV_CALLS": str(tmp_path / "calls.jsonl")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "EXCLUDE_NEWER: unbound variable" in result.stderr


def test_install_live_tools_ignores_inherited_uv_settings(tmp_path: Path, fake_uv: Path) -> None:
    leaked = dict.fromkeys(
        (
            "UV_CONFIG_FILE",
            "UV_INDEX",
            "UV_INDEX_URL",
            "UV_DEFAULT_INDEX",
            "UV_EXTRA_INDEX_URL",
            "UV_FIND_LINKS",
            "UV_INSECURE_HOST",
            "UV_SYSTEM_CERTS",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        ),
        "leak",
    )

    venv, install = _install(tmp_path, fake_uv, EXCLUDE_NEWER="7 days", **leaked)

    assert [venv["env"].get("UV_NO_CONFIG"), install["env"].get("UV_NO_CONFIG")] == ["1", "1"]
    assert not leaked.keys() & (venv["env"].keys() | install["env"].keys())


@pytest.mark.parametrize(
    ("files", "variables"),
    [
        pytest.param({"pyproject.toml": '[tool.uv]\nindex-url = "{index}"\n'}, {}, id="pyproject"),
        pytest.param({"uv.toml": 'index-url = "{index}"\n'}, {}, id="uv-toml"),
        pytest.param({}, {"UV_INDEX_URL": "{index}"}, id="environment"),
    ],
)
def test_install_live_tools_ignores_caller_index(
    tmp_path: Path, httpserver: HTTPServer, files: dict[str, str], variables: dict[str, str]
) -> None:
    caller = tmp_path / "caller"
    caller.mkdir()
    index = httpserver.url_for("/simple")
    for name, template in files.items():
        (caller / name).write_text(template.format(index=index))

    subprocess.run(
        [str(_SCRIPT), str(tmp_path / "tools"), "nab>=0.0.22"],
        cwd=caller,
        env=os.environ
        | {
            "EXCLUDE_NEWER": "7 days",
            # PyPI is unreachable through this proxy, so the install fails fast unless it uses the caller's index.
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "localhost,127.0.0.1",
            "UV_CACHE_DIR": str(tmp_path / "cache"),
            "UV_HTTP_RETRIES": "0",
        }
        | {name: template.format(index=index) for name, template in variables.items()},
        capture_output=True,
        check=False,
    )

    assert httpserver.log == []
