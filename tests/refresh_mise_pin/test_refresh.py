from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest
import yaml

from tools.refresh_mise_pin import main


def _release(
    version: str,
    *,
    days: int,
    prerelease: bool = False,
    draft: bool = False,
    asset: bool = True,
    digest: str | None = "sha256:" + "a" * 64,
    asset_days: int | None = None,
    archive: bool = True,
    recent_archive: str = "",
) -> dict[str, object]:
    asset_date = (datetime.now(UTC) - timedelta(days=days if asset_days is None else asset_days)).isoformat()
    archive_date = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    assets = (
        [{"name": f"mise-v{version}-linux-x64", "digest": digest, "created_at": asset_date, "updated_at": asset_date}]
        if asset
        else []
    )
    if archive:
        assets.extend(
            {
                "name": f"mise-v{version}-linux-x64{suffix}",
                "digest": "sha256:" + "b" * 64,
                "created_at": archive_date,
                "updated_at": datetime.now(UTC).isoformat() if suffix == recent_archive else archive_date,
            }
            for suffix in (".tar.zst", ".tar.gz")
        )
    return {
        "tag_name": f"v{version}",
        "published_at": (datetime.now(UTC) - timedelta(days=days)).isoformat(),
        "prerelease": prerelease,
        "draft": draft,
        "assets": assets,
    }


def _step(version: str, digest: str) -> str:
    return (
        "      - name: 🔧 Set up mise (JDKs)\n"
        "        uses: jdx/mise-action@08ae2a091c038e1e05ec6f5115dc5c69d5a2a6b8 # v5.1.2\n"
        "        with:\n"
        f"          version: {version}\n"
        f"          sha256: {digest}\n"
    )


@pytest.mark.parametrize(
    ("workflow_text", "old_version"),
    [
        pytest.param(
            "jobs:\n  build:\n    steps:\n      - name: 🔧 Set up mise (JDKs)\n"
            "        uses: jdx/mise-action@08ae2a091c038e1e05ec6f5115dc5c69d5a2a6b8 # v5.1.2\n"
            '        with:\n          version: "2026.10.12"\n          sha256: '
            + "0" * 64
            + "\n      - name: Build\n        run: echo unchanged\n",
            'version: "2026.10.13"',
            id="jetbrains-fish",
        ),
        pytest.param(
            "jobs:\n  build:\n    steps:\n      - name: 🔧 Set up mise (JDKs)\n"
            "        uses: jdx/mise-action@08ae2a091c038e1e05ec6f5115dc5c69d5a2a6b8 # v5.1.2\n"
            "        with:\n          version: 2026.10.12\n          sha256: "
            + "0" * 64
            + "\n      - name: Build\n        run: echo unchanged\n",
            "version: 2026.10.13",
            id="pyvenvmanage",
        ),
    ],
)
def test_update_real_workflow_styles(
    tmp_path: Path, workflow_text: str, old_version: str, mise_binary: tuple[Path, str]
) -> None:
    binary, digest = mise_binary
    workflow = _workflow(tmp_path, workflow_text)
    result = _run(
        tmp_path,
        "update",
        str(workflow.relative_to(tmp_path)),
        "🔧 Set up mise (JDKs)",
        "2026.10.13",
        digest,
        str(binary),
    )
    assert result.returncode == 0, result.stderr
    assert old_version in workflow.read_text()
    assert f"sha256: {digest}" in workflow.read_text()
    assert "run: echo unchanged" in workflow.read_text()
    assert (tmp_path / "output").read_text() == f"changed=true\nversion=2026.10.13\nsha256={digest}\n"


def test_update_does_not_rewrite_unchanged_pin(tmp_path: Path, mise_binary: tuple[Path, str]) -> None:
    binary, digest = mise_binary
    workflow = _workflow(tmp_path, _step("2026.10.13", digest))
    before = workflow.stat().st_mtime_ns
    result = _run(
        tmp_path,
        "update",
        str(workflow.relative_to(tmp_path)),
        "🔧 Set up mise (JDKs)",
        "2026.10.13",
        digest,
        str(binary),
    )
    assert result.returncode == 0, result.stderr
    assert workflow.stat().st_mtime_ns == before
    assert (tmp_path / "output").read_text().startswith("changed=false\n")


