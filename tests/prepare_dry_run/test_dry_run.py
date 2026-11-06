import pytest
from conftest import WORKFLOWS, at, load_yaml, mapping


@pytest.mark.parametrize("workflow", ["prepare-release-creator.yaml", "prepare-towncrier-release.yaml"])
def test_dry_run_assembles_without_pushing(workflow: str) -> None:
    document = load_yaml(WORKFLOWS / workflow)

    assert at(document, "on", "workflow_call", "inputs", "dry-run", "default") == "false"
    assert at(document, "on", "workflow_call", "secrets", "RELEASE_APP_PRIVATE_KEY", "required") == "false"
    assert at(document, "jobs", "push", "if") == "${{ !inputs.dry-run }}"
    assert "if" not in mapping(at(document, "jobs", "assemble"))
    assert at(document, "concurrency", "group") == (
        "prepare-release-${{ github.repository }}${{ inputs.dry-run && format('-dry-run-{0}', github.ref) || '' }}"
    )
