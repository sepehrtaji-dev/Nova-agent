"""End-to-end probe: the local Ollama server must stay reachable even when
stale proxy environment variables point at a dead port.

Run as a subprocess by
``test_ollama_transient_errors.LocalServerWithDeadProxyEndToEndTests``.
The parent supplies an environment with HTTP_PROXY/HTTPS_PROXY aimed at a
closed port and NO no_proxy entry; this child starts a fake Ollama server on
the loopback, imports ``model.ollama`` (which must exempt loopback hosts
from the proxy BEFORE the ollama client is built) and exercises both the
plain and the streaming chat path.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOllama(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        chunk = {
            "model": "fake",
            "created_at": "now",
            "message": {"role": "assistant", "content": "pong"},
            "done": not body.get("stream"),
        }
        payload = json.dumps(chunk).encode()
        if body.get("stream"):
            tail = dict(chunk, message={"role": "assistant", "content": ""}, done=True)
            payload += b"\n" + json.dumps(tail).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    repo = sys.argv[1]
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    except OSError as exc:
        # Some locked-down Windows environments have no usable Winsock
        # provider. Report an explicit skip instead of mislabeling this as
        # an Ollama proxy-bypass failure.
        if getattr(exc, "winerror", None) == 10106:
            print(f"E2E-SKIP: Windows socket provider unavailable ({exc})", flush=True)
            return
        raise
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["OLLAMA_HOST"] = f"http://127.0.0.1:{server.server_address[1]}"

    sys.path.insert(0, repo)
    from model.ollama import chat_with_retries

    plain = chat_with_retries(
        {"model": "fake", "messages": [{"role": "user", "content": "hi"}], "stream": False},
        attempts=1,
    )
    assert plain.message.content == "pong", plain
    print("E2E-OK", flush=True)

    parts = list(chat_with_retries(
        {"model": "fake", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        attempts=1,
    ))
    assert any(p.message.content == "pong" for p in parts), parts
    print("STREAM-OK", flush=True)


if __name__ == "__main__":
    main()
