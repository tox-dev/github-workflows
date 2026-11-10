import os
import re
import shlex
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from textwrap import dedent

import pytest
import yaml
from conftest import action
from pytest_httpserver import HTTPServer

SCRIPT = Path(__file__).resolve().parents[2] / "tools/cooled_prek.py"


def _fake_uv(directory: Path, httpserver: HTTPServer) -> None:
    # The snippet runs as `uv run --with pyyaml python -I -`. The fake drops everything but the interpreter and
    # imports a sitecustomize from a test-only directory, since -I ignores PYTHONPATH; it sends pypi.org to the server.
    site = directory / "pypi-site"
    site.mkdir()
    base = httpserver.url_for("").rstrip("/")
    (site / "sitecustomize.py").write_text(
        dedent(
            f"""
            import urllib.request
            from urllib.parse import urlsplit

            base = {base!r}
            original_open = urllib.request.urlopen

            def route_open(request, *args, **kwargs):
                parsed = urlsplit(request.full_url)
                if parsed.hostname == "pypi.org":
                    request = urllib.request.Request(base + parsed.path, headers=dict(request.header_items()))
                return original_open(request, *args, **kwargs)

            urllib.request.urlopen = route_open
            """
        )
    )
    code = (
        f"import coverage, sys; coverage.process_startup(); sys.path.insert(0, {str(site)!r}); "
        f"import sitecustomize; exec(compile(sys.stdin.read(), {str(SCRIPT.with_name('hook_pin_cutoffs.py'))!r}, 'exec'))"
    )
    fake = directory / "uv"
    fake.write_text(f"#!/bin/sh\nexec {sys.executable!r} -I -c {shlex.quote(code)}\n")
    fake.chmod(0o755)


def test_no_hook_run_bypasses_cooled_prek() -> None:
    root = Path(__file__).resolve().parents[2]
    runs = [
        step.get("run", "")
        for path in (*root.glob(".github/workflows/*.yaml"), *root.glob("*/action.yml"))
        for document in [yaml.load(path.read_text(), Loader=yaml.BaseLoader)]
        for steps in (
            [document["runs"]["steps"]]
            if "runs" in document
            else [job.get("steps", []) for job in document["jobs"].values()]
        )
        for step in steps
    ]
    commands = [
        command
        for run in runs
        for command in re.findall(r"\bprek (?:run|install-hooks|update)\b[^\n]*", run.replace("\\\n", " "))
    ]

    assert not commands, commands


@pytest.mark.parametrize("name", ["prepare-towncrier-release.yaml", "prepare-release-creator.yaml"])
def test_prepare_installs_no_hook_it_does_not_run(name: str) -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
    )

    assert "install-hooks" not in str(workflow["jobs"]["assemble"]["steps"])


def test_cooled_prek_action_passes_each_argument(tmp_path: Path, action_scripts: Path, httpserver: HTTPServer) -> None:
    fake = tmp_path / "bin/prek"
    fake.parent.mkdir()
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >"$RUNNER_TEMP/args"\n')
    fake.chmod(0o755)
    _fake_uv(fake.parent, httpserver)

    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "cooled-prek",
        version="",
        ARGS="run mdformat --files CHANGELOG.md",
        PATH=f"{fake.parent}:{os.environ['PATH']}",
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "args").read_text().splitlines() == [
        "--config",
        ".pre-commit-config.yaml",
        "run",
        "mdformat",
        "--files",
        "CHANGELOG.md",
    ]


