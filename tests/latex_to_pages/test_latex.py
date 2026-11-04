from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Final

import pytest
from conftest import JsonObject, at, load_yaml, mapping, step, steps, text, workflow_step

WORKFLOW: Final[str] = "latex-to-pages.yaml"
ROOT: Final = Path(__file__).resolve().parents[2]
GH_STUB: Final[str] = """\
#!/usr/bin/env bash
case "$*" in
*pages/builds*) echo "abc built" ;;
*) echo abc ;;
esac
"""
CURL_STUB: Final[str] = '#!/usr/bin/env bash\ncat "$SERVED_FILE"\n'
NOOP_STUB: Final[str] = "#!/usr/bin/env bash\nexit 0\n"


def _workflow() -> JsonObject:
    return load_yaml(ROOT / ".github/workflows" / WORKFLOW)


def _step(job: str, name: str) -> JsonObject:
    return step(_workflow(), job, name)


@pytest.fixture
def stubs(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("gh", GH_STUB), ("curl", CURL_STUB), ("sleep", NOOP_STUB)):
        script = bin_dir / name
        script.write_text(body)
        script.chmod(0o755)
    return bin_dir


def test_top_level_grants_nothing_and_each_job_holds_only_its_scope() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {}
    assert at(workflow, "jobs", "build", "permissions") == {"contents": "read"}
    assert at(workflow, "jobs", "deploy", "permissions") == {"contents": "write", "pages": "read"}


def test_build_pins_clock_and_bounds_runtime() -> None:
    assert at(_workflow(), "jobs", "build", "timeout-minutes") == "20"
    compile_step = _step("build", "📕 Compile LaTeX document")
    pre_compile = text(mapping(compile_step["with"])["pre_compile"])
    assert "SOURCE_DATE_EPOCH=${{ steps.epoch.outputs.epoch }}" in pre_compile
    assert at(_workflow(), "jobs", "deploy", "timeout-minutes") == "30"


def test_checkouts_keep_credentials_out_of_the_workspace() -> None:
    workflow = _workflow()
    for job in mapping(at(workflow, "jobs")):
        checkouts = [
            item for item in steps(workflow, job) if text(item.get("uses", "")).startswith("actions/checkout@")
        ]
        assert [item["with"] for item in checkouts] == [{"persist-credentials": "false"}]


@pytest.mark.parametrize(
    ("root_file", "pdf"),
    [
        pytest.param("main.tex", "main.pdf", id="root"),
        pytest.param("doc/cv.tex", "cv.pdf", id="nested"),
    ],
)
def test_records_pdf_name_and_digest(tmp_path: Path, root_file: str, pdf: str) -> None:
    (tmp_path / Path(root_file).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / Path(root_file).with_suffix(".pdf")).write_bytes(b"pdf bytes")
    output = tmp_path / "output"
    result = workflow_step(
        WORKFLOW,
        "build",
        "🔎 Record PDF name and digest",
        tmp_path,
        {"ROOT_FILE": root_file, "GITHUB_OUTPUT": str(output)},
    )
    assert result.returncode == 0, result.stderr
    fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert fields == {
        "path": str(Path(root_file).with_suffix(".pdf")),
        "name": Path(pdf).name,
        "sha256": hashlib.sha256(b"pdf bytes").hexdigest(),
    }


def test_missing_pdf_fails_the_build(tmp_path: Path) -> None:
    result = workflow_step(
        WORKFLOW,
        "build",
        "🔎 Record PDF name and digest",
        tmp_path,
        {"ROOT_FILE": "main.tex", "GITHUB_OUTPUT": str(tmp_path / "output")},
    )
    assert result.returncode != 0


@pytest.mark.parametrize(
    ("content", "accepted"),
    [
        pytest.param(b"pdf bytes", True, id="matches-build"),
        pytest.param(b"tampered", False, id="tampered-download"),
    ],
)
def test_deploy_rejects_a_download_that_differs_from_the_build(
    tmp_path: Path,
    content: bytes,
    accepted: bool,
) -> None:
    (tmp_path / "built").mkdir()
    (tmp_path / "built/main.pdf").write_bytes(content)
    result = workflow_step(
        WORKFLOW,
        "deploy",
        "🔍 Check downloaded PDF digest",
        tmp_path,
        {"PDF_NAME": "main.pdf", "PDF_SHA256": hashlib.sha256(b"pdf bytes").hexdigest()},
    )
    assert (result.returncode == 0) is accepted, result.stderr


def _verify(tmp_path: Path, stubs: Path, served: bytes, expected: str) -> subprocess.CompletedProcess[str]:
    served_file = tmp_path / "served.pdf"
    served_file.write_bytes(served)
    return workflow_step(
        WORKFLOW,
        "deploy",
        "🔍 Verify published PDF",
        tmp_path,
        {
            "GH_TOKEN": "token",
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_RUN_ID": "1",
            "URL": "https://owner.github.io/repo/main.pdf",
            "PDF_SHA256": expected,
            "SERVED_FILE": str(served_file),
            "PATH": f"{stubs}:{os.environ['PATH']}",
        },
    )


def test_verify_loop_accepts_the_served_bytes_it_built(tmp_path: Path, stubs: Path) -> None:
    result = _verify(tmp_path, stubs, b"built pdf", hashlib.sha256(b"built pdf").hexdigest())
    assert result.returncode == 0, result.stderr
    assert "Pages serves the freshly built PDF" in result.stdout


def test_verify_loop_fails_when_pages_keeps_serving_other_bytes(tmp_path: Path, stubs: Path) -> None:
    result = _verify(tmp_path, stubs, b"stale pdf", hashlib.sha256(b"built pdf").hexdigest())
    assert result.returncode != 0
    assert "::error::" in result.stderr
