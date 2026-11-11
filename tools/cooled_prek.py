#!/usr/bin/env python3
"""Install prek hooks under the upload cutoff, then run them in the caller's environment."""

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from uv_environment import clean_uv_environment


def main() -> int:
    arguments = sys.argv[1:]
    if arguments == ["refresh-pins"]:
        return _pin_cutoffs(["--refresh"]).returncode
    if arguments[:1] != ["run"]:
        return _install_hooks(arguments)
    hooks = []
    for argument in arguments[1:]:
        if argument.startswith("-"):
            break
        hooks.append(argument)
    if status := _install_hooks(["install-hooks", *hooks]):
        return status
    print(f"Running prek {' '.join(arguments)} with the caller's environment", flush=True)
    return subprocess.run(["prek", "--config", ".pre-commit-config.yaml", *arguments], check=False).returncode


def _install_hooks(arguments: list[str]) -> int:
    environment = clean_uv_environment() | {"UV_EXCLUDE_NEWER": "7 days", "UV_NO_CONFIG": "1", "UV_NO_SOURCES": "1"}
    result = _pin_cutoffs([], environment)
    if result.returncode:
        return result.returncode
    exceptions = result.stdout.strip()
    with TemporaryDirectory() as directory:
        if exceptions:
            config = Path(directory) / "uv.toml"
            config.write_text(f"[exclude-newer-package]\n{exceptions}\n")
            environment["UV_CONFIG_FILE"] = str(config)
            print(
                f"Running prek {' '.join(arguments)} with hook environments built under the 7 days cutoff, "
                "repository uv settings ignored, [tool.nab] exceptions and exact hook pins admitted up to their dates: "
                f"{' '.join(exceptions.splitlines())}",
                flush=True,
            )
        else:
            print(
                f"Running prek {' '.join(arguments)} with hook environments built under the 7 days cutoff, "
                "repository uv settings ignored",
                flush=True,
            )
        return subprocess.run(
            ["prek", "--config", ".pre-commit-config.yaml", *arguments], env=environment, check=False
        ).returncode


def _pin_cutoffs(arguments: list[str], environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["uv", "run", "--no-project", "--with", "pyyaml", "python", "-I", "-", *arguments],
        input=Path(__file__).with_name("hook_pin_cutoffs.py").read_text(),
        text=True,
        capture_output=True,
        env=environment or clean_uv_environment(),
        check=False,
    )
    sys.stderr.write(result.stderr)
    return result


raise SystemExit(main())
