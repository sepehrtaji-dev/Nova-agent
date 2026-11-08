import unittest

from agent.core import NovaCore


class NativeThinkingBrain:
    def __init__(self):
        self.callback_received = None

    def generate_stream(
        self, prompt, on_token, system_prompt=None, on_thought_delta=None,
    ):
        self.callback_received = on_thought_delta
        if callable(on_thought_delta):
            on_thought_delta("native model thought")
        on_token("final answer")
        return "final answer"


class CoreNativeThinkingToggleTests(unittest.TestCase):
    def make_core(self, enabled):
        core = NovaCore.__new__(NovaCore)
        core.brain = NativeThinkingBrain()
        events = []
        core.status_callback = events.append
        core.thinking_enabled = enabled
        core.test_events = events
        return core

    def test_disabled_does_not_publish_or_request_thinking_callback(self):
        core = self.make_core(False)

        answer = core._generate_with_native_thinking("hello", "Nova")

        self.assertEqual(answer, "final answer")
        self.assertIsNone(core.brain.callback_received)
        self.assertFalse(any(
            event.startswith("MODEL_THOUGHT_")
            for event in core.test_events
        ))

    def test_enabled_publishes_native_thought_separately_from_answer(self):
        core = self.make_core(True)
        events = core.test_events

        answer = core._generate_with_native_thinking("hello", "Nova")

        self.assertEqual(answer, "final answer")
        self.assertTrue(callable(core.brain.callback_received))
        self.assertEqual(events, [
            "MODEL_THOUGHT_START",
            "MODEL_THOUGHT_DELTA:native model thought",
            "MODEL_ANSWER_DELTA:final answer",
            "MODEL_THOUGHT_END",
        ])


if __name__ == "__main__":
    unittest.main()
