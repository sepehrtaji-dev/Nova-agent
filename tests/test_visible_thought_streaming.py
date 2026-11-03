import unittest

from agent.core import NovaCore


class StreamingBrain:
    def __init__(self, chunks):
        self.chunks = chunks

    def generate_stream(self, prompt, on_token, system_prompt=None):
        for chunk in self.chunks:
            on_token(chunk)
        return "".join(self.chunks)


class VisibleThoughtStreamingTests(unittest.TestCase):
    def make_core(self, chunks):
        core = NovaCore.__new__(NovaCore)
        events = []
        core.status_callback = events.append
        core.brain = StreamingBrain(chunks)
        return core, events

    def test_streams_model_authored_note_and_returns_only_final_answer(self):
        chunks = [
            "<nova_no",
            "te>The user is asking for a concise greeting. ",
            "I should respond naturally.</nova_note><nova_answer>Hi there!</nova_answer>",
        ]
        core, events = self.make_core(chunks)

        answer = core._generate_with_visible_note(
            "hi",
            "You are Nova.",
        )

        self.assertEqual(answer, "Hi there!")
        self.assertIn("MODEL_THOUGHT_START", events)
        self.assertIn("MODEL_THOUGHT_END", events)
        streamed = "".join(
            event[len("MODEL_THOUGHT_DELTA:"):]
            for event in events
            if event.startswith("MODEL_THOUGHT_DELTA:")
        )
        self.assertEqual(
            streamed,
            "The user is asking for a concise greeting. "
            "I should respond naturally.",
        )

    def test_does_not_invent_a_note_when_model_ignores_tagged_format(self):
        core, events = self.make_core(["A plain answer without tags."])

        answer = core._generate_with_visible_note("hi", "You are Nova.")

        self.assertEqual(answer, "A plain answer without tags.")
        self.assertEqual(events, [])

    def test_malformed_tagged_output_is_not_reported_as_a_clean_answer(self):
        core, events = self.make_core([
            "<nova_note>I'll answer briefly.</nova_note>missing answer tags"
        ])

        answer = core._generate_with_visible_note("hi", "You are Nova.")

        self.assertIn("<nova_note>", answer)
        self.assertIn("MODEL_THOUGHT_START", events)
        self.assertIn("MODEL_THOUGHT_END", events)


if __name__ == "__main__":
    unittest.main()
