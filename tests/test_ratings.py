"""Synthetic offline tests. Ratings never retain private message content."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest
from unittest.mock import patch

from chatpulse.ratings import RatingError, rate_last, record_digest


class RatingsTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "private" / "ratings.json"
        override = patch("chatpulse.ratings.rating_file_path", return_value=self.path)
        override.start()
        self.addCleanup(override.stop)

    def test_rating_last_digest_retains_only_safe_run_metadata(self):
        run_id = record_digest(model="qwen3.5:9b", count=376,
                               chunks=3, seconds=423,
                               has_vision=True, sample=False)
        stored_id = rate_last(5)
        self.assertEqual(run_id, stored_id)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["runs"]), 1)
        record = data["runs"][0]
        self.assertEqual(record["score"], 5)
        self.assertEqual(record["model"], "qwen3.5:9b")
        self.assertEqual(record["messages"], 376)
        self.assertTrue(record["vision"])
        self.assertEqual(
            set(record), {
                "id", "created_at", "model", "messages", "chunks",
                "generation_seconds", "vision", "sample", "score",
            }
        )
        self.assertNotIn("chat_text", self.path.read_text())
        if os.name != "nt":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)

    def test_no_rating_without_run_or_after_rating(self):
        with self.assertRaises(RatingError):
            rate_last(4)
        record_digest(model="qwen3.5:9b", count=25, chunks=1,
                      seconds=30, has_vision=False, sample=True)
        rate_last(2)
        with self.assertRaises(RatingError):
            rate_last(3)
        self.assertEqual(json.loads(self.path.read_text())["runs"][-1]["score"], 2)

    def test_invalid_scores_fail_before_writing(self):
        for score in (-1, 0, 6, True, "5"):
            with self.subTest(score=score), self.assertRaises(RatingError):
                rate_last(score)
        self.assertFalse(self.path.exists())

    def test_only_last_100_runs_kept(self):
        for i in range(105):
            record_digest(model="qwen3.5:9b", count=i + 1, chunks=1,
                          seconds=i, has_vision=False, sample=False)
        data = json.loads(self.path.read_text())
        self.assertEqual(len(data["runs"]), 100)
        self.assertEqual(data["runs"][0]["messages"], 6)
        self.assertEqual(data["runs"][-1]["messages"], 105)

    def test_symlink_target_rejected(self):
        source = Path(self.tempdir.name) / "other.json"
        source.write_text("PRIVATE", encoding="utf-8")
        self.path.parent.mkdir()
        self.path.symlink_to(source)
        with self.assertRaises(RatingError):
            record_digest(model="qwen3.5:9b", count=1, chunks=1,
                          seconds=1, has_vision=False, sample=False)
        self.assertEqual(source.read_text(), "PRIVATE")


if __name__ == "__main__":
    unittest.main()
