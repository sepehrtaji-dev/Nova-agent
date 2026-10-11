import tempfile
import unittest
from pathlib import Path

from memory.manager import MemoryManager


class MemoryManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "long_term.json"
        self.memory = MemoryManager(path=str(self.path))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_remember_updates_existing_key_and_persists(self):
        self.memory.remember("profile", "gpu", "RTX 3060")
        self.memory.remember("profile", "gpu", "RTX 4070")

        reloaded = MemoryManager(path=str(self.path))
        self.assertEqual(reloaded.get_memory()["profile"]["gpu"], "RTX 4070")
        self.assertEqual(len([item for item in reloaded.entries() if item["key"] == "profile.gpu"]), 1)

    def test_entries_flattens_nested_memory(self):
        self.memory.remember("profile", "language", "Persian")
        entries = self.memory.entries()
        self.assertIn({"key": "profile.language", "value": "Persian"}, entries)

    def test_forget_removes_only_the_exact_key_and_persists(self):
        self.memory.remember("profile", "language", "Persian")
        self.memory.remember("profile", "gpu", "RTX 3060")

        self.assertTrue(self.memory.forget("profile", "language"))
        self.assertFalse(self.memory.forget("profile", "language"))

        reloaded = MemoryManager(path=str(self.path))
        self.assertNotIn("language", reloaded.get_memory()["profile"])
        self.assertEqual(reloaded.get_memory()["profile"]["gpu"], "RTX 3060")

    def test_forget_supports_list_based_categories(self):
        self.memory.remember("projects", "nova", "Local AI agent")
        self.memory.remember("projects", "chess", "Chess model")

        self.assertTrue(self.memory.forget("projects", "nova"))
        self.assertEqual(self.memory.get_memory()["projects"], [{"chess": "Chess model"}])

    def test_invalid_memory_inputs_are_rejected(self):
        with self.assertRaises(TypeError):
            self.memory.remember("", "key", "value")
        with self.assertRaises(TypeError):
            self.memory.remember("profile", "", "value")
        with self.assertRaises(TypeError):
            self.memory.remember("profile", "key", None)


    def test_graphics_card_question_matches_gpu_memory_key(self):
        self.memory.remember("profile", "gpu", "RTX 3060")

        matches = self.memory.relevant("what graphics card do I use?")

        self.assertTrue(matches)
        self.assertEqual(matches[0]["key"], "profile.gpu")
        self.assertEqual(matches[0]["value"], "RTX 3060")

    def test_persian_graphics_card_question_matches_gpu_memory_key(self):
        self.memory.remember("profile", "gpu", "RTX 3060")

        matches = self.memory.relevant("کارت گرافیکم چیه؟")

        self.assertTrue(matches)
        self.assertEqual(matches[0]["key"], "profile.gpu")
        self.assertEqual(matches[0]["value"], "RTX 3060")

    def test_empty_or_irrelevant_query_returns_no_match(self):
        self.memory.remember("profile", "gpu", "RTX 3060")

        self.assertEqual(self.memory.relevant("what is my favorite food"), [])
        self.assertEqual(self.memory.relevant("   "), [])


if __name__ == "__main__":
    unittest.main()
