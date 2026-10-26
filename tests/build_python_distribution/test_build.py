from __future__ import annotations

import os
import shutil
import tomllib
from pathlib import Path

from conftest import action, run


def test_build_python_distribution_creates_wheel_and_sdist(
    build_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    result = action(
        build_repository,
        tmp_path,
        action_scripts,
        "build-python-distribution",
        version="0.2.0",
        RUNNER_TEMP=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert {path.name for path in (build_repository / "dist").iterdir() if path.suffix in {".whl", ".gz"}} == {
        "fixture-0.2.0-py3-none-any.whl",
        "fixture-0.2.0.tar.gz",
    }
    assert any("hatchling==" in path.read_text() for path in tmp_path.glob("build-constraints-*.txt"))


def test_build_python_distribution_repeats_exact_bytes(
    build_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    outputs: list[dict[str, bytes]] = []
    for name in ("first", "second"):
        temporary = tmp_path / name
        temporary.mkdir()
        result = action(
            build_repository,
            temporary,
            action_scripts,
            "build-python-distribution",
            version="0.2.0",
            RUNNER_TEMP=str(temporary),
        )
        assert result.returncode == 0, result.stderr
        outputs.append({path.name: path.read_bytes() for path in (build_repository / "dist").iterdir()})
        shutil.rmtree(build_repository / "dist")
    assert outputs[0] == outputs[1]


def test_build_python_distribution_rejects_backend_hash_mismatch(
    build_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    lock = build_repository / "pylock.toml"
    contents = lock.read_text()
    package = next(package for package in tomllib.loads(contents)["packages"] if package["name"] == "hatchling")
    for artifact in [package["sdist"], *package["wheels"]]:
        contents = contents.replace(artifact["hashes"]["sha256"], "0" * 64, 1)
    lock.write_text(contents)
    run(build_repository, "git", "add", "pylock.toml")
    run(build_repository, "git", "commit", "-m", "Corrupt backend hash")
    result = action(
        build_repository,
        tmp_path,
        action_scripts,
        "build-python-distribution",
        version="0.2.0",
        RUNNER_TEMP=str(tmp_path),
        UV_CACHE_DIR=str(tmp_path / "uv-cache"),
    )
    assert result.returncode != 0
    assert "Hash mismatch" in result.stderr


def test_build_python_distribution_does_not_run_hooks(
    build_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    config = build_repository / ".pre-commit-config.yaml"
    config.write_text(config.read_text().replace("entry: bash -c true", "entry: bash -c 'touch generated-file'"))
    run(build_repository, "git", "add", ".")
    run(build_repository, "git", "commit", "-m", "Create an untracked output")
    result = action(
        build_repository,
        tmp_path,
        action_scripts,
        "build-python-distribution",
        version="0.2.0",
        RUNNER_TEMP=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert not (build_repository / "generated-file").exists()


def test_build_python_distribution_stops_when_interpreter_lookup_fails(
    build_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    tools = tmp_path / "bin"
    tools.mkdir()
    uv = shutil.which("uv")
    assert uv is not None
    (tools / "uv").write_text(
        '#!/usr/bin/env bash\nif [[ "$1" == python && "$2" == find ]]; then exit 19; fi\n'
        'if [[ "$1" == build ]]; then printf "build called\\n" >>"$RUNNER_TEMP/build-calls"; fi\n'
        f'exec "{uv}" "$@"\n',
    )
    (tools / "uv").chmod(0o755)
    result = action(
        build_repository,
        tmp_path,
        action_scripts,
        "build-python-distribution",
        version="0.2.0",
        PATH=f"{tools}:{os.environ['PATH']}",
    )
    assert result.returncode == 19, result.stderr
    assert not (tmp_path / "build-calls").exists()
