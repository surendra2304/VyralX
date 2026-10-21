from types import SimpleNamespace

import pytest

from app.services.rights import source_is_publishable


def _pexels_source(source_url: str):
    return SimpleNamespace(
        rights_verified=True,
        license_name="Pexels Content License",
        permission_reference="https://www.pexels.com/license",
        platform="pexels",
        source_url=source_url,
    )


@pytest.mark.parametrize(
    "path",
    [
        "/video/../license",
        "/video/%2e%2e/license",
        "/video/%252e%252e/license",
        "/video/%25252e%25252e/license",
        "/video/%2f..%2flicense",
        "/video/%5c..%5clicense",
    ],
)
def test_pexels_media_path_rejects_traversal_encodings(path):
    assert not source_is_publishable(
        _pexels_source(f"https://www.pexels.com{path}")
    )


def test_pexels_media_path_accepts_normal_video_path():
    assert source_is_publishable(
        _pexels_source("https://www.pexels.com/video/12345/example-clip/")
    )