@pytest.mark.parametrize(
    ("arguments", "install"),
    [
        pytest.param(["run", "--all-files"], ["install-hooks"], id="every-hook"),
        pytest.param(["run", "mdformat"], ["install-hooks", "mdformat"], id="named-hook-without-options"),
        pytest.param(["run", "mdformat", "--files", "CHANGELOG.md"], ["install-hooks", "mdformat"], id="named-hook"),
    ],
)
def test_cooled_prek_builds_hooks_cooled_and_runs_them_with_the_caller_environment(
    tmp_path: Path, arguments: list[str], install: list[str], httpserver: HTTPServer
) -> None:
    fake = tmp_path / "prek"
    fake.write_text(
        '#!/bin/sh\nn=$(ls calls 2>/dev/null | wc -l)\nmkdir -p calls/$n\nprintf "%s\\n" "$@" >calls/$n/args\nenv >calls/$n/env\n'
    )
    fake.chmod(0o755)
    _fake_uv(tmp_path, httpserver)
    leaked = dict.fromkeys(("UV_INDEX_URL", "UV_EXCLUDE_NEWER_PACKAGE", "UV_SYSTEM_CERTS", "SSL_CERT_FILE"), "leak")

    subprocess.run(
        [str(Path(__file__).resolve().parents[2] / "tools/cooled_prek.py"), *arguments],
        cwd=tmp_path,
        env=os.environ | leaked | {"PATH": f"{tmp_path}:{os.environ['PATH']}", "UV_EXCLUDE_NEWER": "1 day"},
        check=True,
    )

    calls = [
        (
            (call / "args").read_text().splitlines(),
            dict(line.split("=", 1) for line in (call / "env").read_text().splitlines() if "=" in line),
        )
        for call in sorted((tmp_path / "calls").iterdir(), key=lambda path: int(path.name))
    ]
    (install_args, install_env), (run_args, run_env) = calls
    assert install_args == ["--config", ".pre-commit-config.yaml", *install]
    assert {name: install_env.get(name) for name in ("UV_EXCLUDE_NEWER", "UV_NO_CONFIG", "UV_NO_SOURCES")} == {
        "UV_EXCLUDE_NEWER": "7 days",
        "UV_NO_CONFIG": "1",
        "UV_NO_SOURCES": "1",
    }
    assert not leaked.keys() & install_env.keys()
    assert run_args == ["--config", ".pre-commit-config.yaml", *arguments]
    assert run_env.get("UV_EXCLUDE_NEWER") == "1 day"
    assert "UV_NO_CONFIG" not in run_env
    assert leaked.items() <= run_env.items()


def test_cooled_prek_stops_when_pin_discovery_fails(tmp_path: Path) -> None:
    for name, body in (("uv", "exit 7"), ("prek", "touch ran")):
        executable = tmp_path / name
        executable.write_text(f"#!/bin/sh\n{body}\n")
        executable.chmod(0o755)

    result = subprocess.run(
        [str(SCRIPT), "run", "--all-files"],
        cwd=tmp_path,
        env=os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 7
    assert not (tmp_path / "ran").exists()


def test_cooled_prek_admits_nab_cutoff_exceptions(tmp_path: Path, httpserver: HTTPServer) -> None:
    fake = tmp_path / "prek"
    fake.write_text('#!/bin/sh\ncat "$UV_CONFIG_FILE" >config\n')
    fake.chmod(0o755)
    _fake_uv(tmp_path, httpserver)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.nab]\nuploaded-prior-to = "P7D"\npackages.sphinx.uploaded-prior-to = 2026-10-21T00:05:13Z\n'
        'packages.release-creator.uploaded-prior-to = "2026-10-26T18:24:46Z"\npackages.uv.decision-order = "stable"\n'
    )

    subprocess.run(
        [str(Path(__file__).resolve().parents[2] / "tools/cooled_prek.py"), "install-hooks"],
        cwd=tmp_path,
        env=os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"},
        check=True,
    )

    assert (tmp_path / "config").read_text().splitlines() == [
        "[exclude-newer-package]",
        '"release-creator" = "2026-10-26T18:24:46Z"',
        '"sphinx" = "2026-10-21T00:05:13Z"',
    ]


def test_cooled_prek_without_exceptions_sets_no_config_file(tmp_path: Path, httpserver: HTTPServer) -> None:
    fake = tmp_path / "prek"
    fake.write_text('#!/bin/sh\nprintf "%s" "${UV_CONFIG_FILE-unset}" >config\n')
    fake.chmod(0o755)
    _fake_uv(tmp_path, httpserver)
    (tmp_path / "pyproject.toml").write_text('[tool.nab]\nuploaded-prior-to = "P7D"\n')

    subprocess.run(
        [str(Path(__file__).resolve().parents[2] / "tools/cooled_prek.py"), "install-hooks"],
        cwd=tmp_path,
        env=os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}", "UV_CONFIG_FILE": "/leak/uv.toml"},
        check=True,
    )

    assert (tmp_path / "config").read_text() == "unset"


