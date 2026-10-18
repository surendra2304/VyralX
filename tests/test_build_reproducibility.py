"""Regression checks for hash-locked PEP 517 build dependencies."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXACT_REQUIREMENT = re.compile(r"([A-Za-z0-9_.-]+)==([^\s;]+)")
SHA256_HASH = re.compile(r"sha256:[0-9a-f]{64}")


def test_pep517_build_dependencies_are_exactly_pinned_and_hash_checked():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build_system = metadata["build-system"]
    declared = {}
    for value in build_system["requires"]:
        match = EXACT_REQUIREMENT.fullmatch(value)
        assert match, f"Build dependency must use an exact version: {value}"
        name, version = match.groups()
        normalized_name = name.lower().replace("_", "-")
        assert normalized_name not in declared, f"Duplicate build dependency: {name}"
        declared[normalized_name] = f"{normalized_name}=={version}"

    uv_settings = metadata["tool"]["uv"]
    assert uv_settings.get("require-build-hashes") is True
    constraints = {}
    for item in uv_settings["build-constraint-dependencies"]:
        requirement = item["requirement"]
        match = EXACT_REQUIREMENT.fullmatch(requirement)
        assert match, f"Build constraint must use an exact version: {requirement}"
        name, version = match.groups()
        normalized_name = name.lower().replace("_", "-")
        assert normalized_name not in constraints, f"Duplicate build constraint: {name}"
        hashes = item.get("hashes")
        assert isinstance(hashes, list) and hashes, f"Build constraint has no hashes: {name}"
        assert all(SHA256_HASH.fullmatch(value) for value in hashes), (
            f"Build constraint has an invalid SHA-256: {name}"
        )
        constraints[normalized_name] = f"{normalized_name}=={version}"

    assert declared == constraints
