#!/usr/bin/env python3
"""Install release tools from PyPI under an upload cutoff."""

import os
import subprocess
import sys

from uv_environment import clean_uv_environment


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("usage: install_live_tools.py VENV REQUIREMENT [REQUIREMENT ...]")
    cutoff = os.environ.get("EXCLUDE_NEWER")
    if cutoff is None:
        raise SystemExit("EXCLUDE_NEWER is required")
    environment = clean_uv_environment() | {"UV_NO_CONFIG": "1"}
    overrides = [line.strip() for line in os.environ.get("EXCLUDE_NEWER_PACKAGE", "").splitlines() if line.strip()]
    options = ["--exclude-newer", cutoff]
    for override in overrides:
        options.extend(("--exclude-newer-package", override))
    override_summary = f", overrides: {' '.join(overrides)}" if overrides else ""
    print(
        f"Installing {' '.join(sys.argv[2:])} into {sys.argv[1]} from PyPI (cutoff {cutoff}{override_summary})",
        flush=True,
    )
    for command in (
        ["uv", "venv", "--allow-existing", "--python", "3.15", sys.argv[1]],
        ["uv", "pip", "install", "--python", sys.argv[1], *options, *sys.argv[2:]],
    ):
        if (result := subprocess.run(command, env=environment, check=False)).returncode:
            return result.returncode
    return 0


raise SystemExit(main())
