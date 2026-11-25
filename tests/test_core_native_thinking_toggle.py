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


class StreamingSummaryBrain:
    """Streams the approach preview as several tokens (live, not buffered)."""

    def __init__(self):
        self.calls = []

    def generate_stream(self, prompt, on_token, system_prompt=None, **kwargs):
        self.calls.append(prompt)
        if "Before answering, write a short user-facing approach summary" in prompt:
            for tok in ("Planning ", "a concise ", "reply."):
                on_token(tok)
            return "Planning a concise reply."
        on_token("final answer")
        return "final answer"


class ThinkingOnlySummaryBrain:
    """A reasoning model that answers the preview prompt in its thinking channel.

    The content stream is empty; the summary arrives via on_thought_delta.
    """

    def __init__(self):
        self.calls = []

    def generate_stream(self, prompt, on_token, system_prompt=None,
                        on_thought_delta=None, **kwargs):
        self.calls.append(prompt)
        if "Before answering, write a short user-facing approach summary" in prompt:
            if callable(on_thought_delta):
                on_thought_delta("Greeting the user warmly.")
            return ""
        on_token("final answer")
        return "final answer"


class StrictSignatureBrain:
    """A brain whose generate_stream rejects on_thought_delta (no **kwargs)."""

    def __init__(self):
        self.calls = []

    def generate_stream(self, prompt, on_token, system_prompt=None):
        self.calls.append(prompt)
        if "Before answering, write a short user-facing approach summary" in prompt:
            on_token("A concise approach preview.")
            return "A concise approach preview."
        on_token("final answer")
        return "final answer"


class ApproachPreviewStreamingTests(unittest.TestCase):
    """Think mode must stream the approach preview live and never freeze."""

    def make_core(self, brain):
        core = NovaCore.__new__(NovaCore)
        core.brain = brain
        events = []
        core.status_callback = events.append
        core.thinking_enabled = True
        return core, events

    def test_summary_is_streamed_token_by_token_not_buffered(self):
        core, events = self.make_core(StreamingSummaryBrain())
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "final answer")
        # One START, one DELTA per token, one END — the panel fills live and
        # the UI is never idle for the whole summary generation (the freeze).
        self.assertEqual(events, [
            "MODEL_THOUGHT_START",
            "MODEL_THOUGHT_DELTA:Planning ",
            "MODEL_THOUGHT_DELTA:a concise ",
            "MODEL_THOUGHT_DELTA:reply.",
            "MODEL_THOUGHT_END",
            "MODEL_ANSWER_DELTA:final answer",
        ])

    def test_empty_content_falls_back_to_labelled_thinking_summary(self):
        core, events = self.make_core(ThinkingOnlySummaryBrain())
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "final answer")
        self.assertEqual(events, [
            "MODEL_THOUGHT_START",
            "MODEL_THOUGHT_DELTA:Greeting the user warmly.",
            "MODEL_THOUGHT_END",
            "MODEL_ANSWER_DELTA:final answer",
        ])

    def test_strict_brain_retries_without_on_thought_delta(self):
        core, events = self.make_core(StrictSignatureBrain())
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "final answer")
        # The first call raised TypeError (on_thought_delta rejected); the
        # retry without it still streams the approach preview token-by-token.
        self.assertEqual(events, [
            "MODEL_THOUGHT_START",
            "MODEL_THOUGHT_DELTA:A concise approach preview.",
            "MODEL_THOUGHT_END",
            "MODEL_ANSWER_DELTA:final answer",
        ])


if __name__ == "__main__":
    unittest.main()