def test_update_rejects_downgrade(tmp_path: Path, mise_binary: tuple[Path, str]) -> None:
    binary, digest = mise_binary
    workflow = _workflow(tmp_path, _step("2026.10.14", "0" * 64))
    result = _run(
        tmp_path,
        "update",
        ".github/workflows/release.yaml",
        "🔧 Set up mise (JDKs)",
        "2026.10.13",
        digest,
        str(binary),
    )
    assert result.returncode != 0
    assert "older than the current pin" in result.stderr
    assert "version: 2026.10.14" in workflow.read_text()


def test_update_preserves_following_step_fields(tmp_path: Path, mise_binary: tuple[Path, str]) -> None:
    binary, digest = mise_binary
    workflow = _workflow(tmp_path, _step("2026.10.12", "0" * 64) + "        env:\n          OTHER: yes\n")
    result = _run(
        tmp_path,
        "update",
        ".github/workflows/release.yaml",
        "🔧 Set up mise (JDKs)",
        "2026.10.13",
        digest,
        str(binary),
    )
    assert result.returncode == 0, result.stderr
    assert "        env:\n          OTHER: yes\n" in workflow.read_text()


def test_update_ignores_step_text_inside_run_block(tmp_path: Path, mise_binary: tuple[Path, str]) -> None:
    binary, digest = mise_binary
    fake = _step("2026.10.12", "0" * 64)
    content = (
        "jobs:\n  build:\n    steps:\n      - name: Write fixture\n        run: |\n"
        + "".join(f"          {line}" for line in fake.splitlines(keepends=True))
        + _step("2026.10.12", "0" * 64)
    )
    workflow = _workflow(tmp_path, content)
    result = _run(
        tmp_path, "update", ".github/workflows/release.yaml", "🔧 Set up mise (JDKs)", "2026.10.13", digest, str(binary)
    )
    assert result.returncode == 0, result.stderr
    assert workflow.read_text().count("version: 2026.10.12") == 1
    assert workflow.read_text().count("version: 2026.10.13") == 1


def test_update_rejects_aliased_inputs_from_other_step(tmp_path: Path, mise_binary: tuple[Path, str]) -> None:
    binary, digest = mise_binary
    content = (
        "jobs:\n  build:\n    steps:\n"
        "      - name: Other\n        uses: jdx/mise-action@08ae2a091c038e1e05ec6f5115dc5c69d5a2a6b8\n"
        f"        with: &mise\n          version: 2026.10.12\n          sha256: {'0' * 64}\n"
        "      - name: 🔧 Set up mise (JDKs)\n"
        "        uses: jdx/mise-action@08ae2a091c038e1e05ec6f5115dc5c69d5a2a6b8\n"
        "        with: *mise\n"
    )
    workflow = _workflow(tmp_path, content)
    result = _run(
        tmp_path, "update", ".github/workflows/release.yaml", "🔧 Set up mise (JDKs)", "2026.10.13", digest, str(binary)
    )
    assert result.returncode != 0
    assert "YAML aliases outside" in result.stderr
    assert workflow.read_text() == content


def test_update_rejects_inputs_aliased_by_later_step(tmp_path: Path, mise_binary: tuple[Path, str]) -> None:
    binary, digest = mise_binary
    content = (
        "jobs:\n  build:\n    steps:\n"
        "      - name: 🔧 Set up mise (JDKs)\n"
        "        uses: jdx/mise-action@08ae2a091c038e1e05ec6f5115dc5c69d5a2a6b8\n"
        f"        with: &mise\n          version: 2026.10.12\n          sha256: {'0' * 64}\n"
        "      - name: Other\n        uses: jdx/mise-action@08ae2a091c038e1e05ec6f5115dc5c69d5a2a6b8\n"
        "        with: *mise\n"
    )
    workflow = _workflow(tmp_path, content)
    result = _run(
        tmp_path, "update", ".github/workflows/release.yaml", "🔧 Set up mise (JDKs)", "2026.10.13", digest, str(binary)
    )
    assert result.returncode != 0
    assert "aliased elsewhere" in result.stderr
    assert workflow.read_text() == content


def test_update_rejects_shadowed_job(tmp_path: Path, mise_binary: tuple[Path, str]) -> None:
    binary, digest = mise_binary
    content = "jobs:\n  build:\n    steps:\n" + _step("2026.10.12", "0" * 64) + "  build:\n    steps: []\n"
    workflow = _workflow(tmp_path, content)
    result = _run(
        tmp_path, "update", ".github/workflows/release.yaml", "🔧 Set up mise (JDKs)", "2026.10.13", digest, str(binary)
    )
    assert result.returncode != 0
    assert "duplicate YAML job name" in result.stderr
    assert workflow.read_text() == content


