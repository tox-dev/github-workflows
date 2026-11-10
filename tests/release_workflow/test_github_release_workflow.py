import pytest
from conftest import WORKFLOWS, JsonObject, at, load_yaml, step, steps


@pytest.fixture(scope="module")
def workflow() -> JsonObject:
    return load_yaml(WORKFLOWS / "github-release.yaml")


def test_github_release_publishes_from_a_release_environment_only(workflow: JsonObject) -> None:
    assert at(workflow, "jobs", "github-release", "environment") == "release"
    assert at(workflow, "jobs", "github-release", "permissions") == {"contents": "write"}
    assert at(workflow, "permissions") == {}


def test_github_release_verifies_pypi_before_publishing(workflow: JsonObject) -> None:
    names = [item["name"] for item in steps(workflow, "github-release")]

    assert names == [
        "📩 Download distributions",
        "📩 Download release notes",
        "🐍 Install uv and Python",
        "⏳ Wait for distributions",
        "⏳ Wait for release notes",
        "🔍 Verify PyPI artifacts",
        "🚀 Publish GitHub release",
    ]
    assert step(workflow, "github-release", "📩 Download distributions")["background"] == "true"
    assert step(workflow, "github-release", "📩 Download release notes")["background"] == "true"


def test_github_release_verifies_the_requested_version(workflow: JsonObject) -> None:
    verify = step(workflow, "github-release", "🔍 Verify PyPI artifacts")

    assert verify["with"] == {
        "project": "${{ inputs.project }}",
        "version": "${{ inputs.version }}",
        "dist": "dist",
        "exclude-newer": "${{ inputs.exclude-newer }}",
        "exclude-newer-package": "${{ inputs.exclude-newer-package }}",
    }


def test_github_release_title_prefixes_the_tag(workflow: JsonObject) -> None:
    publish = step(workflow, "github-release", "🚀 Publish GitHub release")

    assert publish["with"] == {
        "tag": "${{ inputs.tag }}",
        "commit": "${{ github.sha }}",
        "title": "${{ inputs.title-prefix }}${{ inputs.tag }}",
        "notes-file": "${{ runner.temp }}/release-notes.md",
        "assets-directory": "${{ inputs.assets-directory }}",
    }
