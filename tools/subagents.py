"""Isolated child-agent delegation for Nova's model-driven tool loop."""
from __future__ import annotations

import json
import threading


class SubagentTool:
    """Run a bounded, isolated child NovaCore for a self-contained subtask."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cancel_event = None

    def prepare_input(self, arguments, context):
        payload = dict(arguments or {})
        context = context if isinstance(context, dict) else {}
        access = context.get("parent_access", {})
        payload["_parent_access"] = access if isinstance(access, dict) else {}
        payload["_parent_effort"] = str(context.get("parent_effort", "medium") or "medium")
        self._cancel_event = context.get("cancel_event")
        return payload

    def run(self, input_json):
        try:
            payload = json.loads(input_json) if isinstance(input_json, str) else dict(input_json or {})
        except (TypeError, ValueError):
            return json.dumps({"status": "failed", "error": "Subagent input must be valid JSON."})

        prompt = str(payload.get("task", "") or "").strip()
        if not prompt:
            return json.dumps({"status": "failed", "error": "A non-empty subtask is required."})
        if len(prompt) > 6000:
            return json.dumps({"status": "failed", "error": "Subtask exceeds the 6000-character limit."})
        if not self._lock.acquire(blocking=False):
            return json.dumps({"status": "failed", "error": "A subagent is already running; continue with the available results."})

        try:
            from agent.core import NovaCore
            from agent.cancellation import GenerationCancelled

            child = NovaCore()
            parent_access = payload.get("_parent_access")
            if isinstance(parent_access, dict):
                child.set_access(**parent_access)
            # A child is deliberately unable to recursively spawn more agents.
            child.tools.tools.pop("spawn_subagent", None)
            setter = getattr(child.brain, "set_effort", None)
            if callable(setter):
                setter(str(payload.get("_parent_effort", "medium")))
            child.cancel_event = self._cancel_event
            result = child.ask(
                "You are a delegated subagent. Complete only this isolated subtask. "
                "Return a concise, factual result with evidence and any limitations.\n\n"
                "SUBTASK:\n" + prompt
            )
            if self._cancel_event is not None and self._cancel_event.is_set():
                return json.dumps({"status": "cancelled", "error": "The parent request was stopped."})
            return json.dumps({
                "status": "completed",
                "result": str(result or "")[:20000],
            }, ensure_ascii=False)
        except GenerationCancelled:
            return json.dumps({"status": "cancelled", "error": "The parent request was stopped."})
        except Exception as exc:
            # A failed child is a tool result, not a fatal parent-agent error.
            return json.dumps({
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }, ensure_ascii=False)
        finally:
            self._cancel_event = None
            self._lock.release()
