"""Insert the New Contributors list from GitHub's generated notes ahead of the trailing link rows of a release body."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Final

_FIRST_CONTRIBUTION: Final = re.compile(r"^\* (@\S+) made their first contribution in (\S+)$")
_LINK_ROW: Final = re.compile(r"^\[[^\]]+\]\(\S+\)(, \[[^\]]+\]\(\S+\))*$")


def main() -> None:
    notes, generated, output = (Path(argument) for argument in sys.argv[1:4])
    credits = [
        f"- {match[1]} made their first contribution in {match[2]}"
        for line in generated.read_text(encoding="utf-8").splitlines()
        if (match := _FIRST_CONTRIBUTION.match(line.strip())) and not match[1].endswith("[bot]")
    ]
    body = notes.read_text(encoding="utf-8")
    if credits:
        paragraphs = body.strip().split("\n\n")
        links = len(paragraphs)
        while links and _LINK_ROW.match(paragraphs[links - 1].strip()):
            links -= 1
        section = "### New Contributors\n\n" + "\n".join(credits)
        body = "\n\n".join([*paragraphs[:links], section, *paragraphs[links:]]) + "\n"
    output.write_text(body, encoding="utf-8")
    names = ", ".join(credit.split()[1] for credit in credits)
    print(f"New Contributors: {names}" if credits else "New Contributors: none in GitHub's generated notes")


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]
