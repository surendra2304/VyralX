"""Validate OCI layout archives, compare image payloads, and diagnose changed layer members."""

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


@dataclass(frozen=True)
class LayerEntryFingerprint:
    kind: str
    size: int
    mode: int
    uid: int
    gid: int
    mtime: int | float
    linkname: str
    sha256: str | None
    pax_headers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ImageLayers:
    platform: str
    layers: tuple[dict[str, Any], ...]
    diff_ids: tuple[str, ...]


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


def _platform_label(platform: Any) -> str:
    if not isinstance(platform, dict) or not platform:
        return "unspecified"
    os_name = platform.get("os", "?")
    architecture = platform.get("architecture", "?")
    variant = platform.get("variant")
    label = f"{os_name}/{architecture}"
    return f"{label}/{variant}" if isinstance(variant, str) and variant else label


def _read_image_layers(path: str | Path) -> list[ImageLayers]:
    """Read ordered image-layer descriptors for each platform, without extracting files."""
    with tarfile.open(path, mode="r:*") as archive:
        members = {_member_name(member.name): member for member in archive.getmembers()}

        def read_layout_json(blob_path: str, label: str) -> dict[str, Any]:
            member = members.get(blob_path)
            if member is None or member.size > _MAX_METADATA_BYTES:
                raise OCIArtifactError(f"cannot read bounded OCI metadata: {label}")
            stream = archive.extractfile(member)
            if stream is None:
                raise OCIArtifactError(f"cannot read OCI metadata: {label}")
            with stream:
                content = stream.read(_MAX_METADATA_BYTES + 1)
            if len(content) != member.size or len(content) > _MAX_METADATA_BYTES:
                raise OCIArtifactError(f"OCI metadata size is invalid: {label}")
            return _json_object(content, label)

        index = read_layout_json("index.json", "index.json")
        result: list[ImageLayers] = []

        def visit(descriptor: Any, platform: Any, depth: int = 0) -> None:
            if depth > 64 or not isinstance(descriptor, dict):
                raise OCIArtifactError("invalid or deeply nested OCI descriptor")
            digest_value = descriptor.get("digest")
            match = _SHA256.fullmatch(digest_value) if isinstance(digest_value, str) else None
            if match is None:
                raise OCIArtifactError("invalid OCI digest while diagnosing layer differences")
            digest = match.group(0)
            blob_path = f"blobs/sha256/{digest.split(':', 1)[1]}"
            media_type = descriptor.get("mediaType")
            payload = read_layout_json(blob_path, f"descriptor {digest}")
            resolved_platform = descriptor.get("platform") or platform
            if media_type in _INDEX_TYPES:
                children = payload.get("manifests")
                if not isinstance(children, list):
                    raise OCIArtifactError(f"invalid nested OCI index: {digest}")
                for child in children:
                    visit(child, resolved_platform, depth + 1)
                return
            if media_type in _MANIFEST_TYPES:
                layers = payload.get("layers")
                config_descriptor = payload.get("config")
                if not isinstance(layers, list) or not isinstance(config_descriptor, dict):
                    raise OCIArtifactError(f"invalid OCI manifest config/layers: {digest}")
                config_digest_value = config_descriptor.get("digest")
                config_match = (
                    _SHA256.fullmatch(config_digest_value)
                    if isinstance(config_digest_value, str)
                    else None
                )
                if config_match is None:
                    raise OCIArtifactError(f"invalid OCI image config digest: {digest}")
                config_digest = config_match.group(0)
                config_blob_path = f"blobs/sha256/{config_digest.split(':', 1)[1]}"
                config_payload = read_layout_json(config_blob_path, f"image config {config_digest}")
                rootfs = config_payload.get("rootfs")
                raw_diff_ids = rootfs.get("diff_ids") if isinstance(rootfs, dict) else []
                diff_ids = (
                    tuple(item for item in raw_diff_ids if isinstance(item, str))
                    if isinstance(raw_diff_ids, list)
                    else ()
                )
                result.append(
                    ImageLayers(
                        _platform_label(resolved_platform),
                        tuple(layer for layer in layers if isinstance(layer, dict)),
                        diff_ids,
                    )
                )

        manifests = index.get("manifests")
        if not isinstance(manifests, list):
            raise OCIArtifactError("invalid root OCI index for layer diagnostics")
        for descriptor in manifests:
            visit(descriptor, None)
        return result


