import re
from typing import Final

import pytest
from conftest import WORKFLOWS, JsonObject, load_yaml, mapping

ROOT: Final = WORKFLOWS.parents[1]
CATALOG_ROW: Final = re.compile(
    r"^\| `(?P<unit>[\w.-]+)` +\|.*\]\((?P<page>docs/[\w-]+\.md)(?:#(?P<anchor>[\w-]+))?\) *\|$"
)
HEADING: Final = re.compile(r"^(?P<level>#+) (?P<title>.+)$")


def _reusable_workflows() -> dict[str, JsonObject]:
    documents = {path.name: load_yaml(path) for path in sorted(WORKFLOWS.glob("*.yaml"))}
    # The repository's own callers also take workflow_call, but add other triggers.
    return {
        name: mapping(mapping(document["on"])["workflow_call"] or {})
        for name, document in documents.items()
        if set(mapping(document["on"])) == {"workflow_call"}
    }


def _actions() -> dict[str, JsonObject]:
    return {path.parent.name: load_yaml(path) for path in sorted(ROOT.glob("*/action.yml"))}


INTERFACES: Final = _reusable_workflows() | _actions()


def _catalog() -> dict[str, tuple[str, str | None]]:
    rows = (CATALOG_ROW.match(line) for line in (ROOT / "README.md").read_text().splitlines())
    return {row["unit"]: (row["page"], row["anchor"]) for row in rows if row}


def _slug(title: str) -> str:
    return re.sub(r"[^\w\- ]", "", title.strip().lower()).replace(" ", "-")


def _section(page: str, anchor: str | None) -> str:
    lines = (ROOT / page).read_text().splitlines()
    if anchor is None:
        return "\n".join(lines)
    headings = [(index, match) for index, line in enumerate(lines) if (match := HEADING.match(line))]
    start, level = next((index, len(match["level"])) for index, match in headings if _slug(match["title"]) == anchor)
    end = next((index for index, match in headings if index > start and len(match["level"]) <= level), len(lines))
    return "\n".join(lines[start:end])


def test_catalog_lists_every_workflow_and_action() -> None:
    assert sorted(_catalog()) == sorted(INTERFACES)


@pytest.mark.parametrize("unit", sorted(INTERFACES))
def test_reference_names_every_input_output_and_secret(unit: str) -> None:
    interface = INTERFACES[unit]
    names = {name for key in ("inputs", "outputs", "secrets") for name in mapping(interface.get(key) or {})}
    section = _section(*_catalog()[unit])
    assert {name for name in names if f"`{name}`" not in section} == set()
