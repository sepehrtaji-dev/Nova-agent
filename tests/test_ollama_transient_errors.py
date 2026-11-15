"""Regression tests for transient Ollama 5xx handling.

Ollama answers 503 while a model is still loading or when every runner is
busy; before the retry/backoff fix that single response aborted the whole
tool loop and surfaced as "the tool interaction failed: ResponseError:
(status code: 503)".
"""
import unittest
from unittest.mock import patch

from ollama import ResponseError

from model.ollama import (
    OllamaBrain,
    chat_with_retries,
    is_transient_server_error,
)


class Message:
    def __init__(self, *, thinking="", content="", tool_calls=None):
        self.thinking = thinking
        self.content = content
        self.tool_calls = tool_calls or []


class Chunk:
    def __init__(self, message):
        self.message = message


def flaky_stream_after(chunks):
    """A stream that yields chunks, then dies with a transient 503."""
    def generator():
        yield from chunks
        raise ResponseError("server busy", 503)
    return generator()


class TransientErrorDetection(unittest.TestCase):
    def test_detects_5xx_status_codes(self):
        for code in (500, 502, 503, 504):
            self.assertTrue(is_transient_server_error(ResponseError("boom", code)))

    def test_ignores_client_errors_and_unknown_exceptions(self):
        self.assertFalse(is_transient_server_error(ResponseError("model missing", 404)))
        self.assertFalse(is_transient_server_error(ResponseError("bad request", 400)))
        self.assertFalse(is_transient_server_error(RuntimeError("anything else")))
        self.assertFalse(is_transient_server_error(ResponseError("no code", -1)))

    def test_falls_back_to_parsing_the_message_text(self):
        class Legacy(Exception):
            def __str__(self):
                return "ollama: server busy (status code: 503)"

        self.assertTrue(is_transient_server_error(Legacy()))


class ChatWithRetriesTests(unittest.TestCase):
    def test_retries_transient_5xx_and_recovers(self):
        calls = []
        sleeps = []
        ok = {"message": {"content": "recovered"}, "done_reason": "stop"}
        with (
            patch("model.ollama.ollama.chat", side_effect=[
                ResponseError("server busy", 503),
                ResponseError("still loading", 503),
                ok,
            ]) as chat,
            patch("model.ollama.time") as fake_time,
        ):
            fake_time.sleep.side_effect = sleeps.append
            result = chat_with_retries({"model": "m", "messages": []}, attempts=4)
        self.assertEqual(result, ok)
        self.assertEqual(chat.call_count, 3)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_backoff_grows_and_raises_when_attempts_run_out(self):
        sleeps = []
        with (
            patch("model.ollama.ollama.chat",
                  side_effect=ResponseError("busy", 503)) as chat,
            patch("model.ollama.time") as fake_time,
        ):
            fake_time.sleep.side_effect = sleeps.append
            with self.assertRaises(ResponseError):
                chat_with_retries({"model": "m", "messages": []}, attempts=4)
        self.assertEqual(chat.call_count, 4)
        self.assertEqual(sleeps, [1.0, 2.0, 4.0])

    def test_does_not_retry_client_errors(self):
        with (
            patch("model.ollama.ollama.chat",
                  side_effect=ResponseError("model not found", 404)) as chat,
            patch("model.ollama.time") as fake_time,
        ):
            with self.assertRaises(ResponseError):
                chat_with_retries({"model": "m", "messages": []})
        self.assertEqual(chat.call_count, 1)
        fake_time.sleep.assert_not_called()


class ToolTurnRetryTests(unittest.TestCase):
    def _brain(self):
        return OllamaBrain(model="gemma4:latest")

    def test_generate_tool_turn_retries_transient_503(self):
        brain = self._brain()
        ok = {"message": {"content": "done", "tool_calls": []}}
        with (
            patch("model.ollama.ollama.show", return_value={}),
            patch("model.ollama.ollama.chat", side_effect=[
                ResponseError("server busy", 503),
                ok,
            ]) as chat,
            patch("model.ollama.time") as fake_time,
        ):
            result = brain.generate_tool_turn(
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
            )
        self.assertEqual(result["content"], "done")
        self.assertEqual(chat.call_count, 2)
        fake_time.sleep.assert_called_once_with(1.0)

    def test_generate_tool_turn_fails_fast_on_404(self):
        brain = self._brain()
        with (
            patch("model.ollama.ollama.show", return_value={}),
            patch("model.ollama.ollama.chat",
                  side_effect=ResponseError("model not found", 404)) as chat,
            patch("model.ollama.time") as fake_time,
        ):
            with self.assertRaises(ResponseError):
                brain.generate_tool_turn(
                    messages=[{"role": "user", "content": "hi"}],
                    tools=[],
                )
        self.assertEqual(chat.call_count, 1)
        fake_time.sleep.assert_not_called()

    def test_stream_retries_when_the_server_rejects_before_any_token(self):
        brain = self._brain()
        tokens = []
        with (
            patch("model.ollama.ollama.show", return_value={}),
            patch("model.ollama.ollama.chat", side_effect=[
                ResponseError("server busy", 503),
                iter([Chunk(Message(content="Hello!"))]),
            ]) as chat,
            patch("model.ollama.time") as fake_time,
        ):
            result = brain.generate_tool_turn_stream(
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                on_token=tokens.append,
            )
        self.assertEqual(result["content"], "Hello!")
        self.assertEqual(tokens, ["Hello!"])
        self.assertEqual(chat.call_count, 2)
        fake_time.sleep.assert_called_once_with(1.0)

    def test_stream_never_retries_after_tokens_reached_the_ui(self):
        brain = self._brain()
        tokens = []
        with (
            patch("model.ollama.ollama.show", return_value={}),
            patch("model.ollama.ollama.chat", side_effect=[
                flaky_stream_after([Chunk(Message(content="partial "))]),
            ]) as chat,
            patch("model.ollama.time") as fake_time,
        ):
            with self.assertRaises(ResponseError):
                brain.generate_tool_turn_stream(
                    messages=[{"role": "user", "content": "hi"}],
                    tools=[],
                    on_token=tokens.append,
                )
        # The user already saw "partial "; a replay would duplicate it.
        self.assertEqual(tokens, ["partial "])
        self.assertEqual(chat.call_count, 1)
        fake_time.sleep.assert_not_called()

    def test_plain_generate_retries_transient_503(self):
        brain = self._brain()
        ok = {"message": {"content": "back online"}, "done_reason": "stop"}
        with (
            patch("model.ollama.ollama.chat", side_effect=[
                ResponseError("still loading", 503),
                ok,
            ]) as chat,
            patch("model.ollama.time") as fake_time,
        ):
            result = brain.generate("hello", system_prompt="Nova")
        self.assertEqual(result, "back online")
        self.assertEqual(chat.call_count, 2)
        fake_time.sleep.assert_called_once_with(1.0)


class FriendlyFailureMessageTests(unittest.TestCase):
    def test_transient_5xx_gets_a_targeted_explanation(self):
        from agent.core import _tool_failure_message
        message = _tool_failure_message(ResponseError("", 503))
        self.assertIn("Ollama", message)
        self.assertIn("busy or still loading", message)
        self.assertIn("ollama ps", message)
        self.assertIn("status code: 503", message)

    def test_other_failures_keep_the_original_wording(self):
        from agent.core import _tool_failure_message
        message = _tool_failure_message(RuntimeError("boom"))
        self.assertIn("tool interaction failed", message)
        self.assertIn("RuntimeError: boom", message)
        self.assertNotIn("Ollama", message)


if __name__ == "__main__":
    unittest.main()
