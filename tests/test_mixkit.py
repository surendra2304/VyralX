import pytest
from app.services.mixkit import search_videos, import_video_file


def test_search_videos_returns_candidates():
    results = search_videos("technology", max_results=5)
    assert isinstance(results, list)
    if results:
        first = results[0]
        assert "id" in first
        assert "download_url" in first
        assert first["download_url"].endswith(".mp4")


def test_search_videos_empty_query_falls_back():
    results = search_videos("", max_results=3)
    assert isinstance(results, list)


def test_import_video_file_fails_gracefully_on_invalid_url():
    with pytest.raises(RuntimeError):
        import_video_file("999999999", "https://invalid.example.com/notfound.mp4")
