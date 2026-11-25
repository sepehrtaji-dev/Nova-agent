import unittest

from agent.core import NovaCore


class NativeThinkingBrain:
    """A brain that streams an answer but emits no native thinking."""

    def __init__(self):
        self.calls = []
        self.kwargs_received = None

    def generate_stream(self, prompt, on_token, system_prompt=None, **kwargs):
        self.calls.append(prompt)
        self.kwargs_received = kwargs
        on_token("final ")
        on_token("answer")
        return "final answer"


class InterleavedReasoningBrain:
    """A reasoning model that emits thinking tokens interleaved with content."""

    def __init__(self):
        self.calls = []

    def generate_stream(self, prompt, on_token, system_prompt=None,
                        on_thought_delta=None, **kwargs):
        self.calls.append({"has_thought_cb": callable(on_thought_delta)})
        if callable(on_thought_delta):
            on_thought_delta("Planning ")
            on_thought_delta("a concise ")
            on_thought_delta("reply.")
        on_token("final answer")
        return "final answer"


class ThinkingOnlyBrain:
    """A reasoning model that answers entirely in its thinking channel.

    The content stream is empty; the reasoning arrives via on_thought_delta.
    This is the gemma4 case the user reported: the panel must still fill.
    """

    def __init__(self):
        self.calls = []

    def generate_stream(self, prompt, on_token, system_prompt=None,
                        on_thought_delta=None, **kwargs):
        self.calls.append({"has_thought_cb": callable(on_thought_delta)})
        if callable(on_thought_delta):
            on_thought_delta("Greeting the user warmly.")
        return ""


class StrictSignatureBrain:
    """A brain whose generate_stream rejects on_thought_delta (no **kwargs)."""

    def __init__(self):
        self.calls = []

    def generate_stream(self, prompt, on_token, system_prompt=None):
        self.calls.append(prompt)
        on_token("final answer")
        return "final answer"


class NativeReasoningBrain:
    """A reasoning model that advertises a thinking channel.

    think_value_for_effort resolves a think= value, so the core passes think=
    and routes on_thought_delta; the model's own thinking is shown live while
    the answer streams.
    """

    def __init__(self):
        self.calls = []

    def supports_thinking(self):
        return True

    def think_value_for_effort(self, effort="medium"):
        return True

    def generate_stream(self, prompt, on_token, system_prompt=None,
                        on_thought_delta=None, think=None, **kwargs):
        self.calls.append({
            "think": think,
            "has_thought_cb": callable(on_thought_delta),
        })
        if callable(on_thought_delta):
            on_thought_delta("Considering the greeting.")
        on_token("Hello! ")
        on_token("I'm well.")
        return "Hello! I'm well."


class UnadvertisedReasoningBrain:
    """A brain that exposes think_value_for_effort but returns None.

    This models a model that CAN reason but does not advertise thinking via
    /api/show (so think_value_for_effort resolves to None). With Think on, the
    core must STILL force think=True so the model actually produces thinking —
    otherwise the panel stays empty (the gemma4 bug).
    """

    def __init__(self):
        self.calls = []

    def think_value_for_effort(self, effort="medium"):
        return None

    def generate_stream(self, prompt, on_token, system_prompt=None,
                        on_thought_delta=None, think=None, **kwargs):
        self.calls.append({"think": think, "has_thought_cb": callable(on_thought_delta)})
        if callable(on_thought_delta):
            on_thought_delta("Reasoning without advertisement.")
        on_token("answer")
        return "answer"


class CoreNativeThinkingToggleTests(unittest.TestCase):
    def make_core(self, brain, enabled):
        core = NovaCore.__new__(NovaCore)
        core.brain = brain
        events = []
        core.status_callback = events.append
        core.thinking_enabled = enabled
        return core, events

    def test_disabled_streams_answer_only(self):
        core, events = self.make_core(NativeThinkingBrain(), False)
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "final answer")
        self.assertEqual(core.brain.calls, ["hello"])
        self.assertEqual(events, [
            "MODEL_ANSWER_DELTA:final ",
            "MODEL_ANSWER_DELTA:answer",
        ])

    def test_enabled_routes_on_thought_delta_but_skips_panel_without_thinking(self):
        # Think is on and on_thought_delta is routed to the brain, but this brain
        # never calls it. No thinking panel appears; the answer streams at once.
        # There is no separate pre-answer generation, so no second API call and
        # no transition freeze.
        core, events = self.make_core(NativeThinkingBrain(), True)
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "final answer")
        self.assertEqual(core.brain.calls, ["hello"])
        self.assertIn("on_thought_delta", core.brain.kwargs_received)
        self.assertEqual(events, [
            "MODEL_ANSWER_DELTA:final ",
            "MODEL_ANSWER_DELTA:answer",
        ])


