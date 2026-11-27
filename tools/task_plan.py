"""Model-authored task checklist for Nova's native tool loop.

The model calls ``update_plan`` to create its task list and to tick items off as
it works. The tool only validates and normalizes the list; the tool loop
publishes it to the UI and uses it to decide whether the work is really done.
"""
from __future__ import annotations

import json

_DONE = {"completed", "complete", "done", "verified"}
_FAILED = {"failed", "error"}
_RUNNING = {"in_progress", "in progress", "running", "active"}
_VALID = _DONE | _FAILED | _RUNNING | {"pending"}
MAX_STEPS = 20
MAX_TEXT = 300


def normalize_status(value):
    status = str(value or "pending").strip().casefold().replace("-", "_")
    if status in {"in progress"}:
        status = "in_progress"
    if status in _DONE:
        return "completed"
    if status in _FAILED:
        return "failed"
    if status in _RUNNING:
        return "in_progress"
    return "pending"


def normalize_plan(steps):
    """Return a list of {description, status} dicts, or raise ValueError."""
    if not isinstance(steps, list) or not steps:
        raise ValueError("'steps' must be a non-empty list.")
    normalized = []
    for index, step in enumerate(steps[:MAX_STEPS], 1):
        if isinstance(step, str):
            step = {"description": step}
        if not isinstance(step, dict):
            raise ValueError(f"Step {index} must be an object or a string.")
        description = str(step.get("description") or step.get("title") or "").strip()
        if not description:
            raise ValueError(f"Step {index} needs a non-empty description.")
        normalized.append({
            "description": description[:MAX_TEXT],
            "status": normalize_status(step.get("status")),
        })
    return normalized


def open_steps(steps):
    """Steps that still need work (pending, in progress or failed)."""
    return [
        step for step in (steps or [])
        if isinstance(step, dict) and normalize_status(step.get("status")) != "completed"
    ]


class TaskPlanTool:
    def update_plan(self, input_json):
        try:
            payload = json.loads(input_json) if isinstance(input_json, str) else dict(input_json or {})
        except (TypeError, ValueError):
            return json.dumps({"ok": False, "error": "Input must be valid JSON."})
        try:
            steps = normalize_plan(payload.get("steps"))
        except ValueError as exc:
            return json.dumps({"ok": False, "error": str(exc)})
        done = sum(1 for step in steps if step["status"] == "completed")
        return json.dumps({
            "ok": True,
            "steps": steps,
            "completed": done,
            "total": len(steps),
            "remaining": len(steps) - done,
        }, ensure_ascii=False)

    def verify(self, tool_input, tool_result):
        """The plan is a bookkeeping record; confirm it when it parsed cleanly."""
        from agent.verifier import VerificationResult
        try:
            data = json.loads(tool_result)
        except (TypeError, ValueError):
            data = {}
        if isinstance(data, dict) and data.get("ok"):
            return VerificationResult("confirmed", str(tool_result)[:200], "Task list recorded.")
        return VerificationResult("failed", str(tool_result)[:200], "Task list was rejected.")
