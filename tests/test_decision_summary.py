import unittest

from agent.core import NovaCore


class ThinkingProcessTests(unittest.TestCase):
    def make_core(self):
        core = NovaCore.__new__(NovaCore)
        events = []
        core.status_callback = events.append
        return core, events

    def test_does_not_publish_planner_summary_as_native_thinking(self):
        core, events = self.make_core()
        plan = {
            "visible_summary": (
                "The request is to update the existing HTML footer. "
                "I will inspect the file before choosing the smallest safe edit."
            ),
            "steps": [],
        }

        core._publish_thinking_process(
            "Add a GitHub link to index.html",
            "computer",
            plan,
        )

        # Planner summaries describe orchestration, not native model reasoning.
        self.assertEqual(events, [])

    def test_does_not_invent_summary_when_planner_did_not_return_one(self):
        core, events = self.make_core()

        core._publish_thinking_process(
            "Add a GitHub link to index.html",
            "computer",
            {"steps": []},
        )

        self.assertEqual(events, [])

    def test_execution_updates_remain_factual_and_separate(self):
        core, events = self.make_core()

        core._publish_thinking_update("read_file: verification CONFIRMED")

        self.assertEqual(
            events,
            ["THINKING_UPDATE:read_file: verification CONFIRMED"],
        )


if __name__ == "__main__":
    unittest.main()
