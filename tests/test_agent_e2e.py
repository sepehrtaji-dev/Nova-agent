"""Integration tests that exercise Nova components together without a live model or OS tools."""

import json
import tempfile
import unittest
from pathlib import Path

from agent.planner import Planner
from agent.router import ToolRouter
from memory.extractor import MemoryExtractor
from memory.storage import MemoryStorage
from tools.registry import ToolRegistry


class ScriptedBrain:
    """Deterministic model boundary: tests the real consumers, not model quality."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("Unexpected model call")
        return self.responses.pop(0)


class AgentPipelineE2ETests(unittest.TestCase):
    def test_planner_router_registry_and_real_tool_execution(self):
        """A model plan is normalized, routed, schema-checked, and executed."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.txt"
            tools = ToolRegistry()
            tools.register(
                "write_note",
                "Write text to a test workspace file",
                lambda payload: (
                    Path(payload["path"]).write_text(payload["content"], encoding="utf-8")
                    and "WRITE_OK"
                ),
                capability="filesystem",
                input_schema={
                    "type": "object",
                    "required": ["path", "content"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "content": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            )
            brain = ScriptedBrain([
                json.dumps({
                    "goal": "write the requested note",
                    "steps": [{
                        "description": "Write the note to the requested path",
                        "tool": "write_note",
                        "input": {"path": str(target), "content": "Nova E2E"},
                    }],
                })
            ])
            planner = Planner(brain, tools)
            router = ToolRouter(brain, tools)

            plan = planner.create_plan(
                "write Nova E2E to the test file",
                allowed_tools=["write_note"],
            )
            self.assertEqual(len(plan["steps"]), 1)
            self.assertEqual(plan["steps"][0]["tool"], "write_note")

            decision = router.decide(
                message="write Nova E2E to the test file",
                task_type="computer",
                plan=planner.get_plan_summary(plan),
                allowed_tools=["write_note"],
            )
            self.assertEqual(decision["action"], "tool")
            self.assertEqual(decision["tool"], "write_note")
            payload = json.loads(decision["input"])
            valid, reason = tools.validate_input("write_note", payload)
            self.assertTrue(valid, reason)

            result = tools.execute("write_note", payload)
            self.assertEqual(result, "WRITE_OK")
            self.assertEqual(target.read_text(encoding="utf-8"), "Nova E2E")
            self.assertEqual(brain.responses, [])

    def test_memory_extraction_survives_storage_round_trip(self):
        """Explicit Persian profile information survives extraction and disk IO."""
        class MemoryBrain:
            def generate(self, prompt, **kwargs):
                return json.dumps({
                    "memories": [{
                        "category": "profile",
                        "key": "name",
                        "value": "سپهر",
                    }]
                }, ensure_ascii=False)

        message = "اسم من سپهره"
        extractor = MemoryExtractor(MemoryBrain())
        self.assertTrue(extractor.should_extract(message))
        extracted = extractor.extract(message)
        self.assertEqual(extracted["memories"][0]["value"], "سپهر")

        with tempfile.TemporaryDirectory() as directory:
            storage = MemoryStorage(str(Path(directory) / "long_term.json"))
            storage.save({
                "profile": {"name": extracted["memories"][0]["value"]},
                "projects": [],
                "skills": [],
                "preferences": [],
                "facts": [],
            })
            restored = storage.load()
            self.assertEqual(restored["profile"]["name"], "سپهر")

    def test_memory_storage_preserves_corrupt_source_and_recovers_backup(self):
        """Recovery uses a valid backup and leaves the damaged source untouched."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long_term.json"
            path.write_text("{broken", encoding="utf-8")
            backup = Path(str(path) + ".bak")
            backup.write_text(
                json.dumps({"profile": {"name": "سپهر"}}, ensure_ascii=False),
                encoding="utf-8",
            )

            restored = MemoryStorage(str(path)).load()

            self.assertEqual(restored["profile"]["name"], "سپهر")
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
            self.assertEqual(Path(str(path) + ".corrupted").read_text(encoding="utf-8"), "{broken")


if __name__ == "__main__":
    unittest.main()
