from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

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


def test_prepare_hook_install_uses_cooled_prek() -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    step = next(step for step in workflow["jobs"]["assemble"]["steps"] if step.get("id") == "hooks")

    assert (step["uses"], step["with"]) == ("$/cooled-prek", {"args": "install-hooks"})


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


def test_cooled_prek_isolates_hook_installs(tmp_path: Path) -> None:
    fake = tmp_path / "prek"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >args\nenv >env\n')
    fake.chmod(0o755)
    leaked = dict.fromkeys(("UV_INDEX_URL", "UV_EXCLUDE_NEWER_PACKAGE", "UV_SYSTEM_CERTS", "SSL_CERT_FILE"), "leak")

    subprocess.run(
        [str(Path(__file__).resolve().parents[2] / "tools/cooled_prek.sh"), "run", "--all-files"],
        cwd=tmp_path,
        env=os.environ | leaked | {"PATH": f"{tmp_path}:{os.environ['PATH']}", "UV_EXCLUDE_NEWER": "1 day"},
        check=True,
    )

    assert (tmp_path / "args").read_text().splitlines() == ["--config", ".pre-commit-config.yaml", "run", "--all-files"]
    environment = dict(line.split("=", 1) for line in (tmp_path / "env").read_text().splitlines() if "=" in line)
    assert {name: environment.get(name) for name in ("UV_EXCLUDE_NEWER", "UV_NO_CONFIG", "UV_NO_SOURCES")} == {
        "UV_EXCLUDE_NEWER": "7 days",
        "UV_NO_CONFIG": "1",
        "UV_NO_SOURCES": "1",
    }
    assert not leaked.keys() & environment.keys()
