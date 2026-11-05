import json
import unittest

from agent.tool_loop import ToolCallingLoop
from tools.registry import ToolRegistry


class ScriptedToolBrain:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def generate_tool_turn(self, *, messages, tools, system_prompt):
        self.calls.append({
            "messages": json.loads(json.dumps(messages)),
            "tools": tools,
            "system_prompt": system_prompt,
        })
        if not self.turns:
            raise AssertionError("Unexpected model turn")
        return self.turns.pop(0)


class Confirmed:
    status = "confirmed"
    message = "The operation was verified."
    evidence = "test evidence"

    @staticmethod
    def confirmed():
        return True


class FakeVerifier:
    def verify(self, name, encoded, result):
        return Confirmed()


class ToolCallingLoopTests(unittest.TestCase):
    def make_registry(self):
        registry = ToolRegistry()
        registry.register(
            "read_note",
            "Read a note from the test workspace.",
            lambda payload: "NOTE CONTENT: " + json.loads(payload)["path"],
            capability="filesystem",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        )
        registry.register(
            "write_note",
            "Write a note in the test workspace.",
            lambda payload: "WROTE " + json.loads(payload)["path"] + ": " + json.loads(payload)["content"],
            capability="filesystem",
            input_schema={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "content": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
        )
        return registry

    def test_model_drives_read_then_write_then_final_answer(self):
        registry = self.make_registry()
        brain = ScriptedToolBrain([
            {
                "content": "",
                "tool_calls": [{
                    "id": "call_read",
                    "type": "function",
                    "function": {
                        "name": "read_note",
                        "arguments": '{"path":"todo.txt"}',
                    },
                }],
            },
            {
                "content": "",
                "tool_calls": [{
                    "id": "call_write",
                    "type": "function",
                    "function": {
                        "name": "write_note",
                        "arguments": {"path": "todo.txt", "content": "updated"},
                    },
                }],
            },
            {"content": "The note was updated and verified.", "tool_calls": []},
        ])
        verified = []
        loop = ToolCallingLoop(
            brain, registry, FakeVerifier(), ["read_note", "write_note"],
            on_result=lambda *args: verified.append(args[0]),
        )

        answer = loop.run("Inspect and update todo.txt", system_prompt="Nova test")

        self.assertEqual(answer, "The note was updated and verified.")
        self.assertEqual(verified, ["read_note", "write_note"])
        self.assertEqual(len(brain.calls), 3)
        second_messages = brain.calls[1]["messages"]
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertIn("NOTE CONTENT", second_messages[-1]["content"])
        third_messages = brain.calls[2]["messages"]
        self.assertEqual(third_messages[-1]["role"], "tool")
        self.assertIn("WROTE todo.txt", third_messages[-1]["content"])

    def test_disabled_tool_is_not_executed(self):
        registry = self.make_registry()
        executed = []
        registry.register(
            "unsafe_test",
            "A test-only tool that must not run when disabled.",
            lambda payload: executed.append(payload) or "unexpected",
            capability="disabled",
            input_schema={"type": "object", "properties": {}},
        )
        brain = ScriptedToolBrain([
            {
                "content": "",
                "tool_calls": [{
                    "id": "call_disabled",
                    "type": "function",
                    "function": {"name": "unsafe_test", "arguments": "{}"},
                }],
            },
            {"content": "I could not use that disabled tool.", "tool_calls": []},
        ])
        loop = ToolCallingLoop(brain, registry, FakeVerifier(), ["read_note"])
        answer = loop.run("Use the disabled tool", system_prompt="Nova test")
        self.assertEqual(executed, [])
        self.assertIn("disabled", brain.calls[1]["messages"][-1]["content"])
        self.assertEqual(answer, "I could not use that disabled tool.")

    def test_invalid_arguments_are_returned_to_model_without_execution(self):
        registry = self.make_registry()
        executed = []
        registry.tools["read_note"]["function"] = lambda payload: executed.append(payload) or "read"
        brain = ScriptedToolBrain([
            {
                "content": "",
                "tool_calls": [{
                    "id": "call_bad",
                    "type": "function",
                    "function": {"name": "read_note", "arguments": '{"wrong":"x"}'},
                }],
            },
            {"content": "I need a valid path before reading.", "tool_calls": []},
        ])
        loop = ToolCallingLoop(brain, registry, FakeVerifier(), ["read_note"])
        answer = loop.run("Read a note", system_prompt="Nova test")
        self.assertEqual(executed, [])
        self.assertIn("validation failed", brain.calls[1]["messages"][-1]["content"].lower())
        self.assertIn("valid path", answer)


if __name__ == "__main__":
    unittest.main()
