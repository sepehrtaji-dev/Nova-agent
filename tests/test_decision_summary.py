import unittest
from unittest.mock import Mock

from agent.core import NovaCore


class ThinkingProcessTests(unittest.TestCase):
    def make_core(self):
        core = NovaCore.__new__(NovaCore)
        events = []
        core.status_callback = events.append
        return core, events

    def test_computer_process_uses_actual_plan_and_tool_names(self):
        core, events = self.make_core()
        plan = {
            "goal": "Update the footer",
            "steps": [
                {
                    "description": "Read the existing HTML file",
                    "tool": "read_file",
                    "input": {"path": "index.html"},
                },
                {
                    "description": "Write the updated HTML",
                    "tool": "write_file",
                    "input": {"path": "index.html"},
                },
            ],
        }

        core._publish_thinking_process(
            "Read index.html and add my GitHub link to the footer",
            "computer",
            plan,
        )

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].startswith("THINKING_PROCESS:"))
        self.assertIn("Goal Identification", events[0])
        self.assertIn("Tool Selection & Execution Plan", events[0])
        self.assertIn("read_file", events[0])
        self.assertIn("write_file", events[0])
        self.assertIn("Pending", events[0])

    def test_conversation_process_does_not_claim_tool_execution(self):
        core, events = self.make_core()

        core._publish_thinking_process("Explain recursion", "conversation")

        self.assertEqual(len(events), 1)
        self.assertIn("answered conversationally", events[0])
        self.assertNotIn("read_file", events[0])

    def test_execution_updates_are_published_as_separate_events(self):
        core, events = self.make_core()

        core._publish_thinking_update("read_file: verification CONFIRMED")

        self.assertEqual(
            events,
            ["THINKING_UPDATE:read_file: verification CONFIRMED"],
        )


if __name__ == "__main__":
    unittest.main()