def _hook_repo(root: Path, files: dict[str, str]) -> Path:
    repo = root / "hook"
    repo.mkdir()
    for name, text in {"README.md": "hook\n", **files}.items():
        (repo / name).write_text(text)
    git = ["git", "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@example.com"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "release"], check=True)
    subprocess.run([*git, "tag", "v1.0.0"], check=True)
    return repo


def _config(root: Path, repo: Path, hook: dict[str, object]) -> None:
    (root / ".pre-commit-config.yaml").write_text(
        yaml.safe_dump({"repos": [{"repo": str(repo), "rev": "v1.0.0", "hooks": [{"id": "simplint", **hook}]}]})
    )


def _cooled_prek(root: Path, httpserver: HTTPServer) -> subprocess.CompletedProcess[str]:
    fake = root / "prek"
    fake.write_text('#!/bin/sh\ncat "${UV_CONFIG_FILE:-/dev/null}" >config\n')
    fake.chmod(0o755)
    _fake_uv(root, httpserver)
    return subprocess.run(
        [str(SCRIPT), "install-hooks"],
        cwd=root,
        env=os.environ | {"PATH": f"{root}{os.pathsep}{os.environ['PATH']}", "NO_PROXY": "localhost,127.0.0.1"},
        capture_output=True,
        text=True,
        check=False,
    )


def _uploaded(days: int) -> datetime:
    return datetime.now(UTC).replace(microsecond=0) - timedelta(days=days)


def _stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _simple(httpserver: HTTPServer, releases: dict[str, datetime]) -> None:
    # One wheel per release on the Simple JSON page of simplint, uploaded at the given time.
    files = [
        {"filename": f"simplint-{version}-py3-none-any.whl", "upload-time": uploaded.isoformat()}
        for version, uploaded in releases.items()
    ]
    httpserver.expect_request("/simple/simplint/").respond_with_json({"meta": {"api-version": "1.0"}, "files": files})


def _admitted(uploaded: datetime) -> str:
    return f'"simplint" = "{_stamp(uploaded + timedelta(seconds=1))}"'


PIN_SOURCES = [
    pytest.param({"setup.py": 'setup(install_requires=["simplint==0.7.1"])\n'}, {"language": "python"}, id="setup-py"),
    pytest.param(
        {"setup.py": 'SIMPLINT_VERSION = "0.7.1"\nsetup(install_requires=[f"simplint=={SIMPLINT_VERSION}"])\n'},
        {"language": "python"},
        id="setup-py-fstring",
    ),
    pytest.param(
        {
            "setup.py": 'VERSION = SIMPLINT_VERSION = "0.7.1"\nsetup(install_requires=[f"simplint=={SIMPLINT_VERSION}"])\n'
        },
        {"language": "python"},
        id="setup-py-chained-fstring",
    ),
    pytest.param(
        {"setup.cfg": "[options]\ninstall_requires =\n    simplint==0.7.1\n"}, {"language": "python"}, id="setup-cfg"
    ),
    pytest.param(
        {"pyproject.toml": '[project]\nname = "hook"\ndependencies = ["simplint==0.7.1"]\n'},
        {"language": "python"},
        id="pyproject",
    ),
    pytest.param(
        {
            "setup.py": 'setup(install_requires=["simplint==0.7.1"])\n',
            ".pre-commit-hooks.yaml": "- id: simplint\n  language: python\n  entry: simplint\n",
        },
        {},
        id="language-from-manifest",
    ),
    pytest.param(
        {}, {"language": "python", "additional_dependencies": ["simplint==0.7.1"]}, id="additional-dependencies"
    ),
    pytest.param(
        {"setup.py": 'setup(install_requires=["simplint[socks]==0.7.1; python_version>=3.10"])\n'},
        {"language": "python"},
        id="extras-and-marker",
    ),
]