class NativeThinkingStreamTests(unittest.TestCase):
    """Think mode routes the model's native thinking to the panel live during the answer."""

    def make_core(self, brain):
        core = NovaCore.__new__(NovaCore)
        core.brain = brain
        events = []
        core.status_callback = events.append
        core.thinking_enabled = True
        return core, events

    def test_thinking_streams_live_token_by_token(self):
        core, events = self.make_core(InterleavedReasoningBrain())
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "final answer")
        # One START, one DELTA per thinking token, then the answer, then END.
        # The panel fills live and the UI is never idle — there is no separate
        # blocking generation before the answer (the freeze the user saw).
        self.assertEqual(events, [
            "MODEL_THOUGHT_START",
            "MODEL_THOUGHT_DELTA:Planning ",
            "MODEL_THOUGHT_DELTA:a concise ",
            "MODEL_THOUGHT_DELTA:reply.",
            "MODEL_ANSWER_DELTA:final answer",
            "MODEL_THOUGHT_END",
        ])

    def test_thinking_only_model_still_fills_the_panel(self):
        # A reasoning model that answers entirely in its thinking channel (empty
        # content stream) must still fill the panel — this is the "empty panel"
        # bug the user reported for gemma4.
        core, events = self.make_core(ThinkingOnlyBrain())
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "")
        self.assertEqual(events, [
            "MODEL_THOUGHT_START",
            "MODEL_THOUGHT_DELTA:Greeting the user warmly.",
            "MODEL_THOUGHT_END",
        ])

    def test_strict_brain_retries_without_on_thought_delta(self):
        core, events = self.make_core(StrictSignatureBrain())
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "final answer")
        # The first call raised TypeError (on_thought_delta rejected); the retry
        # without it still streams the answer.
        self.assertEqual(events, ["MODEL_ANSWER_DELTA:final answer"])

    def test_native_thinking_streams_live_during_answer_and_passes_think(self):
        core, events = self.make_core(NativeReasoningBrain())
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "Hello! I'm well.")
        # Only ONE generation (the answer) — no separate approach summary, so
        # there is no second blocking generation to freeze the UI.
        self.assertEqual(len(core.brain.calls), 1)
        self.assertTrue(core.brain.calls[0]["has_thought_cb"])
        self.assertIs(core.brain.calls[0]["think"], True)
        # The model's native thinking is routed to the panel LIVE, interleaved
        # with the streamed answer — not buffered, not dropped.
        self.assertEqual(events, [
            "MODEL_THOUGHT_START",
            "MODEL_THOUGHT_DELTA:Considering the greeting.",
            "MODEL_ANSWER_DELTA:Hello! ",
            "MODEL_ANSWER_DELTA:I'm well.",
            "MODEL_THOUGHT_END",
        ])

    def test_unadvertised_reasoning_model_still_forces_think_true(self):
        # think_value_for_effort returns None (model doesn't advertise thinking),
        # but Think is ON. The core must force think=True so the model actually
        # reasons and the panel fills — this is the gemma4 empty-panel fix.
        core, events = self.make_core(UnadvertisedReasoningBrain())
        answer = core._generate_with_native_thinking("hello", "Nova")
        self.assertEqual(answer, "answer")
        self.assertEqual(len(core.brain.calls), 1)
        self.assertIs(core.brain.calls[0]["think"], True)
        self.assertTrue(core.brain.calls[0]["has_thought_cb"])
        self.assertEqual(events, [
            "MODEL_THOUGHT_START",
            "MODEL_THOUGHT_DELTA:Reasoning without advertisement.",
            "MODEL_ANSWER_DELTA:answer",
            "MODEL_THOUGHT_END",
        ])


if __name__ == "__main__":
    unittest.main()
