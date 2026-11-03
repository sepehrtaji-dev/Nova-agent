import unittest
from unittest.mock import Mock

from agent.core import NovaCore


class DecisionSummaryTests(unittest.TestCase):
    def make_core(self, generated_summary):
        core = NovaCore.__new__(NovaCore)
        core.brain = Mock()
        core.brain.generate.return_value = generated_summary
        core._identity_system_prompt = Mock(return_value="You are Nova.")
        events = []
        core.status_callback = events.append
        return core, events

    def test_publishes_user_safe_model_decision_summary(self):
        core, events = self.make_core(
            "- The request is to inspect the existing project file.\n"
            "- I should use the available file-reading capability before answering."
        )

        core._publish_decision_summary("Please read index.html", "computer")

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].startswith("MODEL_NOTE:"))
        self.assertIn("inspect the existing project file", events[0])
        self.assertNotIn("THOUGHT_SUMMARY:", events[0])
        prompt = core.brain.generate.call_args.args[0]
        self.assertIn("Do not reveal private chain-of-thought", prompt)
        self.assertIn("Do not claim that any tool has already run", prompt)

    def test_empty_model_summary_uses_transparent_fallback(self):
        core, events = self.make_core("  \n ")

        core._publish_decision_summary("Please read index.html", "computer")

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].startswith("MODEL_NOTE:"))
        self.assertIn("requires an action in your workspace", events[0])
        self.assertIn("verify the outcome", events[0])

    def test_summary_generation_failure_uses_fallback(self):
        core, events = self.make_core("")
        core.brain.generate.side_effect = RuntimeError("model unavailable")

        core._publish_decision_summary("Hello", "conversation")

        self.assertEqual(len(events), 1)
        self.assertIn("conversational request", events[0])
        self.assertIn("answer directly", events[0])


if __name__ == "__main__":
    unittest.main()
