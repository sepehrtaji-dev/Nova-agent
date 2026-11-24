import json
import unittest
from unittest import mock

from tools.subagents import SubagentTool


class FakeBrain:
    def __init__(self):
        self.effort = None

    def set_effort(self, value):
        self.effort = value


class FakeCore:
    latest = None

    def __init__(self):
        self.access = {}
        self.brain = FakeBrain()
        self.tools = type("Registry", (), {"tools": {"spawn_subagent": object(), "read_file": object()}})()
        self.prompt = ""
        FakeCore.latest = self

    def set_access(self, **access):
        self.access = dict(access)

    def ask(self, prompt):
        self.prompt = prompt
        return "child result"


class FailingCore(FakeCore):
    def ask(self, prompt):
        raise RuntimeError("child unavailable")


class SubagentToolTests(unittest.TestCase):
    def test_child_inherits_permissions_and_cannot_spawn_children(self):
        tool = SubagentTool()
        prepared = tool.prepare_input(
            {"task": "Inspect the API design."},
            {"parent_access": {"pc": True, "web": False}, "parent_effort": "high"},
        )
        with mock.patch("agent.core.NovaCore", FakeCore):
            result = json.loads(tool.run(json.dumps(prepared)))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"], "child result")
        self.assertEqual(FakeCore.latest.access, {"pc": True, "web": False})
        self.assertNotIn("spawn_subagent", FakeCore.latest.tools.tools)
        self.assertEqual(FakeCore.latest.brain.effort, "high")
        self.assertIn("Inspect the API design.", FakeCore.latest.prompt)

    def test_child_failure_returns_a_tool_result_instead_of_raising(self):
        tool = SubagentTool()
        prepared = tool.prepare_input({"task": "Investigate a bug."}, {})
        with mock.patch("agent.core.NovaCore", FailingCore):
            result = json.loads(tool.run(json.dumps(prepared)))
        self.assertEqual(result["status"], "failed")
        self.assertIn("child unavailable", result["error"])

    def test_empty_subtask_is_rejected_without_starting_child(self):
        tool = SubagentTool()
        result = json.loads(tool.run(json.dumps({"task": "  "})))
        self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