@pytest.mark.parametrize("content", ["[]\n", "jobs: []\n"], ids=["root", "jobs"])
def test_update_rejects_missing_jobs_mapping(tmp_path: Path, mise_binary: tuple[Path, str], content: str) -> None:
    binary, digest = mise_binary
    workflow = _workflow(tmp_path, _step("2026.10.12", "0" * 64))
    workflow.write_text(content)
    result = _run(
        tmp_path, "update", ".github/workflows/release.yaml", "🔧 Set up mise (JDKs)", "2026.10.13", digest, str(binary)
    )
    assert result.returncode != 0
    assert "workflow needs a jobs mapping" in result.stderr


def test_update_handles_unrelated_recursive_alias(tmp_path: Path, mise_binary: tuple[Path, str]) -> None:
    binary, digest = mise_binary
    content = "jobs:\n  build:\n    steps:\n      - name: Other\n        env: &loop [*loop]\n" + _step(
        "2026.10.12", "0" * 64
    )
    workflow = _workflow(tmp_path, content)
    result = _run(
        tmp_path, "update", ".github/workflows/release.yaml", "🔧 Set up mise (JDKs)", "2026.10.13", digest, str(binary)
    )
    assert result.returncode == 0, result.stderr
    assert "version: 2026.10.13" in workflow.read_text()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param("jobs: {}\n", "found 0", id="missing-step"),
        pytest.param(
            "jobs:\n  build:\n    steps:\n" + _step("2026.10.12", "0" * 64) * 2, "found 2", id="duplicate-step"
        ),
        pytest.param(
            _step("2026.10.12", "0" * 64).replace("jdx/mise-action@08", "jdx/mise-action@v5."),
            "SHA-pinned",
            id="mutable-action",
        ),
        pytest.param(_step("2026.10.12", "0" * 64).split("        with:\n")[0], "with mapping", id="missing-with"),
        pytest.param(
            _step("2026.10.12", "0" * 64).replace("          sha256: " + "0" * 64, ""),
            "literal version and sha256",
            id="missing-digest",
        ),
        pytest.param(
            _step("2026.10.12", "0" * 64).replace("          version: 2026.10.12", "          version: latest"),
            "literal version and sha256",
            id="floating-version",
        ),
        pytest.param(
            _step("2026.10.12", "0" * 64).replace(
                "          sha256: " + "0" * 64, "          sha256: " + "0" * 64 + "\n          sha256: " + "1" * 64
            ),
            "duplicate YAML key: sha256",
            id="duplicate-digest",
        ),
    ],
)
def test_update_rejects_ambiguous_workflow(
    tmp_path: Path, mise_binary: tuple[Path, str], content: str, message: str
) -> None:
    binary, digest = mise_binary
    workflow = _workflow(tmp_path, content)
    original = workflow.read_text()
    result = _run(
        tmp_path,
        "update",
        str(workflow.relative_to(tmp_path)),
        "🔧 Set up mise (JDKs)",
        "2026.10.13",
        digest,
        str(binary),
    )
    assert result.returncode != 0
    assert message in result.stderr
    assert workflow.read_text() == original


@pytest.mark.parametrize(
    ("workflow_name", "version", "digest", "binary_version", "message"),
    [
        pytest.param("README.md", "2026.10.13", "a" * 64, "2026.10.13", "workflow must", id="outside-workflows"),
        pytest.param(
            ".github/workflows/release.yaml",
            "latest",
            "a" * 64,
            "2026.10.13",
            "invalid mise version",
            id="invalid-version",
        ),
        pytest.param(
            ".github/workflows/release.yaml",
            "2026.10.13",
            "bad",
            "2026.10.13",
            "invalid mise digest",
            id="invalid-digest",
        ),
        pytest.param(
            ".github/workflows/release.yaml",
            "2026.10.13",
            "a" * 64,
            "2026.10.12",
            "did not install",
            id="wrong-binary-version",
        ),
        pytest.param(
            ".github/workflows/release.yaml", "2026.10.13", "0" * 64, "2026.10.13", "differs", id="wrong-binary-digest"
        ),
    ],
)
def test_update_rejects_unverified_inputs(
    tmp_path: Path, workflow_name: str, version: str, digest: str, binary_version: str, message: str
) -> None:
    workflow = tmp_path / workflow_name
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text("jobs:\n  build:\n    steps:\n" + _step("2026.10.12", "0" * 64))
    binary = tmp_path / "bin" / "mise"
    binary.parent.mkdir()
    binary.write_bytes(b"verified mise")
    binary.with_name("mise-version").write_text(binary_version)
    result = _run(tmp_path, "update", workflow_name, "🔧 Set up mise (JDKs)", version, digest, str(binary))
    assert result.returncode != 0
    assert message in result.stderr


