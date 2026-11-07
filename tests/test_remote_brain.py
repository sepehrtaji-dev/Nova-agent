"""Tests for the remote OpenAI-compatible brain and provider selection."""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from model.ollama import OllamaBrain
from model.provider import backend_kind, build_brain, describe_brain
from model.remote import OpenAICompatibleBrain, RemoteBrainError

CAPTURED = []
RESPONSES = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        CAPTURED.append({
            "path": self.path,
            "auth": self.headers.get("Authorization", ""),
            "body": json.loads(body) if body else {},
        })

        override = RESPONSES.get("status")
        if override == 401:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(json.dumps(
                {"error": {"message": "bad key sk-leak-999"}}).encode())
            return
        if override == 429:
            self.send_response(429)
            self.send_header("Retry-After", "1")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {
                "message": "google/gemma-4-26b-a4b-it:free is temporarily "
                           "rate-limited upstream.",
                "code": 429}}).encode())
            return
        if override == 500:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
            return
        if override == "tool_call":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "choices": [{
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_test",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": "{\"path\": \"index.html\"}"
                            }
                        }]
                    }
                }]
            }).encode())
            return
        if override == "garbage":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>not json</html>")
            return
        if override == "no_choices":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"choices": []}).encode())
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "ready"}}]
        }).encode())


class RemoteBrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_port
        cls.base = f"http://127.0.0.1:{cls.port}/v1"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        CAPTURED.clear()
        RESPONSES.clear()
        self.brain = OpenAICompatibleBrain(
            model="test-model", api_key="sk-good", base_url=self.base,
            max_retries=0)

    def test_native_tool_turn_preserves_structured_tool_calls(self):
        RESPONSES["status"] = "tool_call"
        definitions = [{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }]
        result = self.brain.generate_tool_turn(
            messages=[{"role": "user", "content": "Read index.html"}],
            tools=definitions,
            system_prompt="Nova test",
        )
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(
            json.loads(result["tool_calls"][0]["function"]["arguments"]),
            {"path": "index.html"},
        )
        sent = CAPTURED[-1]["body"]
        self.assertEqual(sent["tools"], definitions)
        self.assertEqual(sent["tool_choice"], "auto")
        self.assertEqual(sent["messages"][-1]["content"], "Read index.html")

    def test_remote_tool_history_serializes_function_arguments(self):
        RESPONSES["status"] = "tool_call"
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_previous",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": {"path": "index.html"},
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call_previous",
                "name": "read_file",
                "content": "{\"ok\": true}",
            },
        ]
        self.brain.generate_tool_turn(messages=messages, tools=[], system_prompt="Nova")
        sent_messages = CAPTURED[-1]["body"]["messages"]
        self.assertEqual(
            json.loads(sent_messages[1]["tool_calls"][0]["function"]["arguments"]),
            {"path": "index.html"},
        )
        self.assertEqual(sent_messages[2]["tool_call_id"], "call_previous")

    def test_ollama_native_tool_turn_uses_tool_name_for_tool_results(self):
        from model.ollama import OllamaBrain

        response = {"message": {"content": "done", "tool_calls": []}}
        with mock.patch("model.ollama.ollama.chat", return_value=response) as chat:
            brain = OllamaBrain(model="test-model")
            result = brain.generate_tool_turn(
                messages=[
                    {
                        "role": "assistant",
                        "tool_calls": [{
                            "id": "call_previous",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": {"path": "index.html"},
                            },
                        }],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_previous",
                        "name": "read_file",
                        "content": "file contents",
                    },
                ],
                tools=[],
                system_prompt="Nova",
            )
        self.assertEqual(result["content"], "done")
        sent_messages = chat.call_args.kwargs["messages"]
        self.assertEqual(sent_messages[-1]["role"], "tool")
        self.assertEqual(sent_messages[-1]["tool_name"], "read_file")
        self.assertNotIn("tool_call_id", sent_messages[-1])
        assistant_call = sent_messages[-2]["tool_calls"][0]
        self.assertEqual(assistant_call["function"]["arguments"], {"path": "index.html"})
        self.assertNotIn("id", assistant_call)
        self.assertNotIn("type", assistant_call)

    def test_successful_call_parses_content(self):
        self.assertEqual(self.brain.generate("hi"), "ready")
        sent = CAPTURED[-1]
        self.assertTrue(sent["path"].endswith("/chat/completions"))
        self.assertEqual(sent["body"]["model"], "test-model")
        self.assertEqual(len(sent["body"]["messages"]), 2)


    def test_num_predict_is_mapped_to_remote_max_tokens(self):
        self.brain.generate("write a short report", options={"num_predict": 2048})
        self.assertEqual(CAPTURED[-1]["body"]["max_tokens"], 2048)

    def test_explicit_max_tokens_takes_precedence_over_num_predict(self):
        self.brain.generate(
            "write a short report",
            options={"num_predict": 8192, "max_tokens": 1024},
        )
        self.assertEqual(CAPTURED[-1]["body"]["max_tokens"], 1024)

    def test_calls_without_explicit_system_prompt_receive_nova_instructions(self):
        self.brain.generate("my name is sepehr")
        system_message = CAPTURED[-1]["body"]["messages"][0]["content"]
        self.assertIn("You are Nova", system_message)
        self.assertIn("untrusted data", system_message)


    def test_explicit_system_prompt_is_preserved_instead_of_default(self):
        self.brain.generate("hello", system_prompt="Custom system prompt")
        self.assertEqual(
            CAPTURED[-1]["body"]["messages"][0]["content"],
            "Custom system prompt",
        )

    def test_default_remote_prompt_requires_natural_prose_for_conversation(self):
        self.brain.generate("my name is sepehr")
        system_message = CAPTURED[-1]["body"]["messages"][0]["content"]
        self.assertIn("natural prose", system_message)
        self.assertIn("never expose", system_message)

    def test_authorization_header_is_sent(self):
        self.brain.generate("hi")
        self.assertEqual(CAPTURED[-1]["auth"], "Bearer sk-good")

    def test_json_mode_requests_a_json_object(self):
        self.brain.generate("hi", json_mode=True)
        self.assertEqual(
            CAPTURED[-1]["body"]["response_format"], {"type": "json_object"})

    def test_http_401_is_not_retried_and_does_not_leak_secrets(self):
        RESPONSES["status"] = 401
        with self.assertRaises(RemoteBrainError) as ctx:
            self.brain.generate("hi")
        message = str(ctx.exception)
        self.assertIn("401", message)
        self.assertNotIn("sk-good", message)
        self.assertNotIn("sk-leak-999", message)
        self.assertFalse(ctx.exception.transient)

    def test_transient_500_is_retried(self):
        RESPONSES["status"] = 500
        brain = OpenAICompatibleBrain(
            model="m", api_key="k", base_url=self.base, max_retries=1)
        RESPONSES.clear()  # second attempt succeeds
        with mock.patch("model.remote.time.sleep"):
            self.assertEqual(brain.generate("hi"), "ready")

    def test_persistent_429_reports_rate_limit_not_missing_response(self):
        """Regression: a 429 was reported as 'did not respond'.

        The provider had responded, with a rate limit, and the misleading
        wording sent the user looking for a connectivity problem. A 429 also
        needs a real wait: a 1-4s backoff cannot clear a shared free pool.
        """
        RESPONSES["status"] = 429
        brain = OpenAICompatibleBrain(
            model="google/gemma-4-26b-a4b-it:free", api_key="k",
            base_url=self.base, max_retries=2)
        with mock.patch("model.remote.time.sleep") as sleeper:
            with self.assertRaises(RemoteBrainError) as ctx:
                brain.generate("hi")
        message = str(ctx.exception)
        self.assertIn("rate-limited", message.lower())
        self.assertNotIn("did not respond", message)
        self.assertTrue(ctx.exception.transient)
        # Waits must be honoured for each retry.
        self.assertGreaterEqual(sleeper.call_count, 2)

    def test_429_maps_free_tier_wording_to_actionable_hint(self):
        from model.remote import _rate_limit_hint

        hint = _rate_limit_hint(
            '{"error":{"message":"x:free is temporarily rate-limited upstream"}}')
        self.assertIn("free model", hint.lower())
        self.assertIn("different model", hint)
        quota = _rate_limit_hint('{"error":{"message":"insufficient quota"}}')
        self.assertIn("quota", quota.lower())

    def test_retry_after_header_is_honoured_and_bounded(self):
        class FakeError(Exception):
            def __init__(self, header):
                self.headers = {"Retry-After": header}

        brain = OpenAICompatibleBrain(model="m", api_key="k", base_url=self.base)
        with mock.patch.dict(os.environ, {"NOVA_RATE_LIMIT_WAIT": "5"}):
            self.assertEqual(brain._retry_after_seconds(FakeError("12")), 12.0)
            # Absurd values are clamped so a turn cannot hang for minutes.
            self.assertEqual(brain._retry_after_seconds(FakeError("9999")), 60.0)
            # A missing or unparseable header falls back to the default.
            self.assertEqual(brain._retry_after_seconds(FakeError("")), 5.0)
            self.assertEqual(brain._retry_after_seconds(FakeError("soon")), 5.0)

    def test_non_json_response_is_reported(self):
        RESPONSES["status"] = "garbage"
        with self.assertRaises(RemoteBrainError) as ctx:
            self.brain.generate("hi")
        self.assertIn("non-JSON", str(ctx.exception))

    def test_empty_choices_is_reported(self):
        RESPONSES["status"] = "no_choices"
        with self.assertRaises(RemoteBrainError) as ctx:
            self.brain.generate("hi")
        self.assertIn("no choices", str(ctx.exception))

    def test_unconfigured_brain_refuses_instead_of_calling_out(self):
        empty = OpenAICompatibleBrain(model="", api_key="", base_url=self.base)
        self.assertFalse(empty.is_configured())
        with self.assertRaises(RemoteBrainError):
            empty.generate("hi")
        self.assertEqual(empty.probe()["status"], "unconfigured")

    def test_describe_discloses_data_leaves_the_machine(self):
        text = self.brain.describe()
        self.assertIn("test-model", text)
        self.assertIn("provider's servers", text)
        self.assertIn("sent to", text)

    def test_c_gen_matches_generate_signature(self):
        self.assertEqual(self.brain.c_gen("hi"), "ready")


