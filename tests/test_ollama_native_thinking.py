import unittest
from unittest.mock import patch

from model.ollama import OllamaBrain


class Message:
    def __init__(self, *, thinking="", thinking_summary="", content="", tool_calls=None):
        self.thinking = thinking
        self.thinking_summary = thinking_summary
        self.content = content
        self.tool_calls = tool_calls or []


class Chunk:
    def __init__(self, message):
        self.message = message


class OllamaNativeThinkingTests(unittest.TestCase):
    def test_detects_thinking_from_ollama_show_metadata(self):
        brain = OllamaBrain(model="gemma4:latest")
        with patch("model.ollama.ollama.show", return_value={
            "thinking": {"values": [False, True], "default": True},
            "capabilities": ["completion", "thinking"],
        }) as show:
            self.assertTrue(brain.supports_thinking())
            self.assertTrue(brain.supports_thinking())
            show.assert_called_once_with("gemma4:latest")

    def test_does_not_enable_thinking_for_models_without_support(self):
        brain = OllamaBrain(model="plain-model")
        with patch("model.ollama.ollama.show", return_value={
            "thinking": {"values": [False], "default": False},
            "capabilities": ["completion"],
        }):
            self.assertFalse(brain.supports_thinking())

    def test_standard_stream_forwards_native_thought_callback(self):
        brain = OllamaBrain(model="gemma4:latest")
        chunks = [
            Chunk(Message(thinking="PRIVATE INTERNAL TRACE", thinking_summary="The model is checking the request.")),
            Chunk(Message(content="Final answer.")),
        ]
        thoughts = []
        answers = []
        with (
            patch("model.ollama.ollama.show", return_value={
                "thinking": {"values": [False, True], "default": True},
                "capabilities": ["completion", "thinking"],
            }),
            patch("model.ollama.ollama.chat", return_value=iter(chunks)),
        ):
            result = brain.generate_stream(
                "hello", answers.append, system_prompt="Nova",
                on_thought_delta=thoughts.append,
            )
        self.assertEqual(result, "Final answer.")
        self.assertEqual(answers, ["Final answer."])
        self.assertEqual(thoughts, ["The model is checking the request."])

    def test_standard_stream_streams_raw_thinking_live_when_no_labelled_summary(self):
        """A reasoning model with only raw thinking fills the panel live.

        Without this, the panel stayed empty for the whole thinking phase and
        only filled (via a separate post-hoc summary) at the end — the freeze
        the user reported. When a chunk carries raw thinking but no labelled
        thinking_summary, stream that thinking live.
        """
        brain = OllamaBrain(model="gemma4:latest")
        chunks = [
            Chunk(Message(thinking="Working through the greeting.")),
            Chunk(Message(thinking="Deciding to be warm.")),
            Chunk(Message(content="Hi there!")),
        ]
        thoughts = []
        answers = []
        with (
            patch("model.ollama.ollama.show", return_value={
                "thinking": {"values": [False, True], "default": True},
                "capabilities": ["completion", "thinking"],
            }),
            patch("model.ollama.ollama.chat", return_value=iter(chunks)) as chat,
        ):
            result = brain.generate_stream(
                "hi", answers.append, system_prompt="Nova",
                on_thought_delta=thoughts.append, think=True,
            )
        self.assertIs(chat.call_args.kwargs["think"], True)
        # Raw thinking streamed live, in order — not buffered for a post-hoc
        # summary that would only arrive after a second blocking generation.
        self.assertEqual(thoughts, ["Working through the greeting.", "Deciding to be warm."])
        self.assertEqual(answers, ["Hi there!"])
        self.assertEqual(result, "Hi there!")


    def test_streams_native_thinking_separately_from_answer(self):
        brain = OllamaBrain(model="gemma4:latest")
        chunks = [
            Chunk(Message(thinking="PRIVATE TRACE A", thinking_summary="The model is reviewing the request. ")),
            Chunk(Message(thinking="PRIVATE TRACE B", thinking_summary="A concise greeting is appropriate. ")),
            Chunk(Message(content="Hey! How can I help?")),
        ]
        thought_deltas = []
        answer_deltas = []
        with (
            patch("model.ollama.ollama.show", return_value={
                "thinking": {"values": [False, True], "default": True},
                "capabilities": ["completion", "thinking"],
            }),
            patch("model.ollama.ollama.chat", return_value=iter(chunks)) as chat,
        ):
            result = brain.generate_tool_turn_stream(
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                system_prompt="Nova",
                on_token=answer_deltas.append,
                on_thought_delta=thought_deltas.append,
            )

        self.assertTrue(chat.call_args.kwargs["think"])
        self.assertEqual(
            thought_deltas,
            ["The model is reviewing the request. ", "A concise greeting is appropriate. "],
        )
        self.assertEqual(answer_deltas, ["Hey! How can I help?"])
        self.assertEqual(
            result["thinking"],
            "PRIVATE TRACE APRIVATE TRACE B",
        )
        self.assertEqual(
            result["reasoning_summary"],
            "The model is reviewing the request. A concise greeting is appropriate. ",
        )
        self.assertNotIn("PRIVATE TRACE", "".join(thought_deltas))
        self.assertEqual(result["content"], "Hey! How can I help?")


    def test_generate_stream_retries_without_think_when_server_rejects_it(self):
        """A non-reasoning model rejects think=; generate_stream retries without it.

        The core forces think=True when the user turns Think on (so models that
        can reason but don't advertise it still produce thinking). A genuinely
        non-reasoning model answers think= with an error mentioning think +
        "not supported"; generate_stream must retry once WITHOUT think= so the
        answer still streams instead of erroring out.
        """
        brain = OllamaBrain(model="plain-model")
        chunks = [Chunk(Message(content="Final answer."))]
        answers = []
        calls = []

        def fake_chat(**kwargs):
            calls.append(dict(kwargs))
            if kwargs.get("think"):
                raise RuntimeError("think is not supported by this model")
            return iter(chunks)

        with (
            patch("model.ollama.ollama.show", return_value={
                "thinking": {"values": [False], "default": False},
                "capabilities": ["completion"],
            }),
            patch("model.ollama.ollama.chat", side_effect=fake_chat),
        ):
            result = brain.generate_stream(
                "hi", answers.append, system_prompt="Nova", think=True,
            )
        # First call carried think=True and was rejected; retry dropped think=.
        self.assertEqual(len(calls), 2)
        self.assertIs(calls[0]["think"], True)
        self.assertNotIn("think", calls[1])
        self.assertEqual(answers, ["Final answer."])
        self.assertEqual(result, "Final answer.")


    def test_tool_turn_streams_thinking_live_and_never_runs_a_blocking_summarizer(self):
        """The tool-call path must not freeze for a second inference per round.

        generate_tool_turn_stream used to hold the thinking back and, after the
        stream ended, call generate() again just to summarize it. That extra
        blocking call was the multi-second freeze and left the panel empty
        until the round was already over.
        """
        brain = OllamaBrain(model="gemma4:latest")
        chunks = [
            Chunk(Message(thinking="Checking which file to read.")),
            Chunk(Message(thinking="I should list the folder first.")),
            Chunk(Message(tool_calls=[{"function": {"name": "list_files", "arguments": {}}}])),
        ]
        thoughts = []
        with (
            patch("model.ollama.ollama.show", return_value={
                "thinking": {"values": [False, True], "default": True},
                "capabilities": ["completion", "thinking"],
            }),
            patch("model.ollama.ollama.chat", return_value=iter(chunks)) as chat,
            patch.object(OllamaBrain, "generate", side_effect=AssertionError("blocking summarizer ran")),
        ):
            result = brain.generate_tool_turn_stream(
                [{"role": "user", "content": "look around"}], [],
                think=True, on_thought_delta=thoughts.append,
            )
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(thoughts, ["Checking which file to read.", "I should list the folder first."])
        self.assertEqual(len(result["tool_calls"]), 1)
        self.assertIn("list the folder", result["reasoning_summary"])

    def test_tool_turn_retries_without_think_when_server_rejects_it(self):
        brain = OllamaBrain(model="plain-model")
        answers = []
        calls = []

        def fake_chat(**kwargs):
            calls.append(dict(kwargs))
            if kwargs.get("think"):
                raise RuntimeError("think is not supported by this model")
            return iter([Chunk(Message(content="Plain answer."))])

        with (
            patch("model.ollama.ollama.show", return_value={"capabilities": ["completion"]}),
            patch("model.ollama.ollama.chat", side_effect=fake_chat),
        ):
            result = brain.generate_tool_turn_stream(
                [{"role": "user", "content": "hi"}], [], think=True, on_token=answers.append,
            )
        self.assertEqual(len(calls), 2)
        self.assertNotIn("think", calls[1])
        self.assertEqual(answers, ["Plain answer."])
        self.assertEqual(result["content"], "Plain answer.")


    def test_tool_turns_request_an_explicit_context_window(self):
        """Without num_ctx Ollama truncates the oldest prompt text (the user's request)."""
        import os
        brain = OllamaBrain(model="plain-model")
        seen = []

        def fake_chat(**kwargs):
            seen.append(kwargs["options"])
            return iter([Chunk(Message(content="ok"))])

        with (
            patch("model.ollama.ollama.show", return_value={"capabilities": ["completion"]}),
            patch("model.ollama.ollama.chat", side_effect=fake_chat),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("NOVA_TOOL_NUM_CTX", None)
            os.environ.pop("NOVA_NUM_CTX", None)
            brain.generate_tool_turn_stream([{"role": "user", "content": "hi"}], [])
            self.assertEqual(seen[-1]["num_ctx"], 16384)
            self.assertEqual(brain.context_window_tokens, 16384)
            os.environ["NOVA_TOOL_NUM_CTX"] = "32768"
            brain.generate_tool_turn_stream([{"role": "user", "content": "hi"}], [])
            self.assertEqual(seen[-1]["num_ctx"], 32768)
            # A caller-supplied value always wins.
            brain.generate_tool_turn_stream([{"role": "user", "content": "hi"}], [], options={"num_ctx": 9000})
            self.assertEqual(seen[-1]["num_ctx"], 9000)


if __name__ == "__main__":
    unittest.main()
