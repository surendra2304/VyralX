"""Tests for the strict OCI image artifact reproducibility comparator."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts.compare_oci_images import (
    OCIArtifactError,
    compare_oci_artifacts,
    inspect_oci_archive,
)


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _descriptor(content: bytes, media_type: str) -> dict:
    return {
        "mediaType": media_type,
        "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        "size": len(content),
    }


def _layer_tar(payload: bytes) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        member = tarfile.TarInfo("payload.txt")
        member.size = len(payload)
        member.mtime = 0
        member.mode = 0o644
        member.uid = 0
        member.gid = 0
        member.uname = ""
        member.gname = ""
        archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


def _write_archive(
    path: Path,
    *,
    layer_content: bytes = b"sample OCI layer",
    compression_level: int | None = None,
    corrupt_blob: bool = False,
    unsafe_member: bool = False,
    member_mtime: int = 0,
    wrong_descriptor_size: bool = False,
) -> None:
    uncompressed_layer = _layer_tar(layer_content)
    layer_blob = (
        gzip.compress(uncompressed_layer, compresslevel=compression_level, mtime=0)
        if compression_level is not None
        else uncompressed_layer
    )
    layer_media_type = (
        "application/vnd.oci.image.layer.v1.tar+gzip"
        if compression_level is not None
        else "application/vnd.oci.image.layer.v1.tar"
    )
    config = _json_bytes(
        {
            "architecture": "amd64",
            "os": "linux",
            "rootfs": {
                "type": "layers",
                "diff_ids": ["sha256:" + hashlib.sha256(uncompressed_layer).hexdigest()],
            },
        }
    )
    layer_descriptor = _descriptor(layer_blob, layer_media_type)
    config_descriptor = _descriptor(config, "application/vnd.oci.image.config.v1+json")
    manifest = _json_bytes(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": config_descriptor,
            "layers": [layer_descriptor],
        }
    )
    manifest_descriptor = _descriptor(manifest, "application/vnd.oci.image.manifest.v1+json")
    root_descriptor = {
        **manifest_descriptor,
        "platform": {"architecture": "amd64", "os": "linux"},
    }
    if wrong_descriptor_size:
        root_descriptor["size"] += 1
    root_index = _json_bytes({"schemaVersion": 2, "manifests": [root_descriptor]})
    blobs = {
        "blobs/sha256/" + hashlib.sha256(config).hexdigest(): config,
        "blobs/sha256/" + hashlib.sha256(layer_blob).hexdigest(): (
            layer_blob + b"corruption" if corrupt_blob else layer_blob
        ),
        "blobs/sha256/" + hashlib.sha256(manifest).hexdigest(): manifest,
    }
    members = {
        "oci-layout": _json_bytes({"imageLayoutVersion": "1.0.0"}),
        "index.json": root_index,
        **blobs,
    }
    with tarfile.open(path, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, content in sorted(members.items()):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mtime = member_mtime
            member.mode = 0o644
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            archive.addfile(member, io.BytesIO(content))
        if unsafe_member:
            member = tarfile.TarInfo("../escape")
            member.size = 1
            archive.addfile(member, io.BytesIO(b"x"))


def test_identical_independent_oci_archives_pass_even_with_different_tar_metadata(tmp_path: Path):
    first = tmp_path / "first.oci.tar"
    second = tmp_path / "second.oci.tar"
    _write_archive(first, member_mtime=1)
    _write_archive(second, member_mtime=999)

    identical, details, left, right = compare_oci_artifacts(first, second)

    assert identical
    assert left.archive_sha256 != right.archive_sha256
    assert left.files == right.files
    assert "byte-for-byte" in details[0]


def test_different_image_layer_fails_and_reports_changed_file_path(tmp_path: Path):
    first = tmp_path / "first.oci.tar"
    second = tmp_path / "second.oci.tar"
    _write_archive(first, layer_content=b"layer one")
    _write_archive(second, layer_content=b"layer two")

    identical, details, left, right = compare_oci_artifacts(first, second)

    assert not identical
    assert left.files != right.files
    assert any("OCI member differs" in item for item in details)
    assert any("linux/amd64 layer 1" in item for item in details)
    assert any("file bytes differ: payload.txt" in item for item in details)
    assert any("uncompressed rootfs diff_id differs" in item for item in details)


def test_different_compression_with_identical_uncompressed_layer_is_diagnosed(tmp_path: Path):
    first = tmp_path / "gzip-level-one.oci.tar"
    second = tmp_path / "gzip-level-nine.oci.tar"
    _write_archive(first, compression_level=1)
    _write_archive(second, compression_level=9)

    identical, details, _, _ = compare_oci_artifacts(first, second)

    assert not identical
    assert any("uncompressed rootfs diff_id matches" in item for item in details)
    assert any("archive blob differs but member fingerprints match" in item for item in details)


def test_corrupt_blob_is_rejected_even_when_its_filename_claims_another_digest(tmp_path: Path):
    archive = tmp_path / "corrupt.oci.tar"
    _write_archive(archive, corrupt_blob=True)

    with pytest.raises(OCIArtifactError, match="does not match its path digest"):
        inspect_oci_archive(archive)


def test_unsafe_tar_member_is_rejected(tmp_path: Path):
    archive = tmp_path / "unsafe.oci.tar"
    _write_archive(archive, unsafe_member=True)

    with pytest.raises(OCIArtifactError, match="unsafe"):
        inspect_oci_archive(archive)


def test_descriptor_size_mismatch_is_rejected(tmp_path: Path):
    archive = tmp_path / "invalid-size.oci.tar"
    _write_archive(archive, wrong_descriptor_size=True)

    with pytest.raises(OCIArtifactError, match="size does not match"):
        inspect_oci_archive(archive)


def test_unknown_root_media_type_is_rejected(tmp_path: Path):
    archive = tmp_path / "unknown-root-type.oci.tar"
    _write_archive(archive)
    with tarfile.open(archive, mode="r") as source:
        members = {
            item.name: source.extractfile(item).read()
            for item in source.getmembers()
            if item.isfile()
        }
    index = json.loads(members["index.json"])
    index["manifests"][0]["mediaType"] = "application/vnd.example.unknown.v1+json"
    members["index.json"] = _json_bytes(index)
    with tarfile.open(archive, mode="w") as target:
        for name, content in sorted(members.items()):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            target.addfile(member, io.BytesIO(content))

    with pytest.raises(OCIArtifactError, match="not a manifest or index"):
        inspect_oci_archive(archive)
