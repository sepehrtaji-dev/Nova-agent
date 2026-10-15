"""A tiny OpenAI-compatible server for testing Nova's remote mode offline.

Run this in one terminal, then point Nova at it in another:

    python fake_openai_server.py
    set NOVA_PROVIDER=remote
    set NOVA_API_BASE_URL=http://127.0.0.1:8765/v1
    set NOVA_API_MODEL=fake-model
    set NOVA_API_KEY=test-key
    python check_provider.py

It echoes back a Nova-shaped answer, so you can confirm the whole remote path
(request shape, auth, parsing, identity prompt) before using a real provider or
spending money.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8765


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  [{self.command}] {fmt % args}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        messages = payload.get("messages", [])
        system = messages[0].get("content", "") if messages else ""
        user = messages[-1].get("content", "") if messages else ""

        auth = self.headers.get("Authorization", "")
        print(f"  model={payload.get('model')!r} messages={len(messages)} "
              f"auth={'yes' if auth.startswith('Bearer ') else 'NO'}")

        # Show that Nova's identity reached us.
        if "Nova" in system:
            print("  identity prompt received: YES (mentions Nova)")
        else:
            print("  identity prompt received: NO")

        reply = (
            "ready"
            if payload.get("response_format")
            else (
                f"[fake-model] I received your prompt "
                f"({len(user)} chars) and Nova's identity block. "
                "This proves the remote path works end to end."
            )
        )

        body = json.dumps({
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "model": payload.get("model", "fake-model"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10,
                      "total_tokens": 20},
        }).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print("=" * 68)
    print(f"Fake OpenAI-compatible server on http://127.0.0.1:{PORT}/v1")
    print("Point Nova at it with NOVA_API_BASE_URL and press Ctrl+C to stop.")
    print("=" * 68)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
