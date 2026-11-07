import unittest
from unittest.mock import patch

from model.ollama import OllamaBrain


class Message:
    def __init__(self, *, thinking="", content="", tool_calls=None):
        self.thinking = thinking
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

    def test_streams_native_thinking_separately_from_answer(self):
        brain = OllamaBrain(model="gemma4:latest")
        chunks = [
            Chunk(Message(thinking="Let me inspect the request. ")),
            Chunk(Message(thinking="A concise greeting is appropriate. ")),
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
            ["Let me inspect the request. ", "A concise greeting is appropriate. "],
        )
        self.assertEqual(answer_deltas, ["Hey! How can I help?"])
        self.assertEqual(
            result["thinking"],
            "Let me inspect the request. A concise greeting is appropriate. ",
        )
        self.assertEqual(result["content"], "Hey! How can I help?")


if __name__ == "__main__":
    unittest.main()
