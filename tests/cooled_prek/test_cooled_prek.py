from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml


def test_every_hook_run_uses_the_root_config() -> None:
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

    assert commands
    assert all("--config" in command for command in commands), commands


def test_prepare_hook_install_uses_install_time_cutoff() -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    step = next(step for step in workflow["jobs"]["assemble"]["steps"] if step.get("name") == "Install prek hooks")
    script = (Path(__file__).resolve().parents[2] / "tools/cooled_prek.sh").read_text()

    assert {name: step["env"][name] for name in ("UV_EXCLUDE_NEWER", "UV_NO_CONFIG", "UV_NO_SOURCES")} == {
        "UV_EXCLUDE_NEWER": "7 days",
        "UV_NO_CONFIG": "1",
        "UV_NO_SOURCES": "1",
    }
    assert [line for line in step["run"].splitlines() if line.startswith("unset ")] == [
        line for line in script.splitlines() if line.startswith("unset ")
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
