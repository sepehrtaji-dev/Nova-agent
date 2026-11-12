"""Regression tests for Nova's human-readable activity status events.

The desktop UI shows a tiny live chip above the composer ("Thinking…",
"Searching the web…", "Reading the file…", "Writing…"). Tool execution
must publish clean ``ACTIVITY:<phrase>`` events instead of raw tool names
flickering past, and every tool in the registry manifest needs a human
phrase so no tool is ever shown as a raw identifier.
"""
import json
import unittest
from pathlib import Path

from agent.activity import (
    ACTIVITY_PREFIX,
    THINKING_ACTIVITY,
    TOOL_ACTIVITIES,
    activity_for,
    format_activity,
)
from agent.tool_loop import ToolCallingLoop


CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _manifest_tool_names():
    with open(CONFIG_DIR / "tools.json", "r", encoding="utf-8") as handle:
        data = json.load(handle)
    tools = data.get("tools") if isinstance(data, dict) else data
    if isinstance(tools, dict):
        return sorted(tools.keys())
    return sorted(
        item.get("name") for item in tools if isinstance(item, dict) and item.get("name")
    )


class ActivityMappingTests(unittest.TestCase):
    def test_every_manifest_tool_has_a_human_phrase(self):
        for name in _manifest_tool_names():
            self.assertIn(
                name,
                TOOL_ACTIVITIES,
                msg=f"tool '{name}' is missing an activity phrase in agent/activity.py",
            )
            phrase = activity_for(name)
            self.assertFalse(phrase.startswith("Using "), msg=name)
            self.assertNotIn("_", phrase, msg=name)

    def test_known_tools_map_to_human_verbs(self):
        self.assertEqual(activity_for("web_search"), "Searching the web")
        self.assertEqual(activity_for("read_file"), "Reading the file")
        self.assertEqual(activity_for("write_file"), "Writing the file")
        self.assertEqual(activity_for("edit_file"), "Editing the file")
        self.assertEqual(activity_for("find_files"), "Finding files")
        self.assertEqual(activity_for("list_files"), "Listing files")
        self.assertEqual(activity_for("terminal"), "Running the command")
        self.assertEqual(activity_for("git"), "Working with git")
        self.assertEqual(activity_for("github"), "Asking GitHub")
        self.assertEqual(activity_for("noviqx_github_get_file"), "Reading from GitHub")
        self.assertEqual(activity_for("noviqx_github_update_file"), "Updating GitHub file")
        self.assertEqual(activity_for("desktop"), "Controlling the desktop")

    def test_unknown_tool_falls_back_to_a_readable_phrase(self):
        self.assertEqual(activity_for("mystery_tool"), "Using mystery_tool")
        self.assertEqual(activity_for(""), "Working")
        self.assertEqual(activity_for(None), "Working")

    def test_prefix_fallback_for_unregistered_tools(self):
        self.assertEqual(activity_for("web_fetch_page"), "Searching the web")
        self.assertEqual(activity_for("github_create_issue"), "Asking GitHub")

    def test_format_activity_wraps_the_wire_prefix(self):
        self.assertEqual(format_activity("web_search"), ACTIVITY_PREFIX + "Searching the web")


class StreamedNativeBrain:
    def __init__(self, responses):
        self.responses = list(responses)

    def generate_tool_turn_stream(
        self, messages, tools, system_prompt=None, on_token=None,
        on_thought_delta=None,
    ):
        response = self.responses.pop(0)
        for chunk in response.get("thought_chunks", []):
            if callable(on_thought_delta):
                on_thought_delta(chunk)
        for chunk in response.get("chunks", []):
            if callable(on_token):
                on_token(chunk)
        return {
            "content": "".join(response.get("chunks", [])),
            "tool_calls": response.get("tool_calls", []),
        }


class ToolRegistry:
    tools = {}

    def exists(self, name):
        return name in self.tools

    def validate_input(self, name, arguments):
        return True, None

    def execute(self, name, encoded):
        return "actual tool result"


class ToolLoopActivityEventTests(unittest.TestCase):
    def _loop(self, responses, events):
        brain = StreamedNativeBrain(responses)
        registry = ToolRegistry()
        registry.tools = {
            "web_search": {
                "description": "Search the public web",
                "capability": "web",
                "input_schema": {"type": "object", "properties": {}},
            }
        }
        loop = ToolCallingLoop(
            brain=brain,
            tools=registry,
            verifier=None,
            allowed_tools={"web_search"},
            status=events.append,
            on_answer_delta=lambda token: events.append("DELTA:" + token),
        )
        return loop

    def test_tool_round_publishes_human_activity_events(self):
        events = []
        loop = self._loop([
            {
                "chunks": [],
                "tool_calls": [{
                    "id": "call_1",
                    "function": {
                        "name": "web_search",
                        "arguments": json.dumps({"query": "nova"}),
                    },
                }],
            },
            {"chunks": ["Here is what I found."], "tool_calls": []},
        ], events)
        result = loop.run("search for nova", system_prompt="Nova")
        self.assertEqual(result, "Here is what I found.")
        self.assertIn(ACTIVITY_PREFIX + "Searching the web", events)
        self.assertIn(THINKING_ACTIVITY, events)
        # The legacy noisy lines must never come back.
        self.assertFalse(any("Using web_search" in item for item in events))
        self.assertFalse(any(item.startswith("THINKING_UPDATE:Selected") for item in events))
        self.assertFalse(any(item.startswith("THINKING_UPDATE:Received") for item in events))

    def test_activity_sequence_orders_thinking_search_thinking(self):
        events = []
        loop = self._loop([
            {
                "chunks": [],
                "tool_calls": [{
                    "id": "call_1",
                    "function": {
                        "name": "web_search",
                        "arguments": json.dumps({"query": "nova"}),
                    },
                }],
            },
            {"chunks": ["Answer."], "tool_calls": []},
        ], events)
        loop.run("q", system_prompt="Nova")
        search_index = events.index(ACTIVITY_PREFIX + "Searching the web")
        self.assertLess(events.index(THINKING_ACTIVITY), search_index)
        thinking_after = events.index(THINKING_ACTIVITY, search_index + 1)
        self.assertLess(thinking_after, len(events))

    def test_activity_publishes_only_for_actually_executed_tools(self):
        events = []
        loop = self._loop([
            {
                "chunks": [],
                "tool_calls": [{
                    "id": "call_1",
                    "function": {"name": "web_search", "arguments": "{not json"},
                }],
            },
            {"chunks": ["Handled gracefully."], "tool_calls": []},
        ], events)
        result = loop.run("q", system_prompt="Nova")
        self.assertEqual(result, "Handled gracefully.")
        # Nothing ran (arguments were malformed): the chip must stay on
        # "Thinking" instead of flashing a tool verb that never executed.
        self.assertNotIn(ACTIVITY_PREFIX + "Searching the web", events)
        self.assertIn(THINKING_ACTIVITY, events)

    def test_disabled_tool_never_publishes_an_activity_event(self):
        events = []
        loop = self._loop([
            {
                "chunks": [],
                "tool_calls": [{
                    "id": "call_1",
                    "function": {
                        "name": "terminal",
                        "arguments": json.dumps({"program": "ls"}),
                    },
                }],
            },
            {"chunks": ["Cannot do that."], "tool_calls": []},
        ], events)
        result = loop.run("q", system_prompt="Nova")
        self.assertEqual(result, "Cannot do that.")
        self.assertNotIn(ACTIVITY_PREFIX + "Running the command", events)


if __name__ == "__main__":
    unittest.main()
