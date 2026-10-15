"""Live capability probes.

Self-knowledge answers about *what Nova can do right now* must be measured, not
recited from configuration. A registered tool proves only that code exists; a
reachability probe proves the capability actually works in this run.

Every probe is bounded, cached briefly, and fails closed: an unverifiable
capability is reported as unverified rather than as available.
"""
from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 45.0  # seconds


def _cached(key, producer):
    now = time.time()
    hit = _CACHE.get(key)
    if hit is not None and now - hit[0] < _CACHE_TTL:
        return hit[1]
    try:
        value = producer()
    except Exception as exc:  # never let a probe break an answer
        value = {
            "status": "error",
            "reachable": False,
            "detail": f"probe failed ({type(exc).__name__})",
        }
    _CACHE[key] = (now, value)
    return value


def clear_cache():
    _CACHE.clear()


def probe_web(timeout: float = 6.0) -> dict:
    """Actually reach the network, not just check that the tool is registered.

    Tries a real HTTP request first, then a raw DNS/TCP connect, so a blocked
    HTTP path does not hide a working network.
    """
    def _run():
        attempts = []

        for url in ("https://duckduckgo.com/", "https://example.com/"):
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0 (Nova probe)"}
                )
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    if int(getattr(response, "status", 200)) < 500:
                        return {
                            "status": "reachable",
                            "reachable": True,
                            "method": "http",
                            "target": url,
                            "detail": f"HTTP {getattr(response, 'status', '?')} from {url}",
                        }
            except urllib.error.HTTPError as exc:
                # An HTTP error still proves the network path works.
                if int(getattr(exc, "code", 0)) < 500:
                    return {
                        "status": "reachable",
                        "reachable": True,
                        "method": "http",
                        "target": url,
                        "detail": f"HTTP {exc.code} from {url} (network reachable)",
                    }
                attempts.append(f"{url}: HTTP {exc.code}")
            except Exception as exc:
                attempts.append(f"{url}: {type(exc).__name__}")

        try:
            socket.create_connection(("1.1.1.1", 53), timeout=timeout).close()
            return {
                "status": "reachable",
                "reachable": True,
                "method": "tcp",
                "target": "1.1.1.1:53",
                "detail": "TCP connect succeeded; HTTP may be filtered",
            }
        except Exception as exc:
            attempts.append(f"tcp 1.1.1.1:53: {type(exc).__name__}")

        return {
            "status": "unreachable",
            "reachable": False,
            "method": "none",
            "target": "",
            "detail": "; ".join(attempts) or "no probe target responded",
        }

    return _cached("web", _run)


def probe_model_details(core):
    """Describe the model actually serving this session, from live metadata.

    Replaces hardcoded claims such as "3 billion parameters" and "runs locally":
    for a remote model those are simply false, and the model then repeats them.
    Returns a dict that is always safe to render, with unknown fields marked.
    """
    brain = getattr(core, "brain", None)
    model = str(getattr(brain, "model", "") or "").strip()

    try:
        from model.provider import backend_kind, describe_brain

        kind = backend_kind(brain)
        description = describe_brain(brain)
    except Exception:
        kind, description = "unknown", "an unspecified backend"

    details = {
        "model": model or "unknown",
        "backend_kind": kind,
        "backend_description": description,
        "location": ("on the provider's servers" if kind == "remote"
                     else "on this computer"),
        "parameter_count": None,
        "parameter_size": None,
        "architecture": None,
        "quantization": None,
        "context_length": None,
    }

    # Local models expose metadata through Ollama; remote models generally do
    # not, so those fields stay unknown rather than being guessed.
    if kind == "local" and model:
        try:
            from agent.introspection import inspect_model

            info = inspect_model(core)
            if info.get("status") == "available":
                details["parameter_count"] = info.get("parameter_count")
                details["parameter_size"] = info.get("parameter_size")
                details["architecture"] = info.get("architecture")
                details["quantization"] = info.get("quantization")
                details["context_length"] = info.get("model_context_length")
        except Exception:
            pass

    return details


def describe_model(core):
    """One-line, always-true sentence about the model serving this session."""
    d = probe_model_details(core)
    parts = [f"The model serving this session is '{d['model']}', running "
             f"{d['location']}"]
    if d["parameter_size"]:
        parts.append(f"reported size {d['parameter_size']}")
    if d["quantization"]:
        parts.append(f"quantization {d['quantization']}")
    sentence = ", ".join(parts) + "."
    if d["backend_kind"] == "remote":
        sentence += (" Its parameter count is not visible to Nova, so it cannot "
                     "be stated.")
    elif not d["parameter_size"]:
        sentence += (" No size metadata is available from the local runtime, so "
                     "it cannot be stated.")
    return sentence


def probe_ollama(timeout: float = 4.0) -> dict:
    """Confirm the local model server answers, not merely that it is configured."""
    def _run():
        import json

        try:
            request = urllib.request.Request(
                "http://127.0.0.1:11434/api/tags",
                headers={"User-Agent": "Nova probe"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
            models = [
                str(item.get("name") or item.get("model") or "").strip()
                for item in (payload.get("models") or [])
                if isinstance(item, dict)
            ]
            models = [name for name in models if name]
            return {
                "status": "running",
                "reachable": True,
                "models": sorted(set(models)),
                "detail": f"Ollama responded; {len(set(models))} model(s) installed",
            }
        except Exception as exc:
            return {
                "status": "unreachable",
                "reachable": False,
                "models": [],
                "detail": f"Ollama did not respond ({type(exc).__name__})",
            }

    return _cached("ollama", _run)


def probe_math() -> dict:
    """Confirm the math path actually works.

    utils.math_parser formats LaTeX-like notation into readable text; it does
    not evaluate arithmetic. So this checks that the formatter loads and
    transforms correctly, and that Python evaluation is available for actual
    arithmetic, rather than pretending a single "math engine" exists.
    """
    def _run():
        details = []
        ok = True

        try:
            import sys
            from pathlib import Path

            root = Path(__file__).resolve().parent.parent
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from utils.math_parser import parse_math

            rendered = parse_math(r"\frac{1}{2} + \sqrt{4}")
            if "√" not in rendered and "/" not in rendered:
                ok = False
                details.append(f"formatter gave unexpected output: {rendered!r}")
            else:
                details.append(f"LaTeX formatter works ({rendered!r})")
        except Exception as exc:
            ok = False
            details.append(f"math formatter unavailable ({type(exc).__name__})")

        try:
            value = eval("2+2*2", {"__builtins__": {}}, {})  # noqa: S307 - constant
            if value != 6:
                ok = False
                details.append(f"arithmetic gave {value!r}, expected 6")
            else:
                details.append("arithmetic evaluation works")
        except Exception as exc:
            ok = False
            details.append(f"arithmetic evaluation failed ({type(exc).__name__})")

        return {
            "status": "working" if ok else "degraded",
            "reachable": ok,
            "detail": "; ".join(details),
        }

    return _cached("math", _run)


def probe_coding() -> dict:
    """Coding needs a writable workspace plus a terminal/file tool registered."""
    def _run():
        try:
            import os
            import tempfile

            writable = False
            detail = ""
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".nova", delete=True
                ) as handle:
                    handle.write("probe")
                    handle.flush()
                    writable = True
                detail = "workspace is writable"
            except Exception as exc:
                detail = f"workspace not writable ({type(exc).__name__})"

            return {
                "status": "working" if writable else "degraded",
                "reachable": writable,
                "detail": detail,
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "reachable": False,
                "detail": f"probe failed ({type(exc).__name__})",
            }

    return _cached("coding", _run)
