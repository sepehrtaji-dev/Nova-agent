import json
import unittest

from agent.core import NovaCore


class FakeBrain:
    def __init__(self, result):
        self.result = result
        self.prompt = ""
        self.kwargs = {}

    def generate(self, prompt, system_prompt=None, json_mode=False):
        self.prompt = prompt
        self.kwargs = {
            "system_prompt": system_prompt,
            "json_mode": json_mode,
        }
        return self.result


class PublicProgressSummaryTests(unittest.TestCase):
    def make_core(self, result):
        core = NovaCore.__new__(NovaCore)
        core.brain = FakeBrain(result)
        core.events = []
        core.status_callback = core.events.append
        return core

    def test_only_validated_json_summary_is_shown(self):
        core = self.make_core(json.dumps({
            "summary": "The user sent a greeting. I should reply briefly."
        }))
        summary = core._generate_public_progress_summary("hi", "no history", "system")

        self.assertEqual(
            summary,
            "The user sent a greeting. I should reply briefly.",
        )
        self.assertEqual(core.brain.kwargs["json_mode"], True)
        self.assertEqual(core.events[0], "MODEL_THOUGHT_START")
        self.assertEqual(
            [e for e in core.events if e.startswith("MODEL_THOUGHT_DELTA:")],
            ["MODEL_THOUGHT_DELTA:The user sent a greeting. I should reply briefly."],
        )
        self.assertEqual(core.events[-1], "MODEL_THOUGHT_END")
        self.assertIn("USER MESSAGE:\\nhi", core.brain.prompt)
        self.assertIn("NOT a response to the user", core.brain.prompt)

    def test_answer_like_plain_text_is_never_leaked(self):
        core = self.make_core("I'm doing well, thanks for asking! How are you?")
        summary = core._generate_public_progress_summary("hi", "", "system")
        self.assertEqual(summary, "")
        self.assertFalse(any(e.startswith("MODEL_THOUGHT_DELTA:") for e in core.events))
        self.assertEqual(core.events[-1], "MODEL_THOUGHT_END")

    def test_invalid_json_or_oversized_summary_is_rejected(self):
        invalid = self.make_core("not json")
        self.assertEqual(invalid._generate_public_progress_summary("hi", "", "system"), "")

        oversized = self.make_core({"summary": "word " * 60})
        self.assertEqual(oversized._generate_public_progress_summary("hi", "", "system"), "")

        answer_shaped = self.make_core({
            "summary": "I'm doing well, thanks for asking! How are you?"
        })
        self.assertEqual(
            answer_shaped._generate_public_progress_summary("hi", "", "system"),
            "",
        )


if __name__ == "__main__":
    unittest.main()