def test_update_rejects_symlinked_workflow(tmp_path: Path, mise_binary: tuple[Path, str]) -> None:
    binary, digest = mise_binary
    target = _workflow(tmp_path, _step("2026.10.12", "0" * 64))
    target.rename(target.with_name("actual.yaml"))
    target.symlink_to("actual.yaml")
    result = _run(
        tmp_path, "update", ".github/workflows/release.yaml", "🔧 Set up mise (JDKs)", "2026.10.13", digest, str(binary)
    )
    assert result.returncode != 0
    assert "regular YAML" in result.stderr


def test_select_newest_stable_aged_release(tmp_path: Path) -> None:
    releases = [
        _release("2026.10.15", days=1),
        _release("2026.10.14", days=8, prerelease=True),
        _release("2026.10.13", days=8),
        _release("2026.10.12", days=9),
    ]
    (tmp_path / "releases.jsonl").write_text("\n".join(map(json.dumps, releases)))
    result = _run(tmp_path, "select", "releases.jsonl")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == f"version=2026.10.13\nsha256={'a' * 64}\n"


def test_select_rejects_recent_asset_on_aged_release(tmp_path: Path) -> None:
    (tmp_path / "releases.jsonl").write_text(json.dumps(_release("2026.10.13", days=8, asset_days=1)))
    result = _run(tmp_path, "select", "releases.jsonl")
    assert result.returncode != 0
    assert "no mise executable and archives were uploaded and unchanged" in result.stderr


def test_select_uses_older_release_when_newer_asset_is_recent(tmp_path: Path) -> None:
    releases = [_release("2026.10.13", days=8, asset_days=1), _release("2026.10.12", days=9)]
    (tmp_path / "releases.jsonl").write_text("\n".join(map(json.dumps, releases)))
    result = _run(tmp_path, "select", "releases.jsonl")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == f"version=2026.10.12\nsha256={'a' * 64}\n"


@pytest.mark.parametrize("suffix", [pytest.param(".tar.zst", id="zstd"), pytest.param(".tar.gz", id="gzip")])
def test_select_rejects_recent_archive_on_aged_release(tmp_path: Path, suffix: str) -> None:
    (tmp_path / "releases.jsonl").write_text(json.dumps(_release("2026.10.13", days=8, recent_archive=suffix)))
    result = _run(tmp_path, "select", "releases.jsonl")
    assert result.returncode != 0
    assert "no mise executable and archives were uploaded and unchanged" in result.stderr


def test_select_uses_older_release_when_newer_archive_is_recent(tmp_path: Path) -> None:
    releases = [_release("2026.10.13", days=8, recent_archive=".tar.zst"), _release("2026.10.12", days=9)]
    (tmp_path / "releases.jsonl").write_text("\n".join(map(json.dumps, releases)))
    result = _run(tmp_path, "select", "releases.jsonl")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == f"version=2026.10.12\nsha256={'a' * 64}\n"


def test_main_selects_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "releases.jsonl").write_text(json.dumps(_release("2026.10.13", days=8)))
    monkeypatch.setattr(
        sys, "argv", ["refresh_mise_pin.py", "select", str(tmp_path / "releases.jsonl"), str(tmp_path / "output")]
    )
    main()
    assert (tmp_path / "output").read_text() == f"version=2026.10.13\nsha256={'a' * 64}\n"


