"""Regression tests for transient Ollama 5xx handling.

Ollama answers 503 while a model is still loading or when every runner is
busy; before the retry/backoff fix that single response aborted the whole
tool loop and surfaced as "the tool interaction failed: ResponseError:
(status code: 503)".
"""
import os
import subprocess
import sys
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


class LoopbackProxyBypassTests(unittest.TestCase):
    """httpx routes http://localhost through HTTP_PROXY with no loopback
    exception, so a system proxy can answer Nova's local requests with a
    bare 503 while `ollama run` (Go client) works in the same terminal."""

    def test_loopback_hosts_merged_into_no_proxy(self):
        from model.ollama import _ensure_loopback_bypasses_proxy
        env = {
            "HTTP_PROXY": "http://127.0.0.1:10809",
            "NO_PROXY": "internal.corp.example",
        }
        with patch.dict(os.environ, env, clear=True):
            _ensure_loopback_bypasses_proxy()
            self.assertEqual(
                os.environ["NO_PROXY"],
                "internal.corp.example,localhost,127.0.0.1,::1",
            )
            # The user's own entries are preserved and both casings patched.
            self.assertEqual(os.environ["no_proxy"], "localhost,127.0.0.1,::1")

    def test_bypass_is_idempotent(self):
        from model.ollama import _ensure_loopback_bypasses_proxy
        env = {"NO_PROXY": "localhost,127.0.0.1,::1"}
        with patch.dict(os.environ, env, clear=True):
            _ensure_loopback_bypasses_proxy()
            _ensure_loopback_bypasses_proxy()
            self.assertEqual(os.environ["NO_PROXY"], "localhost,127.0.0.1,::1")

    def test_httpx_sends_loopback_direct_but_proxies_the_rest(self):
        from httpx._utils import get_environment_proxies
        from model.ollama import _ensure_loopback_bypasses_proxy
        env = {"HTTP_PROXY": "http://127.0.0.1:10809"}
        with patch.dict(os.environ, env, clear=True):
            _ensure_loopback_bypasses_proxy()
            mounts = get_environment_proxies()
        self.assertEqual(mounts.get("http://"), "http://127.0.0.1:10809")
        self.assertIsNone(mounts.get("all://localhost"))
        self.assertIsNone(mounts.get("all://127.0.0.1"))
        self.assertIsNone(mounts.get("all://[::1]"))


class LocalServerWithDeadProxyEndToEndTests(unittest.TestCase):
    """Proves the whole chain in a fresh interpreter: with HTTP_PROXY aimed
    at a dead port and no NO_PROXY, importing model.ollama and chatting with
    a loopback server must succeed — the proxy must never be used for the
    local server, in the plain and the streaming path alike."""

    def test_local_chat_reaches_ollama_despite_dead_proxy_env(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        child = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e_proxy_bypass_child.py")
        env = {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "http_proxy": "http://127.0.0.1:1",
            "HOME": os.environ.get("HOME", ""),
            "LANG": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8",
        }
        env.pop("NO_PROXY", None)
        env.pop("no_proxy", None)
        proc = subprocess.run(
            [sys.executable, child, repo],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=repo,
        )
        self.assertIn(
            "E2E-OK", proc.stdout,
            msg=f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}",
        )
        self.assertIn(
            "STREAM-OK", proc.stdout,
            msg=f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}",
        )


class FriendlyFailureMessageTests(unittest.TestCase):
    def test_transient_5xx_gets_a_targeted_explanation(self):
        from agent.core import _tool_failure_message
        message = _tool_failure_message(ResponseError("", 503))
        self.assertIn("Ollama", message)
        self.assertIn("busy or still loading", message)
        self.assertIn("ollama ps", message)
        self.assertIn("status code: 503", message)

    def test_empty_body_503_warns_about_the_system_proxy(self):
        # Ollama always answers with a JSON body; an empty one means a
        # middlebox (VPN / system proxy) produced the 503.
        from agent.core import _tool_failure_message
        message = _tool_failure_message(ResponseError("", 503))
        self.assertIn("no body", message)
        self.assertIn("proxy", message)
        self.assertIn("NO_PROXY", message)

    def test_real_ollama_body_keeps_the_message_focused_on_the_server(self):
        from agent.core import _tool_failure_message
        message = _tool_failure_message(ResponseError("server busy, please try again", 503))
        self.assertIn("ollama ps", message)
        self.assertNotIn("no body", message)
        self.assertNotIn("VPN", message)

    def test_connection_refused_gets_a_targeted_explanation(self):
        # Raw httpx ConnectError — the streaming path does not wrap it —
        # with the classic Windows refused error from a dead proxy port.
        import httpx
        from agent.core import _tool_failure_message
        message = _tool_failure_message(httpx.ConnectError(
            "[WinError 10061] No connection could be made because the target "
            "machine actively refused it"))
        self.assertIn("connection was refused", message)
        self.assertIn("ollama serve", message)
        self.assertIn("setx", message)

    def test_ollama_connection_error_gets_the_same_explanation(self):
        from agent.core import _tool_failure_message
        message = _tool_failure_message(ConnectionError(
            "Failed to connect to Ollama. Please check that Ollama is "
            "downloaded, running and accessible. https://ollama.com/download"))
        self.assertIn("connection was refused", message)
        self.assertIn("Ollama is actually running", message)

    def test_other_failures_keep_the_original_wording(self):
        from agent.core import _tool_failure_message
        message = _tool_failure_message(RuntimeError("boom"))
        self.assertIn("tool interaction failed", message)
        self.assertIn("RuntimeError: boom", message)
        self.assertNotIn("Ollama", message)


if __name__ == "__main__":
    unittest.main()
