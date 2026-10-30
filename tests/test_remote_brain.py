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

    def test_successful_call_parses_content(self):
        self.assertEqual(self.brain.generate("hi"), "ready")
        sent = CAPTURED[-1]
        self.assertTrue(sent["path"].endswith("/chat/completions"))
        self.assertEqual(sent["body"]["model"], "test-model")
        self.assertEqual(len(sent["body"]["messages"]), 2)


    def test_calls_without_explicit_system_prompt_receive_nova_instructions(self):
        self.brain.generate("my name is sepehr")
        system_message = CAPTURED[-1]["body"]["messages"][0]["content"]
        self.assertIn("You are Nova", system_message)
        self.assertIn("untrusted data", system_message)

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


if __name__ == "__main__":
    unittest.main()
