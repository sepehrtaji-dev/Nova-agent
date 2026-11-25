import unittest

from agent.core import NovaCore


class NativeThinkingBrain:
    def __init__(self):
        self.calls = []
        self.callback_received = None

    def generate_stream(self, prompt, on_token, system_prompt=None, **kwargs):
        self.calls.append(prompt)
        self.callback_received = kwargs.get("on_thought_delta")
        if "Before answering, write a short user-facing approach summary" in prompt:
            on_token("A concise approach preview.")
            return "A concise approach preview."
        on_token("final ")
        on_token("answer")
        return "final answer"


class CoreNativeThinkingToggleTests(unittest.TestCase):
    def make_core(self, enabled):
        core = NovaCore.__new__(NovaCore)
        core.brain = NativeThinkingBrain()
        events = []
        core.status_callback = events.append
        core.thinking_enabled = enabled
        return core, events

    def test_disabled_skips_approach_preview_and_streams_answer_immediately(self):
        core, events = self.make_core(False)
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "final answer")
        self.assertEqual(len(core.brain.calls), 1)
        self.assertEqual(core.brain.calls, ["hello"])
        self.assertEqual(events, [
            "MODEL_ANSWER_DELTA:final ",
            "MODEL_ANSWER_DELTA:answer",
        ])

    def test_enabled_shows_approach_before_answer_without_buffering(self):
        core, events = self.make_core(True)
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "final answer")
        self.assertEqual(len(core.brain.calls), 2)
        self.assertEqual(events, [
            "MODEL_THOUGHT_START",
            "MODEL_THOUGHT_DELTA:A concise approach preview.",
            "MODEL_THOUGHT_END",
            "MODEL_ANSWER_DELTA:final ",
            "MODEL_ANSWER_DELTA:answer",
        ])


if __name__ == "__main__":
    unittest.main()
