"""Regression tests for project-scene provenance checks."""
from types import SimpleNamespace

from app.services.rights import is_project_scene_publishable


def test_project_scene_requires_official_pexels_source_and_license_evidence():
    asset = SimpleNamespace(rights_verified=True)
    source = SimpleNamespace(
        platform="pexels",
        rights_verified=True,
        license_name="Pexels Content License",
        source_url="https://www.pexels.com/video/123456/",
        permission_reference="https://www.pexels.com/license/",
    )
    assert is_project_scene_publishable(asset, source)


def test_project_scene_rejects_forged_source_url_and_non_pexels_platform():
    asset = SimpleNamespace(rights_verified=True)
    forged = SimpleNamespace(
        platform="pexels",
        rights_verified=True,
        license_name="Pexels Content License",
        source_url="https://not-pexels.example/video/123456/",
        permission_reference="https://www.pexels.com/license/",
    )
    assert not is_project_scene_publishable(asset, forged)

    non_pexels = SimpleNamespace(
        platform="youtube",
        rights_verified=True,
        license_name="Written permission",
        source_url="https://www.youtube.com/watch?v=123456",
        permission_reference="permission-record-2026",
    )
    assert not is_project_scene_publishable(asset, non_pexels)


def test_project_scene_rejects_unverified_or_missing_provenance():
    valid_source = SimpleNamespace(
        platform="pexels",
        rights_verified=True,
        license_name="Pexels Content License",
        source_url="https://www.pexels.com/video/123456/",
        permission_reference="https://www.pexels.com/license/",
    )
    assert not is_project_scene_publishable(SimpleNamespace(rights_verified=False), valid_source)
    assert not is_project_scene_publishable(SimpleNamespace(rights_verified=True), None)
    assert not is_project_scene_publishable(None, valid_source)
