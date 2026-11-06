import unittest

from agent.core import NovaCore


class FakeStreamingBrain:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.prompt = None
        self.system_prompt = None

    def generate_stream(self, prompt, on_token, system_prompt=None):
        self.prompt = prompt
        self.system_prompt = system_prompt
        for chunk in self.chunks:
            on_token(chunk)
        return "".join(self.chunks)


class PublicProgressSummaryTests(unittest.TestCase):
    def make_core(self, chunks):
        core = NovaCore.__new__(NovaCore)
        core.brain = FakeStreamingBrain(chunks)
        core.events = []
        core.status_callback = core.events.append
        return core

    def test_streams_model_authored_summary_into_thinking_events(self):
        core = self.make_core(["This is a greeting. ", "I should reply briefly."])
        summary = core._generate_public_progress_summary(
            "hi", "recent conversation: none", "system"
        )

        self.assertEqual(
            summary,
            "This is a greeting. I should reply briefly.",
        )
        self.assertEqual(core.events[0], "MODEL_THOUGHT_START")
        self.assertEqual(
            [event for event in core.events if event.startswith("MODEL_THOUGHT_DELTA:")],
            [
                "MODEL_THOUGHT_DELTA:This is a greeting. ",
                "MODEL_THOUGHT_DELTA:I should reply briefly.",
            ],
        )
        self.assertEqual(core.events[-1], "MODEL_THOUGHT_END")
        self.assertIn("USER MESSAGE:\\nhi", core.brain.prompt)
        self.assertIn("Do not reveal private chain-of-thought", core.brain.prompt)

    def test_summary_is_capped_and_empty_output_is_closed_cleanly(self):
        core = self.make_core(["x" * 2000])
        summary = core._generate_public_progress_summary("hi", "", "system")
        self.assertEqual(len(summary), 1200)
        self.assertEqual(core.events[-1], "MODEL_THOUGHT_END")

        empty = self.make_core([])
        self.assertEqual(
            empty._generate_public_progress_summary("hi", "", "system"),
            "",
        )
        self.assertEqual(empty.events, ["MODEL_THOUGHT_START", "MODEL_THOUGHT_END"])


if __name__ == "__main__":
    unittest.main()
