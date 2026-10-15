"""Check the configured model backend and report what is actually reachable.

Usage:
    python check_provider.py

Reads the same NOVA_* environment variables the agent uses, so it reports the
truth about the configuration that would be active in a real run. It never
prints the API key.

Exit codes: 0 = backend ready, 1 = backend not usable.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model.provider import (  # noqa: E402
    backend_kind,
    build_brain,
    describe_brain,
    remote_is_configured,
    requested_provider,
)


def mask(value):
    """Show enough of a secret to identify it, never the whole value."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]} ({len(value)} chars)"


def main():
    print("=" * 72)
    print("NOVA MODEL BACKEND CHECK")
    print("=" * 72)
    print(f"  NOVA_PROVIDER      : {requested_provider()}")
    print(f"  NOVA_API_MODEL     : {os.getenv('NOVA_API_MODEL') or '(not set)'}")
    print(f"  NOVA_API_BASE_URL  : {os.getenv('NOVA_API_BASE_URL') or '(default: api.openai.com/v1)'}")
    print(f"  NOVA_API_KEY       : {mask(os.getenv('NOVA_API_KEY', ''))}")
    print(f"  NOVA_MODEL (local) : {os.getenv('NOVA_MODEL') or '(auto-discover)'}")
    print(f"  remote configured  : {remote_is_configured()}")
    print()

    try:
        brain = build_brain()
    except RuntimeError as exc:
        print("CONFIGURATION ERROR")
        print(f"  {exc}")
        print()
        print("The provider was requested explicitly but is not usable. Nova will")
        print("not silently fall back to a local model.")
        return 1

    kind = backend_kind(brain)
    print(f"  selected backend   : {kind}")
    print(f"  {describe_brain(brain)}")
    print()

    print("=" * 72)
    print("LIVE PROBE")
    print("=" * 72)

    if kind == "remote":
        result = brain.probe()
        print(f"  status  : {result['status']}")
        print(f"  detail  : {result['detail']}")
        ok = result.get("reachable", False)
    else:
        print("  (local model: checking Ollama and generation)")
        try:
            from agent import capability_probe

            probe = capability_probe.probe_ollama()
            print(f"  ollama  : {probe['detail']}")
            if not probe.get("reachable"):
                print("  hint    : start it with 'ollama serve'")
                return 1
        except Exception as exc:
            print(f"  ollama probe failed: {exc}")
            return 1
        try:
            reply = brain.generate("Reply with the single word: ready")
            print(f"  generate: OK ({reply[:40]!r})")
            ok = True
        except Exception as exc:
            print(f"  generate: FAILED ({type(exc).__name__}: {exc})")
            ok = False

    print()
    print("=" * 72)
    if ok:
        print("RESULT: backend is ready. Run 'python main.py' to start Nova.")
    else:
        print("RESULT: backend is NOT ready. Fix the issue above and re-run.")
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
