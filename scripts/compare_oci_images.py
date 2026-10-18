"""Validate OCI layout archives and compare image payloads byte-for-byte."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MAX_METADATA_BYTES = 4 * 1024 * 1024
_SHA256 = re.compile(r"^sha256:([0-9a-f]{64})$")
_BLOB_PATH = re.compile(r"^blobs/sha256/([0-9a-f]{64})$")
_INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
_MANIFEST_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}


class OCIArtifactError(ValueError):
    """Raised when an OCI layout is invalid or internally inconsistent."""


@dataclass(frozen=True)
class FileFingerprint:
    size: int
    sha256: str


@dataclass(frozen=True)
class OCIArtifact:
    archive_sha256: str
    files: dict[str, FileFingerprint]
    root_digests: tuple[str, ...]


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _member_name(raw_name: str) -> str:
    """Normalize harmless tar prefixes while rejecting traversal and ambiguous paths."""
    if "\x00" in raw_name or "\\" in raw_name or raw_name.startswith("/"):
        raise OCIArtifactError("archive contains an unsafe member path")
    name = raw_name
    while name.startswith("./"):
        name = name[2:]
    name = name.rstrip("/")
    if name in {"", "."}:
        return ""
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise OCIArtifactError("archive contains an unsafe or non-canonical member path")
    return name


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OCIArtifactError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise OCIArtifactError(f"{label} must contain a JSON object")
    return value


def inspect_oci_archive(path: str | Path) -> OCIArtifact:
    """Validate OCI metadata and descriptors without extracting the untrusted tar."""
    archive_path = Path(path)
    if not archive_path.is_file():
        raise OCIArtifactError(f"OCI archive does not exist: {archive_path}")

    fingerprints: dict[str, FileFingerprint] = {}
    small_contents: dict[str, bytes] = {}
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            seen_names: set[str] = set()
            for member in archive.getmembers():
                name = _member_name(member.name)
                if not name or member.isdir():
                    continue
                if not member.isfile():
                    raise OCIArtifactError("archive contains a non-regular file")
                if name in seen_names:
                    raise OCIArtifactError(f"archive contains a duplicate member: {name}")
                seen_names.add(name)
                if name not in {"oci-layout", "index.json"} and not _BLOB_PATH.fullmatch(name):
                    raise OCIArtifactError(f"unexpected OCI layout member: {name}")
                if member.size < 0:
                    raise OCIArtifactError("archive contains a negative file size")
                if name in {"oci-layout", "index.json"} and member.size > _MAX_METADATA_BYTES:
                    raise OCIArtifactError(f"{name} exceeds the metadata size limit")

                stream = archive.extractfile(member)
                if stream is None:
                    raise OCIArtifactError(f"cannot read OCI layout member: {name}")
                digest = hashlib.sha256()
                captured: list[bytes] | None = [] if member.size <= _MAX_METADATA_BYTES else None
                actual_size = 0
                with stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                        actual_size += len(chunk)
                        if captured is not None:
                            captured.append(chunk)
                if actual_size != member.size:
                    raise OCIArtifactError(f"truncated OCI layout member: {name}")
                fingerprints[name] = FileFingerprint(actual_size, digest.hexdigest())
                if captured is not None:
                    small_contents[name] = b"".join(captured)
    except (tarfile.TarError, OSError) as exc:
        raise OCIArtifactError("cannot read OCI archive") from exc

    for required in ("oci-layout", "index.json"):
        if required not in fingerprints:
            raise OCIArtifactError(f"OCI archive is missing {required}")

    layout = _json_object(small_contents["oci-layout"], "oci-layout")
    if layout.get("imageLayoutVersion") != "1.0.0":
        raise OCIArtifactError("unsupported OCI image layout version")
    index = _json_object(small_contents["index.json"], "index.json")
    manifests = index.get("manifests")
    if index.get("schemaVersion") != 2 or not isinstance(manifests, list) or not manifests:
        raise OCIArtifactError("index.json must contain schemaVersion 2 and at least one manifest")

    blob_paths: dict[str, str] = {}
    for name, fingerprint in fingerprints.items():
        match = _BLOB_PATH.fullmatch(name)
        if not match:
            continue
        digest = match.group(1)
        if fingerprint.sha256 != digest:
            raise OCIArtifactError(f"blob content does not match its path digest: {name}")
        blob_paths[f"sha256:{digest}"] = name

    def validate_descriptor(descriptor: Any) -> tuple[str, str, str]:
        """Validate any descriptor target, including opaque config/layer blobs."""
        if not isinstance(descriptor, dict):
            raise OCIArtifactError("OCI index or manifest contains an invalid descriptor")
        digest_value = descriptor.get("digest")
        digest_match = _SHA256.fullmatch(digest_value) if isinstance(digest_value, str) else None
        if digest_match is None:
            raise OCIArtifactError("OCI descriptor uses an unsupported digest")
        digest = digest_match.group(0)
        blob_path = blob_paths.get(digest)
        if blob_path is None:
            raise OCIArtifactError(f"OCI descriptor references a missing blob: {digest}")
        actual = fingerprints[blob_path]
        declared_size = descriptor.get("size")
        if (
            not isinstance(declared_size, int)
            or isinstance(declared_size, bool)
            or declared_size != actual.size
        ):
            raise OCIArtifactError(f"OCI descriptor size does not match its blob: {digest}")
        media_type = descriptor.get("mediaType")
        if not isinstance(media_type, str) or not media_type:
            raise OCIArtifactError("OCI descriptor has an invalid media type")
        return digest, blob_path, media_type

    visited: set[str] = set()

    def visit_manifest_or_index(descriptor: Any, depth: int = 0) -> None:
        if depth > 64:
            raise OCIArtifactError("OCI descriptor nesting exceeds the validation limit")
        digest, blob_path, media_type = validate_descriptor(descriptor)
        if media_type not in _INDEX_TYPES | _MANIFEST_TYPES:
            raise OCIArtifactError(f"OCI root/index descriptor is not a manifest or index: {digest}")
        if digest in visited:
            return
        visited.add(digest)
        content = small_contents.get(blob_path)
        if content is None:
            raise OCIArtifactError(f"OCI manifest metadata exceeds the size limit: {digest}")
        payload = _json_object(content, f"manifest {digest}")
        if media_type in _INDEX_TYPES:
            children = payload.get("manifests")
            if not isinstance(children, list) or not children:
                raise OCIArtifactError(f"OCI index has an invalid manifests list: {digest}")
            for child in children:
                visit_manifest_or_index(child, depth + 1)
            return

        config = payload.get("config")
        layers = payload.get("layers")
        if not isinstance(config, dict) or not isinstance(layers, list):
            raise OCIArtifactError(f"OCI manifest is missing config or layers: {digest}")
        validate_descriptor(config)
        for layer in layers:
            validate_descriptor(layer)
        subject = payload.get("subject")
        if subject is not None:
            validate_descriptor(subject)

    for descriptor in manifests:
        visit_manifest_or_index(descriptor)

    root_digests_list: list[str] = []
    for item in manifests:
        if not isinstance(item, dict) or not isinstance(item.get("digest"), str):
            raise OCIArtifactError("index.json contains an invalid root descriptor")
        root_digests_list.append(item["digest"])
    return OCIArtifact(_hash_file(archive_path), fingerprints, tuple(root_digests_list))


def compare_oci_artifacts(
    first_path: str | Path, second_path: str | Path
) -> tuple[bool, list[str], OCIArtifact, OCIArtifact]:
    """Compare all OCI layout files, ignoring only the enclosing tar serialization."""
    first = inspect_oci_archive(first_path)
    second = inspect_oci_archive(second_path)
    differences: list[str] = []
    first_names, second_names = set(first.files), set(second.files)
    for name in sorted(first_names - second_names):
        differences.append(f"second archive is missing member: {name}")
    for name in sorted(second_names - first_names):
        differences.append(f"second archive has an extra member: {name}")
    for name in sorted(first_names & second_names):
        if first.files[name] != second.files[name]:
            differences.append(f"OCI member differs: {name}")
    identical = not differences
    if identical:
        differences.append(
            "All OCI layout members match byte-for-byte; outer tar serialization is not part of the image."
        )
    return identical, differences, first, second


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and compare two independent OCI image-layout archives."
    )
    parser.add_argument("first", type=Path, help="first OCI archive")
    parser.add_argument("second", type=Path, help="second OCI archive")
    args = parser.parse_args(argv)

    try:
        identical, details, first, second = compare_oci_artifacts(args.first, args.second)
    except (OCIArtifactError, OSError) as exc:
        print(f"ERROR: OCI artifact validation failed: {exc}", file=sys.stderr)
        return 2

    if identical:
        blob_count = sum(name.startswith("blobs/sha256/") for name in first.files)
        print("PASS: independent OCI image layouts are byte-for-byte identical.")
        print(f"First outer archive SHA-256:  {first.archive_sha256}")
        print(f"Second outer archive SHA-256: {second.archive_sha256}")
        if first.archive_sha256 != second.archive_sha256:
            print("Note: enclosing tar metadata/serialization differs; OCI member contents match.")
        print("Root manifest digest(s): " + ", ".join(first.root_digests))
        print(f"Verified OCI blobs: {blob_count}")
        return 0

    print("FAIL: independent OCI image layouts differ.", file=sys.stderr)
    print("First root manifest digest(s): " + ", ".join(first.root_digests), file=sys.stderr)
    print("Second root manifest digest(s): " + ", ".join(second.root_digests), file=sys.stderr)
    for detail in details:
        print(f"- {detail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
