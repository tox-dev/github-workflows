from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def workflow() -> dict[Any, Any]:
    return yaml.safe_load((ROOT / ".github/workflows/prepare-release-creator.yaml").read_text())


def step(workflow: dict[Any, Any], job: str, name: str) -> dict[Any, Any]:
    return next(item for item in workflow["jobs"][job]["steps"] if item.get("name") == name)


def test_assemble_holds_no_write_token(workflow: dict[Any, Any]) -> None:
    assert workflow["jobs"]["assemble"]["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert workflow["jobs"]["push"]["permissions"] == {"contents": "read"}


def test_push_validates_before_minting_the_token(workflow: dict[Any, Any]) -> None:
    names = [item.get("name") for item in workflow["jobs"]["push"]["steps"]]

    assert names.index("⚙️ Apply release patch") < names.index("🔑 Create release App token")
    assert names[-1] == "🏷️ Commit and tag release"


def test_push_passes_resolved_release_paths_to_the_validator(workflow: dict[Any, Any]) -> None:
    validate = next(
        item for item in workflow["jobs"]["push"]["steps"] if item.get("uses") == "$/validate-release-patch"
    )

    assert validate["with"] == {"allowed-paths": "${{ needs.assemble.outputs.release-paths }}"}


def test_every_external_action_is_sha_pinned(workflow: dict[Any, Any]) -> None:
    uses = [item["uses"] for job in workflow["jobs"].values() for item in job["steps"] if "uses" in item]
    local = {value for value in uses if value.startswith("$/")}

    assert local == {
        "$/install-locked-tools",
        "$/cooled-prek",
        "$/validate-release-patch",
        "$/commit-and-tag",
    }
    assert all("@" in value and len(value.rsplit("@", 1)[1]) == 40 for value in uses if value not in local)


def test_inputs_match_the_documented_contract(workflow: dict[Any, Any]) -> None:
    inputs = workflow[True]["workflow_call"]["inputs"]

    assert inputs["tag-format"]["default"] == "{version}"
    assert inputs["package"]["default"] == ""
    assert inputs["assemble-command"]["required"] is True
    assert inputs["release-paths"]["required"] is True
    assert inputs["cargo-set-version"]["default"] is False
    assert inputs["cargo-set-version-args"]["default"] == ""
    assert inputs["changelog"]["default"] == "CHANGELOG.md"


def test_cargo_tools_install_only_for_a_cargo_bump(workflow: dict[Any, Any]) -> None:
    gated = [item["name"] for item in workflow["jobs"]["assemble"]["steps"] if item.get("name", "").startswith("🦀")]

    assert gated == ["🦀 Install Rust toolchain", "🦀 Install cargo-edit"]
    assert all(
        item["if"] == "${{ inputs.cargo-set-version }}"
        for item in workflow["jobs"]["assemble"]["steps"]
        if item.get("name", "").startswith("🦀")
    )


def test_format_retries_once_when_mdformat_rewrites(workflow: dict[Any, Any]) -> None:
    first = step(workflow, "assemble", "🧹 Format changelog")
    second = step(workflow, "assemble", "🧹 Confirm changelog format")

    assert first["continue-on-error"] is True
    assert second["if"] == "${{ steps.format.outcome == 'failure' }}"
    assert first["with"]["args"] == second["with"]["args"]


def _run_version(
    repository: Path, tmp_path: Path, workflow: dict[Any, Any], **environment: str
) -> subprocess.CompletedProcess[str]:
    script = step(workflow, "assemble", "🏷️ Select release version")["run"]
    output = tmp_path / "output"
    output.touch()
    values = {"BUMP": "minor", "PACKAGE": "", "TAG_FORMAT": "{version}", "CHANGELOG": "CHANGELOG.md"} | environment
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=repository,
        env={
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_OUTPUT": str(output),
            "RELEASE_PATHS": "CHANGELOG.md",
        }
        | values,
        text=True,
        capture_output=True,
        check=False,
    )


