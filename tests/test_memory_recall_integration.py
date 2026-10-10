import tempfile
import unittest
from pathlib import Path

from agent.core import NovaCore
from memory.manager import MemoryManager


class MemoryRecallIntegrationTests(unittest.TestCase):
    def test_saved_memory_is_retrievable_by_relevant_query(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "long_term.json"
            memory = MemoryManager(path=str(path))
            memory.remember("profile", "gpu", "RTX 3060")
            memory.remember("preferences", "language", "Persian")

            matches = memory.relevant("what is my gpu", limit=3)

            self.assertTrue(matches)
            self.assertEqual(matches[0]["key"], "profile.gpu")
            self.assertEqual(matches[0]["value"], "RTX 3060")

    def test_direct_memory_answer_uses_saved_fact_not_model_guess(self):
        class FakeLongMemory:
            def relevant(self, query, limit=3):
                self.asserted_query = query
                return [
                    {"key": "profile.gpu", "value": "RTX 3060", "score": 2}
                ]

        core = NovaCore.__new__(NovaCore)
        core.long_memory = FakeLongMemory()

        answer = core._direct_memory_answer("what is my gpu?")

        self.assertEqual(
            answer,
            "According to your saved memory, profile gpu is RTX 3060.",
        )
        self.assertEqual(core.long_memory.asserted_query, "what is my gpu?")

    def test_direct_memory_answer_does_not_guess_when_no_match(self):
        class FakeLongMemory:
            def relevant(self, query, limit=3):
                return []

        core = NovaCore.__new__(NovaCore)
        core.long_memory = FakeLongMemory()

        self.assertIsNone(core._direct_memory_answer("what is my GPU?"))

    def test_direct_memory_answer_ignores_low_confidence_match(self):
        class FakeLongMemory:
            def relevant(self, query, limit=3):
                return [
                    {"key": "profile.gpu", "value": "Unknown", "score": 1}
                ]

        core = NovaCore.__new__(NovaCore)
        core.long_memory = FakeLongMemory()

        self.assertIsNone(core._direct_memory_answer("what is my GPU?"))


if __name__ == "__main__":
    unittest.main()