def _layer_entries(path: str | Path, digest_value: str) -> dict[str, LayerEntryFingerprint]:
    """Fingerprint a compressed or uncompressed OCI layer tar without extracting paths."""
    match = _SHA256.fullmatch(digest_value)
    if match is None:
        raise OCIArtifactError("invalid layer digest while diagnosing difference")
    blob_path = f"blobs/sha256/{match.group(1)}"
    entries: dict[str, LayerEntryFingerprint] = {}

    with tarfile.open(path, mode="r:*") as outer:
        member = next(
            (item for item in outer.getmembers() if _member_name(item.name) == blob_path),
            None,
        )
        if member is None:
            raise OCIArtifactError(f"missing OCI layer blob: {blob_path}")
        layer_stream = outer.extractfile(member)
        if layer_stream is None:
            raise OCIArtifactError(f"cannot read OCI layer blob: {blob_path}")
        with layer_stream:
            with tarfile.open(fileobj=layer_stream, mode="r|*") as layer_tar:
                for info in layer_tar:
                    name = info.name
                    while name.startswith("./"):
                        name = name[2:]
                    name = name.rstrip("/")
                    if name in {"", "."}:
                        continue
                    content_digest: str | None = None
                    if info.isfile():
                        content = layer_tar.extractfile(info)
                        if content is None:
                            raise OCIArtifactError(f"cannot read layer entry: {name}")
                        digest = hashlib.sha256()
                        with content:
                            for chunk in iter(lambda: content.read(1024 * 1024), b""):
                                digest.update(chunk)
                        content_digest = digest.hexdigest()
                    kind = info.type.decode("ascii", "replace") if isinstance(info.type, bytes) else str(info.type)
                    pax = tuple(sorted((str(key), str(value)) for key, value in info.pax_headers.items()))
                    fingerprint = LayerEntryFingerprint(
                        kind=kind,
                        size=info.size,
                        mode=info.mode,
                        uid=info.uid,
                        gid=info.gid,
                        mtime=info.mtime,
                        linkname=info.linkname,
                        sha256=content_digest,
                        pax_headers=pax,
                    )
                    if name in entries:
                        name = f"{name} [duplicate entry]"
                    entries[name] = fingerprint

    return entries


def _append_layer_diagnostics(
    differences: list[str], first_path: str | Path, second_path: str | Path
) -> None:
    """Explain changed manifest layers and point out exact changed tar paths where possible."""
    try:
        first_images = _read_image_layers(first_path)
        second_images = _read_image_layers(second_path)
    except (OCIArtifactError, OSError, tarfile.TarError) as exc:
        differences.append(f"could not inspect image-layer descriptors: {exc}")
        return

    if len(first_images) != len(second_images):
        differences.append(
            f"image manifest count differs: {len(first_images)} != {len(second_images)}"
        )

    for image_index, (left, right) in enumerate(zip(first_images, second_images), start=1):
        if left.platform != right.platform:
            differences.append(
                f"image manifest {image_index} platform differs: {left.platform} != {right.platform}"
            )
        if len(left.layers) != len(right.layers):
            differences.append(
                f"{left.platform}: image layer count differs: {len(left.layers)} != {len(right.layers)}"
            )
        for layer_index, (left_layer, right_layer) in enumerate(
            zip(left.layers, right.layers), start=1
        ):
            left_digest = str(left_layer.get("digest", ""))
            right_digest = str(right_layer.get("digest", ""))
            if left_digest == right_digest:
                continue
            differences.append(
                f"{left.platform} layer {layer_index} digest differs: "
                f"{left_digest} != {right_digest}"
            )
            left_diff_id = (
                left.diff_ids[layer_index - 1]
                if layer_index - 1 < len(left.diff_ids)
                else None
            )
            right_diff_id = (
                right.diff_ids[layer_index - 1]
                if layer_index - 1 < len(right.diff_ids)
                else None
            )
            if left_diff_id and right_diff_id and left_diff_id == right_diff_id:
                differences.append(
                    f"  layer {layer_index}: uncompressed rootfs diff_id matches "
                    f"({left_diff_id}); investigate OCI compression/serialization."
                )
            elif left_diff_id and right_diff_id:
                differences.append(
                    f"  layer {layer_index}: uncompressed rootfs diff_id differs: "
                    f"{left_diff_id} != {right_diff_id}"
                )
            else:
                differences.append(
                    f"  layer {layer_index}: rootfs diff_id is missing from an image config."
                )
            try:
                left_entries = _layer_entries(first_path, left_digest)
                right_entries = _layer_entries(second_path, right_digest)
            except (OCIArtifactError, OSError, tarfile.TarError) as exc:
                differences.append(f"  layer {layer_index}: could not inspect tar members: {exc}")
                continue

            left_names, right_names = set(left_entries), set(right_entries)
            layer_diffs: list[str] = []
            layer_diffs.extend(
                f"  layer {layer_index}: path only in first build: {name}"
                for name in sorted(left_names - right_names)
            )
            layer_diffs.extend(
                f"  layer {layer_index}: path only in second build: {name}"
                for name in sorted(right_names - left_names)
            )
            for name in sorted(left_names & right_names):
                if left_entries[name] == right_entries[name]:
                    continue
                left_entry, right_entry = left_entries[name], right_entries[name]
                reason = "file bytes differ" if left_entry.sha256 != right_entry.sha256 else "tar metadata differs"
                layer_diffs.append(f"  layer {layer_index}: {reason}: {name}")
            if not layer_diffs:
                differences.append(
                    f"  layer {layer_index}: archive blob differs but member fingerprints match"
                )
            else:
                differences.extend(layer_diffs[:12])
                if len(layer_diffs) > 12:
                    differences.append(
                        f"  layer {layer_index}: {len(layer_diffs) - 12} additional differing paths omitted"
                    )


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
    else:
        _append_layer_diagnostics(differences, first_path, second_path)
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