@pytest.mark.parametrize(("files", "hook"), PIN_SOURCES)
def test_cooled_prek_admits_pin_up_to_its_upload(
    tmp_path: Path, httpserver: HTTPServer, files: dict[str, str], hook: dict[str, object]
) -> None:
    uploaded = _uploaded(1)
    _simple(httpserver, {"0.7.1": uploaded})
    _config(tmp_path, _hook_repo(tmp_path, files), hook)

    result = _cooled_prek(tmp_path, httpserver)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "config").read_text().splitlines() == ["[exclude-newer-package]", _admitted(uploaded)]
    assert _admitted(uploaded) in result.stdout


@pytest.mark.parametrize(
    ("files", "hook"),
    [
        pytest.param({}, {"language": "python", "additional_dependencies": ["simplint>=0.7"]}, id="range"),
        pytest.param(
            {"setup.py": 'setup(install_requires=["simplint>=0.7"])\n'}, {"language": "python"}, id="metadata-range"
        ),
        pytest.param({}, {"language": "system", "additional_dependencies": ["simplint==0.7.1"]}, id="non-python-hook"),
        pytest.param(
            {"setup.py": 'setup(install_requires=["simplint==0.7.1"])\n'},
            {"language": "system"},
            id="non-python-metadata",
        ),
        pytest.param(
            {"setup.py": 'VERSION = "0.7.1"\nsetup(install_requires=[VERSION])\n'},
            {"language": "python"},
            id="nonliteral-requirement",
        ),
        pytest.param(
            {"setup.py": 'setup(install_requires=[f"simplint=={VERSION}"])\n'},
            {"language": "python"},
            id="unknown-fstring-value",
        ),
        pytest.param(
            {"setup.py": 'settings.VERSION = "0.7.1"\nsetup(install_requires=[f"simplint=={VERSION}"])\n'},
            {"language": "python"},
            id="attribute-constant",
        ),
        pytest.param(
            {"setup.py": 'setup(install_requires=[f"simplint=={version()}"])\n'},
            {"language": "python"},
            id="dynamic-fstring-value",
        ),
        pytest.param(
            {"setup.py": 'VERSION = "0.7.1"\nsetup(install_requires=[f"simplint=={VERSION!r}"])\n'},
            {"language": "python"},
            id="formatted-fstring-value",
        ),
        pytest.param(
            {"setup.py": 'setup(extras_require={"test": ["simplint==0.7.1"]}, tests_require=["simplint==0.7.1"])\n'},
            {"language": "python"},
            id="dev-extras",
        ),
        pytest.param(
            {"setup.cfg": "[options.extras_require]\ntest =\n    simplint==0.7.1\n"},
            {"language": "python"},
            id="dev-setup-cfg",
        ),
        pytest.param(
            {
                "pyproject.toml": (
                    '[project.optional-dependencies]\ntest = ["simplint==0.7.1"]\n'
                    '[dependency-groups]\ndev = ["simplint==0.7.1"]\n'
                )
            },
            {"language": "python"},
            id="dev-pyproject",
        ),
    ],
)
def test_cooled_prek_leaves_ranges_dev_pins_and_non_python_hooks_cooled(
    tmp_path: Path, httpserver: HTTPServer, files: dict[str, str], hook: dict[str, object]
) -> None:
    _config(tmp_path, _hook_repo(tmp_path, files), hook)

    result = _cooled_prek(tmp_path, httpserver)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "config").read_text() == ""
    assert httpserver.log == []


def test_cooled_prek_does_not_admit_newer_release(tmp_path: Path, httpserver: HTTPServer) -> None:
    pinned = _uploaded(2)
    _simple(httpserver, {"0.7.1": pinned, "0.8.0": _uploaded(1)})
    _config(
        tmp_path,
        _hook_repo(tmp_path, {"setup.py": 'setup(install_requires=["simplint==0.7.1"])\n'}),
        {"language": "python"},
    )

    result = _cooled_prek(tmp_path, httpserver)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "config").read_text().splitlines() == ["[exclude-newer-package]", _admitted(pinned)]


