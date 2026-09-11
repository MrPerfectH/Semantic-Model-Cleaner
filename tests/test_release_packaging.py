import hashlib
import importlib.util
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


identity = _load("release_identity", ROOT / "scripts/verify_release_identity.py")
checksums = _load("release_checksums", ROOT / "scripts/release_checksums.py")


def test_public_beta_release_identity_is_consistent():
    release = identity.verify("v0.4.0b1")
    assert release == {
        "name": "semantic-model-cleaner",
        "version": "0.4.0b1",
        "channel": "beta",
        "tag": "v0.4.0b1",
        "windows_archive": "semantic-model-cleaner-windows-x64-0.4.0b1.zip",
    }


def test_release_identity_rejects_a_mismatched_tag():
    with pytest.raises(ValueError, match="release tag"):
        identity.verify("v0.4.0")


def test_checksum_sidecar_round_trip_and_tamper_detection(tmp_path):
    artifact = tmp_path / "artifact with spaces.zip"
    artifact.write_bytes(b"public beta")
    sidecar = checksums.write(artifact)
    assert sidecar.read_text() == f"{hashlib.sha256(b'public beta').hexdigest()}  {artifact.name}\n"
    checksums.verify(sidecar)
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        checksums.verify(sidecar)


def test_schema_bundle_checkout_preserves_manifest_bytes_on_windows(tmp_path):
    relative = Path(
        "src/semantic_model_cleaner/schemas/microsoft-report/"
        "fabric/item/report/definition/bookmark/1.0.0/schema.json"
    )
    subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=true",
            "checkout-index",
            f"--prefix={tmp_path}/",
            "--",
            relative.as_posix(),
        ],
        cwd=ROOT,
        check=True,
    )
    checked_out = (tmp_path / relative).read_bytes()
    source = (ROOT / relative).read_bytes()
    assert checked_out == source
    assert b"\r\n" not in checked_out
