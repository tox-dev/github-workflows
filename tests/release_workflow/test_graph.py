from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(
    ("version", "prefix", "accepted"),
    [
        pytest.param("1.2.3", "", True, id="calculated-version"),
        pytest.param("v1.2.3", "v", True, id="prefixed-version"),
        pytest.param("9.9.9", "", False, id="forged-version"),
    ],
)
def test_prepare_validation_calculates_version_independently(
    tmp_path: Path, version: str, prefix: str, accepted: bool
) -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/prepare-towncrier-release.yaml").read_text()
    )
    steps = workflow["jobs"]["validate"]["steps"]
    verify = next(step for step in steps if step.get("name") == "Verify selected release version")
    command = tmp_path / "bin/release-creator"
    command.parent.mkdir()
    expected_arguments = ["tags", "--next", "auto", "--directory", "changelog.d"]
    if prefix:
        expected_arguments.extend(["--prefix", prefix])
    command.write_text(
        f"#!{sys.executable}\nimport sys\nassert sys.argv[1:] == {expected_arguments!r}\n"
        f"assert sys.stdin.read() == {f'{prefix}1.2.2' + chr(10)!r}\nprint({f'{prefix}1.2.3'!r})\n"
    )
    command.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.org",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        ],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "tag", f"{prefix}1.2.2"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", verify["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{command.parent}{os.pathsep}{os.environ['PATH']}",
            "BUMP": "auto",
            "TAG_PREFIX": prefix,
            "FRAGMENTS": "changelog.d",
            "VERSION": version,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode == 0) is accepted
    if not accepted:
        assert "assembled release version differs from 1.2.3" in result.stderr


def test_local_release_creator_builds_with_locked_backends(tmp_path: Path) -> None:
    step = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "install-local-release-creator/action.yml").read_text()
    )["runs"]["steps"][0]
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (fake_bin / "uv").write_text(
        '#!/bin/sh\necho "$@" >>"$RUNNER_TEMP/uv-calls"\n'
        'if [ "$1" = build ]; then mkdir -p "$RUNNER_TEMP/local-tool-dist" && touch "$RUNNER_TEMP/local-tool-dist/x.whl"; fi\n'
    )
    (fake_bin / "uv").chmod(0o755)
    command = tmp_path / ".venv/bin/release-creator"
    command.parent.mkdir(parents=True)
    command.symlink_to(sys.executable)
    output = tmp_path / "github-path"

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env=os.environ
        | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "BUILD_CONSTRAINTS": "constraints.txt",
            "GITHUB_WORKSPACE": str(tmp_path),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_PATH": str(output),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    build, install = (tmp_path / "uv-calls").read_text().splitlines()
    assert "--build-constraints constraints.txt --require-build-hashes" in build
    assert install.endswith(f"--no-deps {tmp_path}/local-tool-dist/x.whl")
    overlay = Path(output.read_text().strip())
    assert [path.name for path in overlay.iterdir()] == ["release-creator"]
    assert (overlay / "release-creator").resolve() == command.resolve()


def test_release_writer_has_only_notes_and_reconciler() -> None:
    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/release.yaml").read_text())
    publish = workflow["jobs"]["publish"]
    assert publish["permissions"] == {"contents": "write"}
    assert publish["needs"] == ["check", "source", "notes"]
    assert [step["uses"] for step in publish["steps"]] == [
        "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
        "$/publish-github-release",
    ]
    assert publish["steps"][-1]["with"]["commit"] == "${{ needs.source.outputs.commit }}"
    assert publish["steps"][0]["with"]["artifact-ids"] == "${{ needs.notes.outputs.artifact-id }}"


def test_shfmt_hook_rejects_unformatted_inline_shell(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    script = tmp_path / "inline-shell-check.sh"
    script.write_text("#!/usr/bin/env bash\nif true\nthen\necho x\nfi\n")
    executable = shutil.which("prek")
    assert executable is not None
    result = subprocess.run(
        [
            executable,
            "run",
            "shfmt",
            "--config",
            str(Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"),
            "--files",
            str(script),
        ],
        cwd=tmp_path,
        env={name: os.environ[name] for name in ("HOME", "PATH")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "diff" in result.stdout


def test_action_manifests_have_no_empty_environment_mapping() -> None:
    root = Path(__file__).resolve().parents[2]
    for path in root.glob("*/action.yml"):
        action = yaml.safe_load(path.read_text())
        assert all("env" not in step or isinstance(step["env"], dict) for step in action["runs"]["steps"]), path
