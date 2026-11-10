import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import WORKFLOWS, JsonObject, at, load_yaml, mapping, step, steps, text


@pytest.fixture(scope="module")
def workflow() -> JsonObject:
    return load_yaml(WORKFLOWS / "prepare-release-creator.yaml")


def test_assemble_holds_no_write_token(workflow: JsonObject) -> None:
    assert at(workflow, "jobs", "assemble", "permissions") == {"contents": "read", "pull-requests": "read"}
    assert at(workflow, "jobs", "push", "permissions") == {"contents": "read"}


def test_push_validates_before_minting_the_token(workflow: JsonObject) -> None:
    names = [item.get("name") for item in steps(workflow, "push")]

    assert names.index("⏳ Wait for release patch") < names.index("⚙️ Apply release patch")
    assert names.index("⚙️ Apply release patch") < names.index("🔑 Create release App token")
    assert names[-1] == "🏷️ Commit and tag release"


def test_push_passes_resolved_release_paths_to_the_validator(workflow: JsonObject) -> None:
    validate = next(item for item in steps(workflow, "push") if item.get("uses") == "$/validate-release-patch")

    assert validate["with"] == {"allowed-paths": "${{ needs.assemble.outputs.release-paths }}"}


def test_uses_its_own_actions(workflow: JsonObject) -> None:
    uses = [text(item["uses"]) for job in mapping(workflow["jobs"]) for item in steps(workflow, job) if "uses" in item]

    assert {value for value in uses if value.startswith("$/")} == {
        "$/install-locked-tools",
        "$/cooled-prek",
        "$/validate-release-patch",
        "$/commit-and-tag",
    }


def test_inputs_match_the_documented_contract(workflow: JsonObject) -> None:
    inputs = mapping(at(workflow, "on", "workflow_call", "inputs"))

    assert at(inputs, "tag-format", "default") == "{version}"
    assert at(inputs, "package", "default") == ""
    assert at(inputs, "assemble-command", "required") == "true"
    assert at(inputs, "release-paths", "required") == "true"
    assert at(inputs, "cargo-set-version", "default") == "false"
    assert at(inputs, "cargo-set-version-args", "default") == ""
    assert at(inputs, "changelog", "default") == "CHANGELOG.md"


def test_cargo_tools_install_only_for_a_cargo_bump(workflow: JsonObject) -> None:
    cargo = [item for item in steps(workflow, "assemble") if text(item.get("name", "")).startswith("🦀")]

    assert [item["name"] for item in cargo] == ["🦀 Install Rust toolchain", "🦀 Install cargo-edit"]
    assert all(item["if"] == "${{ inputs.cargo-set-version }}" for item in cargo)


def test_format_retries_once_when_mdformat_rewrites(workflow: JsonObject) -> None:
    first = step(workflow, "assemble", "🧹 Format changelog")
    second = step(workflow, "assemble", "🧹 Confirm changelog format")

    assert first["continue-on-error"] == "true"
    assert second["if"] == "${{ steps.format.outcome == 'failure' }}"
    assert at(first, "with", "args") == at(second, "with", "args")


def test_unscoped_version_is_bare(repository: Path, tmp_path: Path, workflow: JsonObject) -> None:
    result = _run_version(repository, tmp_path, workflow)

    assert result.returncode == 0, result.stderr
    assert _outputs(tmp_path / "output")["version"] == "1.1.0"
    assert _outputs(tmp_path / "output")["number"] == "1.1.0"


def test_v_prefixed_tag_keeps_the_number_bare(repository: Path, tmp_path: Path, workflow: JsonObject) -> None:
    result = _run_version(repository, tmp_path, workflow, TAG_FORMAT="v{version}")

    assert result.returncode == 0, result.stderr
    assert _outputs(tmp_path / "output")["version"] == "v1.1.0"
    assert _outputs(tmp_path / "output")["number"] == "1.1.0"


def test_scoped_tag_uses_the_package_and_its_own_history(
    repository: Path, tmp_path: Path, workflow: JsonObject
) -> None:
    result = _run_version(
        repository, tmp_path, workflow, PACKAGE="pyproject-fmt", BUMP="patch", TAG_FORMAT="{package}/{version}"
    )

    assert result.returncode == 0, result.stderr
    assert _outputs(tmp_path / "output")["version"] == "pyproject-fmt/1.0.4"


def test_scoped_v_tag_keeps_the_v_inside_the_package_path(
    repository: Path, tmp_path: Path, workflow: JsonObject
) -> None:
    result = _run_version(
        repository, tmp_path, workflow, PACKAGE="pyproject-fmt", BUMP="patch", TAG_FORMAT="{package}/v{version}"
    )

    assert result.returncode == 0, result.stderr
    assert _outputs(tmp_path / "output")["version"] == "pyproject-fmt/v1.0.4"


def test_release_paths_expand_the_package(repository: Path, tmp_path: Path, workflow: JsonObject) -> None:
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
    repository: Path, tmp_path: Path, workflow: JsonObject, environment: dict[str, str], message: str
) -> None:
    result = _run_version(repository, tmp_path, workflow, **environment)

    assert result.returncode != 0
    assert message in result.stderr


def _run_version(
    repository: Path, tmp_path: Path, workflow: JsonObject, **environment: str
) -> subprocess.CompletedProcess[str]:
    script = text(step(workflow, "assemble", "🏷️ Select release version")["run"])
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
