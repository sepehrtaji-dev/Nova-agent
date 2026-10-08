import os
import tempfile
import unittest
from datetime import datetime, timedelta

from memory.embeddings import EmbeddingModel
from memory.knowledge import KnowledgeMemory
from memory.short_term import ShortTermMemory
from memory.vector_memory import VectorMemory


class MemoryTests(unittest.TestCase):
    def test_short_term_memory_keeps_a_reasonable_window(self):
        memory = ShortTermMemory(limit=40)
        for index in range(45):
            memory.add("user", f"message {index}")

        items = memory.get()
        self.assertEqual(len(items), 40)
        self.assertEqual(items[0]["content"], "message 5")
        self.assertEqual(items[-1]["content"], "message 44")

    def test_short_term_prompt_format_preserves_roles(self):
        memory = ShortTermMemory(limit=4)
        memory.add("user", "first")
        memory.add("assistant", "second")
        memory.add("tool", "verified result")

        rendered = memory.format_for_prompt()
        self.assertIn("user:", rendered)
        self.assertIn("assistant:", rendered)
        self.assertIn("tool:", rendered)
        self.assertIn("verified result", rendered)

    def test_knowledge_ignores_expired_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "knowledge.json")
            memory = KnowledgeMemory(path=path)

            memory.add(
                "current topic",
                "this fact is expired",
                freshness="volatile",
            )
            memory.data[-1]["expires_at"] = (
                datetime.utcnow() - timedelta(days=1)
            ).isoformat()
            memory._save()

            memory.add(
                "current topic",
                "this fact is valid",
                freshness="volatile",
            )

            results = memory.search("current topic")
            facts = [item["fact"] for item in results]
            self.assertIn("this fact is valid", facts)
            self.assertNotIn("this fact is expired", facts)

    def test_embedding_is_deterministic_without_model_download(self):
        model = EmbeddingModel(dimensions=64)
        left = model.encode("Nova local agent")
        right = model.encode("Nova local agent")
        self.assertEqual(left, right)
        self.assertEqual(len(left), 64)

    def test_vector_memory_handles_empty_and_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "memories.json")
            memory = VectorMemory(path=path, dimensions=64)
            self.assertEqual(memory.search("anything"), [])

            memory.add("Nova can edit Python files")
            memory.add("Chess uses a board")
            result = memory.search("Python files", limit=1)

            self.assertEqual(len(result), 1)
            self.assertIn("Python", result[0])


if __name__ == "__main__":
    unittest.main()
