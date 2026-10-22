from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


@pytest.mark.parametrize(
    "credential_format",
    [
        pytest.param("pem", id="pem"),
        pytest.param("base64", id="base64"),
        pytest.param("encrypted", id="encrypted"),
    ],
)
def test_signs_and_verifies_exact_archive(
    action_scripts: Path,
    certificate: tuple[Path, Path],
    unsigned_archive: Path,
    tmp_path: Path,
    credential_format: str,
) -> None:
    private_key, chain = certificate
    password = ""
    if credential_format == "encrypted":
        encrypted_key = tmp_path / "encrypted.pem"
        subprocess.run(
            [
                "openssl",
                "pkcs8",
                "-topk8",
                "-v2",
                "aes-256-cbc",
                "-in",
                str(private_key),
                "-out",
                str(encrypted_key),
                "-passout",
                "pass:fixture-pass",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        private_key = encrypted_key
        password = "fixture-pass"
    key_text = private_key.read_text()
    chain_text = chain.read_text()
    if credential_format == "base64":
        key_text = base64.b64encode(key_text.encode()).decode()
        chain_text = base64.b64encode(chain_text.encode()).decode()
    output = tmp_path / "output"
    output.touch()
    java = shutil.which("java")
    assert java is not None
    settings = {
        "ARCHIVE": str(unsigned_archive),
        "EXPECTED_SHA": hashlib.sha256(unsigned_archive.read_bytes()).hexdigest(),
        "GITHUB_OUTPUT": str(output),
        "RUNNER_TEMP": str(tmp_path),
        "JAVA_HOME_17_X64": str(Path(java).resolve().parents[1]),
        "SIGNER_BASE_URL": "https://repo.maven.apache.org/maven2/org/jetbrains/marketplace-zip-signer/0.1.43",
        "SIGNER_SHA256": "2958a0f42221d6062b50f22754e413ae5cc42f60c441467202c6700df2e22f44",
        "CERTIFICATE_CHAIN": chain_text,
        "PRIVATE_KEY": key_text,
        "PRIVATE_KEY_PASSWORD": password,
    }
    for index in range(4):
        assert run_step(action_scripts, index, tmp_path, **settings).returncode == 0
    settings["SIGNED"] = output.read_text().split("archive=", 1)[1].splitlines()[0]
    assert run_step(action_scripts, 4, tmp_path, **settings).returncode == 0
    assert not (tmp_path / "signing-key.pem").exists()
    assert not (tmp_path / "signing-key-decrypted.pem").exists()
    assert not (tmp_path / "signing-chain.pem").exists()
    output.write_text("")
    assert run_step(action_scripts, 5, tmp_path, **settings).returncode == 0
    signed = Path(settings["SIGNED"])
    assert dict(line.split("=", 1) for line in output.read_text().splitlines()) == {
        "archive": str(signed),
        "sha256": hashlib.sha256(signed.read_bytes()).hexdigest(),
    }
    with ZipFile(unsigned_archive) as unsigned, ZipFile(signed) as signed_zip:
        assert {name: unsigned.read(name) for name in unsigned.namelist()} == {
            name: signed_zip.read(name) for name in signed_zip.namelist()
        }


@pytest.mark.parametrize(
    "invalid",
    [
        pytest.param("digest", id="wrong-digest"),
        pytest.param("extension", id="wrong-extension"),
        pytest.param("corrupt", id="corrupt-zip"),
        pytest.param("duplicate", id="duplicate-member"),
        pytest.param("symlink", id="symlink"),
    ],
)
def test_rejects_invalid_unsigned_archive(
    action_scripts: Path,
    unsigned_archive: Path,
    tmp_path: Path,
    invalid: str,
) -> None:
    archive = unsigned_archive
    if invalid == "extension":
        archive = tmp_path / "plugin.tar"
        archive.write_bytes(unsigned_archive.read_bytes())
    elif invalid == "corrupt":
        archive.write_bytes(b"not a ZIP")
    elif invalid == "duplicate":
        with ZipFile(archive, "a") as content:
            content.writestr("Plugin/lib/Plugin.jar", b"changed")
    elif invalid == "symlink":
        archive = tmp_path / "linked.zip"
        archive.symlink_to(unsigned_archive)
    assert (
        run_step(
            action_scripts,
            0,
            tmp_path,
            ARCHIVE=str(archive),
            EXPECTED_SHA="0" * 64 if invalid == "digest" else hashlib.sha256(archive.read_bytes()).hexdigest(),
            GITHUB_OUTPUT=str(tmp_path / "output"),
        ).returncode
        != 0
    )


def test_rejects_changed_signer_jar(action_scripts: Path, tmp_path: Path) -> None:
    (tmp_path / "marketplace-signer-cli.jar").write_bytes(b"not the signer")
    assert (
        run_step(
            action_scripts,
            2,
            tmp_path,
            RUNNER_TEMP=str(tmp_path),
            SIGNER_SHA256="2958a0f42221d6062b50f22754e413ae5cc42f60c441467202c6700df2e22f44",
        ).returncode
        != 0
    )


def test_rejects_missing_java(action_scripts: Path, tmp_path: Path) -> None:
    assert run_step(action_scripts, 3, tmp_path, JAVA_HOME_17_X64=str(tmp_path / "missing")).returncode != 0


@pytest.fixture
def unsigned_archive(tmp_path: Path) -> Path:
    archive = tmp_path / "Plugin 2-1.0.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as content:
        content.writestr("Plugin/lib/Plugin.jar", b"plugin payload")
    return archive


@pytest.fixture
def certificate(tmp_path: Path) -> tuple[Path, Path]:
    private_key = tmp_path / "key.pem"
    chain = tmp_path / "chain.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(private_key),
            "-out",
            str(chain),
            "-subj",
            "/CN=JetBrains test",
            "-days",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return private_key, chain


def run_step(action_scripts: Path, index: int, directory: Path, **settings: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(action_scripts / f"sign-jetbrains-plugin-{index}.sh")],
        cwd=directory,
        env=os.environ | settings,
        text=True,
        capture_output=True,
        check=False,
    )
