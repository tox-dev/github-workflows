from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Final


def main() -> None:
    overlay: Final[Path] = Path(tempfile.mkdtemp(prefix="locked-cli-", dir=os.environ["RUNNER_TEMP"]))
    exposed: list[str] = []
    for command in (Path(sys.argv[1]).resolve() / ("Scripts" if os.name == "nt" else "bin")).iterdir():
        name = command.stem.casefold() if os.name == "nt" else command.name.casefold()
        if (
            command.is_file()
            and (os.name != "nt" or command.suffix.casefold() == ".exe")
            and os.access(command, os.X_OK)
            and not name.startswith(("activate", "deactivate", "easy_install", "ensurepip", "pip", "pydoc", "python"))
            and name not in {"bash", "curl", "gh", "git", "openssl", "sh", "ssh", "uv", "uvx", "wheel"}
        ):
            if os.name == "nt":
                shutil.copy2(command, overlay / command.name)
            else:
                os.symlink(command, overlay / command.name)
            exposed.append(command.name)
    with Path(os.environ["GITHUB_PATH"]).open("a", encoding="utf-8") as stream:
        print(overlay, file=stream)
    print(
        f"Exposed {len(exposed)} command{'' if len(exposed) == 1 else 's'} from {sys.argv[1]} on PATH: {', '.join(sorted(exposed)) or 'none'}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]
