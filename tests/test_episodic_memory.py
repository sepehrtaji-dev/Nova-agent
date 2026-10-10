import json
import tempfile
import unittest
from pathlib import Path

from memory.episodic import EpisodicMemory


class EpisodicMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "episodes.json"
        self.memory = EpisodicMemory(path=self.path, max_episodes=3)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_records_minimal_evidence_and_reloads_from_disk(self):
        saved = self.memory.record(
            "Fix parser crash",
            "read_file",
            "confirmed",
            evidence="Regression test passed",
            message="File contents were read",
        )
        self.assertTrue(saved)
        loaded = EpisodicMemory(path=self.path)
        episodes = loaded.recent()
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["tool"], "read_file")
        self.assertEqual(episodes[0]["status"], "confirmed")
        self.assertEqual(episodes[0]["task"], "Fix parser crash")

    def test_redacts_common_secrets_and_does_not_store_raw_payload(self):
        self.memory.record(
            "Use api_key=abc123 for me@example.com",
            "web_search",
            "failed",
            evidence="Bearer abc.def.ghi",
            message="password=hunter2 denied",
        )
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("abc123", raw)
        self.assertNotIn("me@example.com", raw)
        self.assertNotIn("abc.def.ghi", raw)
        self.assertNotIn("hunter2", raw)

    def test_only_known_verification_states_are_kept(self):
        self.memory.record("task", "tool", "surprise", message="unknown state")
        self.assertEqual(self.memory.recent()[0]["status"], "unverifiable")

    def test_history_is_bounded(self):
        for index in range(5):
            self.memory.record(f"task {index}", "tool", "confirmed")
        episodes = self.memory.recent(limit=10)
        self.assertEqual(len(episodes), 3)
        self.assertEqual(episodes[0]["task"], "task 2")

    def test_search_and_context_retrieve_relevant_experience(self):
        self.memory.record(
            "Fix import error",
            "terminal",
            "failed",
            evidence="ModuleNotFoundError in tests",
            message="Command returned a nonzero exit code",
        )
        self.memory.record(
            "Read config",
            "read_file",
            "confirmed",
            evidence="Configuration file opened",
        )
        results = self.memory.search("import error", limit=3)
        self.assertEqual(results[0]["task"], "Fix import error")
        context = self.memory.context("import error")
        self.assertIn("historical evidence", context)
        self.assertIn("ModuleNotFoundError", context)
        self.assertIn("does not prove the current outcome", context)

    def test_clear_removes_persisted_history(self):
        self.memory.record("task", "tool", "confirmed")
        self.assertTrue(self.memory.clear())
        self.assertEqual(self.memory.recent(), [])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