@pytest.mark.parametrize(
    ("published", "accepted"),
    [pytest.param(b"verified mise", True, id="selected-digest"), pytest.param(b"swapped", False, id="other-bytes")],
)
def test_action_checks_executable_digest_before_mise_runs(tmp_path: Path, published: bytes, accepted: bool) -> None:
    steps = yaml.safe_load((Path(__file__).resolve().parents[2] / "refresh-mise-pin" / "action.yml").read_text())[
        "runs"
    ]["steps"]
    download = next(step for step in steps if step.get("name") == "Download the selected mise executable")
    installer = next(step for step in steps if step.get("uses", "").startswith("jdx/mise-action@"))
    assert steps.index(download) < steps.index(installer)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (tmp_path / "published").write_bytes(published)
    gh = fake_bin / "gh"
    gh.write_text(f'#!/bin/sh\ncp {tmp_path / "published"} "$9/mise-v2026.10.13-linux-x64"\n')
    gh.chmod(0o755)
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", download["run"]],
        env=os.environ
        | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "VERSION": "2026.10.13",
            "EXPECTED_SHA256": sha256(b"verified mise").hexdigest(),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    binary = tmp_path / "refresh-mise-pin" / "bin" / "mise"
    assert (result.returncode == 0) is accepted, result.stderr
    assert binary.exists() is accepted
    if accepted:
        assert os.access(binary, os.X_OK)
        assert binary.with_name("mise-version").read_text() == "2026.10.13"


def test_update_keeps_crlf_line_endings(tmp_path: Path, mise_binary: tuple[Path, str]) -> None:
    binary, digest = mise_binary
    workflow = tmp_path / ".github" / "workflows" / "release.yaml"
    workflow.parent.mkdir(parents=True)
    workflow.write_bytes(("jobs:\n  build:\n    steps:\n" + _step("2026.10.12", "0" * 64)).replace("\n", "\r\n").encode())
    result = _run(
        tmp_path,
        "update",
        ".github/workflows/release.yaml",
        "🔧 Set up mise (JDKs)",
        "2026.10.13",
        digest,
        str(binary),
    )
    assert result.returncode == 0, result.stderr
    assert workflow.read_bytes() == (
        ("jobs:\n  build:\n    steps:\n" + _step("2026.10.13", digest)).replace("\n", "\r\n").encode()
    )


def test_action_keeps_linux_executable_and_archives_in_release_listing() -> None:
    action = yaml.safe_load((Path(__file__).resolve().parents[2] / "refresh-mise-pin" / "action.yml").read_text())
    query = action["runs"]["steps"][0]["run"].split("--jq '", 1)[1].split("'", 1)[0]
    release = _release("2026.10.13", days=8)
    cast(list[dict[str, object]], release["assets"]).append(
        {"name": "mise-v2026.10.13-linux-x64-musl", "digest": "sha256:" + "c" * 64}
    )
    result = subprocess.run(
        ["jq", "-r", query], input=json.dumps([release]), text=True, capture_output=True, check=True
    )
    assert {asset["name"] for asset in json.loads(result.stdout)["assets"]} == {
        "mise-v2026.10.13-linux-x64",
        "mise-v2026.10.13-linux-x64.tar.zst",
        "mise-v2026.10.13-linux-x64.tar.gz",
    }


@pytest.mark.parametrize(
    ("releases", "message"),
    [
        pytest.param([_release("2026.10.13", days=1)], "no stable mise", id="too-young"),
        pytest.param([_release("2026.10.13", days=8, draft=True)], "no stable mise", id="draft"),
        pytest.param([_release("2026.10.13", days=8, asset=False)], "no unique Linux", id="missing-asset"),
        pytest.param([_release("2026.10.13", days=8, archive=False)], "no unique Linux", id="missing-archive"),
        pytest.param([_release("2026.10.13", days=8, digest="sha256:bad")], "no unique Linux", id="bad-asset-digest"),
        pytest.param([_release("2026.10.13", days=8, digest=None)], "no unique Linux", id="null-asset-digest"),
    ],
)
def test_select_rejects_invalid_release(tmp_path: Path, releases: list[dict[str, object]], message: str) -> None:
    (tmp_path / "releases.jsonl").write_text("\n".join(map(json.dumps, releases)))
    result = _run(tmp_path, "select", "releases.jsonl")
    assert result.returncode != 0
    assert message in result.stderr


@pytest.fixture
def mise_binary(tmp_path: Path) -> tuple[Path, str]:
    binary = tmp_path / "bin" / "mise"
    binary.parent.mkdir()
    binary.write_bytes(b"verified mise")
    binary.with_name("mise-version").write_text("2026.10.13")
    return binary, sha256(binary.read_bytes()).hexdigest()


def _workflow(tmp_path: Path, content: str) -> Path:
    workflow = tmp_path / ".github" / "workflows" / "release.yaml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(content if content.startswith("jobs:") else "jobs:\n  build:\n    steps:\n" + content)
    return workflow


def _run(tmp_path: Path, command: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "tools" / "refresh_mise_pin.py"),
            command,
            *arguments,
            str(tmp_path / "output"),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
