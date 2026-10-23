"""Unit tests for VyralX Multi-Project Google Cloud Quota Rotator."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from app.services.quota_rotator import (
    get_all_project_tokens,
    is_project_exhausted,
    mark_project_exhausted,
)


class TestQuotaRotator(unittest.TestCase):
    def test_quota_exhaustion_cycle(self):
        with TemporaryDirectory() as tmp_dir:
            token_path = Path(tmp_dir) / "token.json"
            token_path.write_text("{}", encoding="utf-8")

            with patch("app.services.quota_rotator.QUOTA_TRACKER_FILE", str(Path(tmp_dir) / "quota.json")):
                self.assertFalse(is_project_exhausted(token_path))
                mark_project_exhausted(token_path, "Quota exceeded 429")
                self.assertTrue(is_project_exhausted(token_path))


if __name__ == "__main__":
    unittest.main()
