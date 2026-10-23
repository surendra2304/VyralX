"""Unit tests for VyralX Transformative Commentary Engine."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.transformative_commentator import (
    COMMENTARY_SCRIPTS,
    clean_text_for_drawtext,
)


class TestTransformativeCommentator(unittest.TestCase):
    def test_clean_text_drawtext(self):
        raw = "This is a test: don't use 'quotes' or % symbols! 🐆"
        cleaned = clean_text_for_drawtext(raw)
        self.assertNotIn("'", cleaned)
        self.assertNotIn("🐆", cleaned)
        self.assertIn("This is a test", cleaned)

    def test_commentary_scripts_catalog(self):
        self.assertGreaterEqual(len(COMMENTARY_SCRIPTS), 10)
        for vid, entry in COMMENTARY_SCRIPTS.items():
            self.assertIn("title", entry)
            self.assertIn("script", entry)
            self.assertIn("category", entry)
            self.assertGreater(len(entry["script"]), 20)


if __name__ == "__main__":
    unittest.main()
