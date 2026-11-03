import json
import tempfile
import unittest
from pathlib import Path

from memory.extractor import MemoryExtractor
from memory.episodic import EpisodicMemory
from memory.knowledge import KnowledgeMemory
from tools.registry import ToolRegistry


class FakeBrain:
    def generate(self, prompt, **kwargs):
        return json.dumps({
            "memories": [
                {"category": "profile", "key": "name", "value": "سپهر"}
            ]
        }, ensure_ascii=False)


class MemoryReliabilityTests(unittest.TestCase):
    def test_persian_personal_statement_triggers_extraction(self):
        extractor = MemoryExtractor(FakeBrain())
        self.assertTrue(extractor.should_extract("اسم من سپهره"))

    def test_persian_memory_value_is_retained_when_explicitly_present(self):
        extractor = MemoryExtractor(FakeBrain())
        result = extractor.extract("اسم من سپهره")
        self.assertEqual(result["memories"][0]["value"], "سپهر")

    def test_episodic_search_uses_token_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = EpisodicMemory(path=Path(directory) / "episodes.json")
            memory.record("concatenate strings", "tool_a", "confirmed")
            memory.record("cat behavior", "tool_b", "confirmed")
            results = memory.search("cat")
            self.assertEqual(results[0]["tool"], "tool_b")
            self.assertEqual(len(results), 1)

    def test_episodic_ties_prefer_newest_record(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = EpisodicMemory(path=Path(directory) / "episodes.json")
            memory._episodes = [
                {"timestamp": "2024-01-01T00:00:00+00:00", "task": "same task", "tool": "old", "status": "confirmed"},
                {"timestamp": "2025-01-01T00:00:00+00:00", "task": "same task", "tool": "new", "status": "confirmed"},
            ]
            self.assertEqual(memory.search("same task")[0]["tool"], "new")

    def test_knowledge_ties_prefer_recently_verified_fact(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = KnowledgeMemory(path=str(Path(directory) / "knowledge.json"))
            memory.data = [
                {"topic": "Nova", "fact": "agent", "confidence": 0.8, "last_verified": "2024-01-01T00:00:00+00:00"},
                {"topic": "Nova", "fact": "agent", "confidence": 0.8, "last_verified": "2025-01-01T00:00:00+00:00"},
            ]
            self.assertEqual(memory.search("Nova agent")[0]["last_verified"], "2025-01-01T00:00:00+00:00")


class ToolContractReliabilityTests(unittest.TestCase):
    def test_nested_object_and_array_schema_validation(self):
        registry = ToolRegistry()
        registry.register(
            "example",
            "Example tool",
            lambda payload: payload,
            input_schema={
                "type": "object",
                "required": ["config"],
                "properties": {
                    "config": {
                        "type": "object",
                        "required": ["retries", "tags"],
                        "properties": {
                            "retries": {"type": "integer", "minimum": 1, "maximum": 5},
                            "tags": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string", "minLength": 2},
                            },
                        },
                        "additionalProperties": False,
                    }
                },
            },
        )
        valid, reason = registry.validate_input(
            "example", {"config": {"retries": 3, "tags": ["ok"]}}
        )
        self.assertTrue(valid, reason)

    def test_nested_schema_rejects_out_of_range_and_bad_array_items(self):
        registry = ToolRegistry()
        registry.register(
            "example",
            "Example tool",
            lambda payload: payload,
            input_schema={
                "type": "object",
                "properties": {
                    "config": {
                        "type": "object",
                        "properties": {
                            "retries": {"type": "integer", "maximum": 5},
                            "tags": {"type": "array", "items": {"type": "string", "minLength": 2}},
                        },
                    }
                },
            },
        )
        valid, _ = registry.validate_input(
            "example", {"config": {"retries": 6, "tags": ["x"]}}
        )
        self.assertFalse(valid)

    def test_boolean_is_not_accepted_as_integer(self):
        registry = ToolRegistry()
        registry.register(
            "example",
            "Example tool",
            lambda payload: payload,
            input_schema={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
            },
        )
        valid, _ = registry.validate_input("example", {"count": True})
        self.assertFalse(valid)


if __name__ == "__main__":
    unittest.main()
