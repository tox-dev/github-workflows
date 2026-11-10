import re
from pathlib import Path
from typing import Final

import pytest
from conftest import WORKFLOWS, at, load_yaml, mapping, text

LOCK: Final = load_yaml(WORKFLOWS / "actions.lock")


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS.glob("*.yaml")), ids=lambda path: path.name)
def test_every_external_action_is_locked(workflow: Path) -> None:
    references = re.findall(r"^\s*(?:- )?uses: (\S+)", workflow.read_text(), re.MULTILINE)
    # the lockfile keys an action by its repository in lowercase, so codeql-action/init and PyO3 match their entries
    external = {
        re.sub(r"^([^/]+/[^/@]+)[^@]*@", r"\1@", value).lower() for value in references if not value.startswith("$/")
    }
    listed = at(LOCK, "workflows", f".github/workflows/{workflow.name}")
    assert isinstance(listed, list)
    locked = {text(value).lower() for value in listed}

    assert external <= locked
    assert external <= {value.lower() for value in mapping(at(LOCK, "dependencies"))}


@pytest.mark.parametrize("action", sorted(mapping(at(LOCK, "dependencies"))))
def test_every_locked_action_pins_an_exact_tag_to_a_commit(action: str) -> None:
    entry = mapping(at(LOCK, "dependencies", action))

    assert re.fullmatch(r"v?\d+\.\d+\.\d+", text(entry["ref"])), entry
    assert re.fullmatch(r"sha1-[0-9a-f]{40}", text(entry["commit"])), entry