def _outputs(path: Path) -> dict[str, str]:
    scalars, _, paths = path.read_text().partition("release-paths<<RELEASE_PATHS_EOF\n")
    values = dict(line.split("=", 1) for line in scalars.splitlines())
    values["release-paths"] = paths.removesuffix("RELEASE_PATHS_EOF\n").removesuffix("\n")
    return values


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org"]
    subprocess.run([*git, "init", "-q", "-b", "main", str(root)], check=True)
    (root / "CHANGELOG.md").write_text("# Changelog\n")
    subprocess.run([*git, "-C", str(root), "add", "."], check=True)
    subprocess.run([*git, "-C", str(root), "commit", "-qm", "init"], check=True)
    for tag in ("1.0.0", "pyproject-fmt/1.0.0", "pyproject-fmt/1.0.3"):
        subprocess.run([*git, "-C", str(root), "tag", tag], check=True)
    return root


def test_unscoped_version_is_bare(repository: Path, tmp_path: Path, workflow: dict[Any, Any]) -> None:
    result = _run_version(repository, tmp_path, workflow)

    assert result.returncode == 0, result.stderr
    assert _outputs(tmp_path / "output")["version"] == "1.1.0"
    assert _outputs(tmp_path / "output")["number"] == "1.1.0"


def test_v_prefixed_tag_keeps_the_number_bare(repository: Path, tmp_path: Path, workflow: dict[Any, Any]) -> None:
    result = _run_version(repository, tmp_path, workflow, TAG_FORMAT="v{version}")

    assert result.returncode == 0, result.stderr
    assert _outputs(tmp_path / "output")["version"] == "v1.1.0"
    assert _outputs(tmp_path / "output")["number"] == "1.1.0"


def test_scoped_tag_uses_the_package_and_its_own_history(
    repository: Path, tmp_path: Path, workflow: dict[Any, Any]
) -> None:
    result = _run_version(
        repository, tmp_path, workflow, PACKAGE="pyproject-fmt", BUMP="patch", TAG_FORMAT="{package}/{version}"
    )

    assert result.returncode == 0, result.stderr
    assert _outputs(tmp_path / "output")["version"] == "pyproject-fmt/1.0.4"


def test_scoped_v_tag_keeps_the_v_inside_the_package_path(
    repository: Path, tmp_path: Path, workflow: dict[Any, Any]
) -> None:
    result = _run_version(
        repository, tmp_path, workflow, PACKAGE="pyproject-fmt", BUMP="patch", TAG_FORMAT="{package}/v{version}"
    )

    assert result.returncode == 0, result.stderr
    assert _outputs(tmp_path / "output")["version"] == "pyproject-fmt/v1.0.4"


def test_release_paths_expand_the_package(repository: Path, tmp_path: Path, workflow: dict[Any, Any]) -> None:
    result = _run_version(
        repository,
        tmp_path,
        workflow,
        PACKAGE="pyproject-fmt",
        BUMP="patch",
        TAG_FORMAT="{package}/{version}",
        RELEASE_PATHS="CHANGELOG.md\n{package}/Cargo.toml\nchangelog.d/{package}/*",
    )

    assert result.returncode == 0, result.stderr
    assert _outputs(tmp_path / "output")["release-paths"] == (
        "CHANGELOG.md\npyproject-fmt/Cargo.toml\nchangelog.d/pyproject-fmt/*"
    )


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        pytest.param({"TAG_FORMAT": "release-{version}"}, "unsupported tag-format", id="unknown-format"),
        pytest.param({"PACKAGE": "pyproject-fmt"}, "names no package", id="package-without-scope"),
        pytest.param({"TAG_FORMAT": "{package}/{version}"}, "needs a package input", id="scope-without-package"),
    ],
)
def test_bad_tag_format_stops_before_tagging(
    repository: Path, tmp_path: Path, workflow: dict[Any, Any], environment: dict[str, str], message: str
) -> None:
    result = _run_version(repository, tmp_path, workflow, **environment)

    assert result.returncode != 0
    assert message in result.stderr
