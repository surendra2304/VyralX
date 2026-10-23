from unittest.mock import MagicMock, patch
import pytest
from app.services.ai_visuals import generate_scene_visual


def test_generate_scene_visual_mocked(tmp_path, monkeypatch):
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "media_dir", tmp_path)

    # Mock httpx.Client
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # Minimal 1x1 JPEG header + bytes > 1000
    mock_resp.content = b"\xff\xd8\xff\xe0" + b"\x00" * 1500

    with patch("httpx.Client.get", return_value=mock_resp), \
         patch("app.services.ai_visuals.probe_media", return_value={"duration_seconds": 0.04, "width": 1080, "height": 1920}):
        res = generate_scene_visual("quantum computer")
        assert "visual_id" in res
        assert "file_path" in res
        assert res["metadata"]["width"] == 1080
        assert res["metadata"]["height"] == 1920
