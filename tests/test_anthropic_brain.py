"""Tests for Anthropic Messages API compatibility and native tool-use mapping."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from model.anthropic import AnthropicBrain
from model.provider import backend_kind, build_brain


CAPTURED = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        CAPTURED.append((self.path, self.headers, payload))
        body = {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [
                {"type": "text", "text": "I will inspect the file."},
                {"type": "tool_use", "id": "toolu_1", "name": "read_file",
                 "input": {"path": "README.md"}},
            ],
            "stop_reason": "tool_use",
        }
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class AnthropicBrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        CAPTURED.clear()
        self.brain = AnthropicBrain(
            model="claude-test", api_key="test-secret-key", base_url=self.base
        )

    def test_messages_api_headers_and_endpoint(self):
        result = self.brain.generate("Hello", system_prompt="Be concise.")
        self.assertEqual(result, "I will inspect the file.")
        path, headers, payload = CAPTURED[-1]
        self.assertEqual(path, "/v1/messages")
        self.assertEqual(headers.get("x-api-key"), "test-secret-key")
        self.assertEqual(headers.get("anthropic-version"), "2023-06-01")
        self.assertEqual(payload["system"], "Be concise.")
        self.assertEqual(payload["model"], "claude-test")

    def test_native_tool_use_is_normalized_for_nova_loop(self):
        result = self.brain.generate_tool_turn(
            [{"role": "user", "content": "Read README."}],
            [{"type": "function", "function": {
                "name": "read_file", "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            }}],
            system_prompt="You are Nova.",
        )
        self.assertEqual(result["finish_reason"], "tool_calls")
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(json.loads(result["tool_calls"][0]["function"]["arguments"]), {"path": "README.md"})
        self.assertEqual(CAPTURED[-1][2]["tools"][0]["name"], "read_file")

    def test_openai_tool_history_converts_to_anthropic_blocks(self):
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "read_file", "arguments": "{\"path\":\"README.md\"}"},
            }]},
            {"role": "tool", "tool_call_id": "call_1", "content": "file text"},
        ]
        converted = self.brain._convert_messages(messages)
        self.assertEqual(converted[0]["content"][0]["type"], "tool_use")
        self.assertEqual(converted[1]["content"][0]["type"], "tool_result")
        self.assertEqual(converted[1]["content"][0]["tool_use_id"], "call_1")

    def test_provider_factory_selects_anthropic_backend(self):
        env = {
            "NOVA_PROVIDER": "remote",
            "NOVA_API_PROVIDER": "anthropic",
            "NOVA_API_MODEL": "claude-test",
            "NOVA_API_KEY": "test-secret-key",
            "NOVA_API_BASE_URL": self.base,
        }
        with mock.patch.dict(os.environ, env, clear=True):
            brain = build_brain()
            self.assertIsInstance(brain, AnthropicBrain)
            self.assertEqual(backend_kind(brain), "remote")


if __name__ == "__main__":
    unittest.main()