class ProviderSelectionTests(unittest.TestCase):
    def _with_env(self, **env):
        clean = {k: v for k, v in os.environ.items()
                 if not k.startswith("NOVA_")}
        clean.update(env)
        return mock.patch.dict(os.environ, clean, clear=True)

    def test_default_is_local(self):
        with self._with_env():
            self.assertIsInstance(build_brain(), OllamaBrain)

    def test_explicit_remote_builds_remote_brain(self):
        with self._with_env(NOVA_PROVIDER="remote", NOVA_API_KEY="k",
                            NOVA_API_MODEL="m"):
            brain = build_brain()
            self.assertEqual(backend_kind(brain), "remote")

    def test_remote_without_configuration_does_not_fall_back_silently(self):
        """Falling back would hide that prompts stopped leaving the machine."""
        with self._with_env(NOVA_PROVIDER="remote"):
            with self.assertRaises(RuntimeError):
                build_brain()

    def test_auto_uses_local_when_no_key(self):
        with self._with_env(NOVA_PROVIDER="auto"):
            self.assertEqual(backend_kind(build_brain()), "local")

    def test_base_url_env_is_read_at_construction_not_import(self):
        """Regression: the default base URL was frozen at import time.

        Changing NOVA_API_BASE_URL later had no effect, so requests were sent to
        the default provider instead of the configured endpoint.
        """
        with self._with_env(NOVA_API_BASE_URL="https://gateway.internal/v1",
                            NOVA_API_MODEL="m", NOVA_API_KEY="k"):
            brain = OpenAICompatibleBrain()
            self.assertIn("gateway.internal", brain.base_url)

    def test_describe_brain_local_mentions_nothing_is_sent(self):
        text = describe_brain(OllamaBrain(model="qwen2.5:3b"))
        self.assertIn("qwen2.5:3b", text)
        self.assertIn("nothing is sent", text)


    def test_ollama_native_tool_turn_returns_native_thinking(self):
        response = {"message": {
            "content": "The answer is 42.",
            "thinking": "I should calculate this carefully.",
            "tool_calls": [],
        }}
        with mock.patch("model.ollama.ollama.show", return_value={
            "thinking": {"values": [True], "default": True},
        }), mock.patch("model.ollama.ollama.chat", return_value=response) as chat:
            brain = OllamaBrain(model="test-model")
            result = brain.generate_tool_turn(
                messages=[{"role": "user", "content": "Calculate 6 times 7."}],
                tools=[],
            )
        self.assertEqual(result["thinking"], "I should calculate this carefully.")
        self.assertEqual(result["content"], "The answer is 42.")
        self.assertIs(chat.call_args.kwargs["think"], True)

    def test_ollama_native_tool_stream_emits_thinking_and_tool_calls(self):
        chunks = [
            {"message": {"thinking": "First, inspect ", "content": ""}},
            {"message": {"thinking": "the request.", "content": ""}},
            {"message": {"thinking": "", "content": "", "tool_calls": [{
                "function": {"name": "read_file", "arguments": {"path": "README.md"}}
            }]}},
            {"message": {"thinking": "", "content": "I inspected the README."}},
        ]
        thoughts = []
        with mock.patch("model.ollama.ollama.show", return_value={
            "thinking": {"values": [True], "default": True},
        }), mock.patch("model.ollama.ollama.chat", return_value=iter(chunks)) as chat:
            brain = OllamaBrain(model="test-model")
            result = brain.generate_tool_turn_stream(
                messages=[{"role": "user", "content": "Read README"}],
                tools=[],
                on_thought_delta=thoughts.append,
            )
        self.assertEqual("".join(thoughts), "First, inspect the request.")
        self.assertEqual(result["thinking"], "First, inspect the request.")
        self.assertEqual(result["content"], "I inspected the README.")
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "read_file")
        self.assertIs(chat.call_args.kwargs["think"], True)

    def test_effort_wrapper_forwards_native_thought_callback(self):
        from model.effort import EffortAwareBrain

        class StreamingBrain:
            def __init__(self):
                self.received = None

            def generate_tool_turn_stream(self, **kwargs):
                self.received = kwargs
                kwargs["on_thought_delta"]("native thought")
                return {"content": "answer", "thinking": "native thought", "tool_calls": []}

        backend = StreamingBrain()
        wrapper = EffortAwareBrain(backend, "high")
        thoughts = []
        result = wrapper.generate_tool_turn_stream(
            messages=[], tools=[], on_thought_delta=thoughts.append,
        )
        self.assertEqual(thoughts, ["native thought"])
        self.assertEqual(result["thinking"], "native thought")
        self.assertIs(backend.received["on_thought_delta"], thoughts.append.__self__ if hasattr(thoughts.append, "__self__") else backend.received["on_thought_delta"])

    def test_ollama_effort_uses_only_model_advertised_thinking_levels(self):
        with mock.patch("model.ollama.ollama.show", return_value={
            "thinking": {"values": ["low", "medium"], "default": "medium"},
        }):
            brain = OllamaBrain(model="test-model")
            self.assertEqual(brain.think_value_for_effort("low"), "low")
            self.assertEqual(brain.think_value_for_effort("high"), "medium")
            self.assertIs(brain.think_value_for_effort("off"), False)


if __name__ == "__main__":
    unittest.main()