def test_cooled_prek_does_not_write_pin_older_than_window(tmp_path: Path, httpserver: HTTPServer) -> None:
    _simple(httpserver, {"0.7.1": _uploaded(8)})
    _config(
        tmp_path,
        _hook_repo(tmp_path, {"setup.py": 'setup(install_requires=["simplint==0.7.1"])\n'}),
        {"language": "python"},
    )

    result = _cooled_prek(tmp_path, httpserver)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "config").read_text() == ""


@pytest.mark.parametrize(
    ("nab", "expected"),
    [
        pytest.param("{later}", "{later}", id="toml-datetime-later-wins"),
        pytest.param("{earlier}", "pin", id="toml-datetime-earlier-loses"),
        pytest.param('"{later}"', "{later}", id="string-later-wins"),
        pytest.param('"{earlier}"', "pin", id="string-earlier-loses"),
        pytest.param('"P3D"', "pin", id="duration-loses-to-pin"),
    ],
)
def test_cooled_prek_compares_nab_exception_with_pin(
    tmp_path: Path, httpserver: HTTPServer, nab: str, expected: str
) -> None:
    pinned = _uploaded(2)
    later, earlier = _stamp(pinned + timedelta(days=1)), _stamp(pinned - timedelta(days=1))
    _simple(httpserver, {"0.7.1": pinned})
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.nab]\npackages.simplint.uploaded-prior-to = {nab.format(later=later, earlier=earlier)}\n"
    )
    _config(
        tmp_path,
        _hook_repo(tmp_path, {"setup.py": 'setup(install_requires=["simplint==0.7.1"])\n'}),
        {"language": "python"},
    )

    result = _cooled_prek(tmp_path, httpserver)

    assert result.returncode == 0, result.stderr
    value = _admitted(pinned) if expected == "pin" else f'"simplint" = "{expected.format(later=later)}"'
    assert (tmp_path / "config").read_text().splitlines() == ["[exclude-newer-package]", value]


def test_cooled_prek_keeps_nab_duration_without_pin(tmp_path: Path, httpserver: HTTPServer) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.nab]\npackages.sphinx.uploaded-prior-to = "P3D"\n')
    _config(tmp_path, _hook_repo(tmp_path, {}), {"language": "python"})

    result = _cooled_prek(tmp_path, httpserver)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "config").read_text().splitlines() == ["[exclude-newer-package]", '"sphinx" = "P3D"']


def test_cooled_prek_ignores_local_hooks(tmp_path: Path, httpserver: HTTPServer) -> None:
    (tmp_path / ".pre-commit-config.yaml").write_text(
        yaml.safe_dump({"repos": [{"repo": "local", "hooks": []}, {"repo": "meta", "hooks": []}]})
    )

    result = _cooled_prek(tmp_path, httpserver)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "config").read_text() == ""
    assert httpserver.log == []


@pytest.mark.parametrize(
    ("status", "error"),
    [
        pytest.param(404, "cannot read simplint from PyPI", id="unknown-project"),
        pytest.param(200, "PyPI has no files for simplint==0.7.1", id="version-missing"),
    ],
)
def test_cooled_prek_fails_when_pin_cannot_be_looked_up(
    tmp_path: Path, httpserver: HTTPServer, status: int, error: str
) -> None:
    if status == 404:
        httpserver.expect_request("/simple/simplint/").respond_with_data("", status=404)
    else:
        _simple(httpserver, {"0.6.0": _uploaded(1)})
    repo = _hook_repo(tmp_path, {"setup.py": 'setup(install_requires=["simplint==0.7.1"])\n'})
    _config(tmp_path, repo, {"language": "python"})

    result = _cooled_prek(tmp_path, httpserver)

    assert result.returncode != 0
    assert error in result.stderr
    assert str(repo) in result.stderr


def test_cooled_prek_fails_when_hook_repo_cannot_be_fetched(tmp_path: Path, httpserver: HTTPServer) -> None:
    _config(tmp_path, tmp_path / "missing", {"language": "python"})

    result = _cooled_prek(tmp_path, httpserver)

    assert result.returncode != 0
    assert "cannot fetch v1.0.0 of" in result.stderr
