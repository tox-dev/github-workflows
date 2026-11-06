from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import action


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


def test_cooled_prek_action_passes_each_argument(tmp_path: Path, action_scripts: Path) -> None:
    fake = tmp_path / "bin/prek"
    fake.parent.mkdir()
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >"$RUNNER_TEMP/args"\n')
    fake.chmod(0o755)

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
        pytest.param(["run", "mdformat", "--files", "CHANGELOG.md"], ["install-hooks", "mdformat"], id="named-hook"),
    ],
)
def test_cooled_prek_builds_hooks_cooled_and_runs_them_with_the_caller_environment(
    tmp_path: Path, arguments: list[str], install: list[str]
) -> None:
    fake = tmp_path / "prek"
    fake.write_text(
        '#!/bin/sh\nn=$(ls calls 2>/dev/null | wc -l)\nmkdir -p calls/$n\nprintf "%s\\n" "$@" >calls/$n/args\nenv >calls/$n/env\n'
    )
    fake.chmod(0o755)
    leaked = dict.fromkeys(("UV_INDEX_URL", "UV_EXCLUDE_NEWER_PACKAGE", "UV_SYSTEM_CERTS", "SSL_CERT_FILE"), "leak")

    subprocess.run(
        [str(Path(__file__).resolve().parents[2] / "tools/cooled_prek.sh"), *arguments],
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


def test_cooled_prek_admits_nab_cutoff_exceptions(tmp_path: Path) -> None:
    fake = tmp_path / "prek"
    fake.write_text('#!/bin/sh\ncat "$UV_CONFIG_FILE" >config\n')
    fake.chmod(0o755)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.nab]\nuploaded-prior-to = "P7D"\npackages.sphinx.uploaded-prior-to = 2026-10-21T00:05:13Z\n'
        'packages.release-creator.uploaded-prior-to = "2026-10-26T18:24:46Z"\npackages.uv.decision-order = "stable"\n'
    )

    subprocess.run(
        [str(Path(__file__).resolve().parents[2] / "tools/cooled_prek.sh"), "install-hooks"],
        cwd=tmp_path,
        env=os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"},
        check=True,
    )

    assert (tmp_path / "config").read_text().splitlines() == [
        "[exclude-newer-package]",
        '"release-creator" = "2026-10-26T18:24:46Z"',
        '"sphinx" = "2026-10-21T00:05:13Z"',
    ]


def test_cooled_prek_without_exceptions_sets_no_config_file(tmp_path: Path) -> None:
    fake = tmp_path / "prek"
    fake.write_text('#!/bin/sh\nprintf "%s" "${UV_CONFIG_FILE-unset}" >config\n')
    fake.chmod(0o755)
    (tmp_path / "pyproject.toml").write_text('[tool.nab]\nuploaded-prior-to = "P7D"\n')

    subprocess.run(
        [str(Path(__file__).resolve().parents[2] / "tools/cooled_prek.sh"), "install-hooks"],
        cwd=tmp_path,
        env=os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}", "UV_CONFIG_FILE": "/leak/uv.toml"},
        check=True,
    )

    assert (tmp_path / "config").read_text() == "unset"
