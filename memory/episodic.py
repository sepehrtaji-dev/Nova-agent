"""Small, bounded, evidence-based episodic memory for Nova.

Only concise task/tool outcome summaries are persisted. Raw tool outputs and raw
tool inputs are deliberately not saved. The JSON file is runtime data and is
ignored by git.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
)


class EpisodicMemory:
    """Persist recent tool experiences and retrieve relevant lessons."""

    def __init__(self, path=None, max_episodes=100):
        configured_path = os.getenv("NOVA_EPISODIC_MEMORY_PATH")
        default_path = (
            Path(configured_path).expanduser()
            if configured_path
            else Path(__file__).resolve().parent / "episodic.json"
        )
        self.path = Path(path) if path is not None else default_path
        self.max_episodes = max(1, int(max_episodes))
        self._episodes = self._load()

    @staticmethod
    def _clean(value, limit=240):
        text = str(value or "")
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max(0, int(limit))]

    def _load(self):
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, list):
                return []
            return [
                item for item in data
                if isinstance(item, dict)
                and isinstance(item.get("tool"), str)
                and item.get("status") in {"confirmed", "failed", "unverifiable"}
            ][-self.max_episodes:]
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return []

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(self._episodes, handle, ensure_ascii=False, indent=2)
                handle.flush()
            temporary.replace(self.path)
            return True
        except OSError:
            return False

    def record(self, goal, tool_name, status, evidence="", message=""):
        """Store a minimal tool outcome; never persist raw inputs or raw outputs."""
        status = str(status or "unverifiable").lower()
        if status not in {"confirmed", "failed", "unverifiable"}:
            status = "unverifiable"
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task": self._clean(goal),
            "tool": self._clean(tool_name, 80),
            "status": status,
            "evidence": self._clean(evidence),
            "message": self._clean(message),
        }
        self._episodes.append(entry)
        self._episodes = self._episodes[-self.max_episodes:]
        return self._save()

    def recent(self, limit=10):
        try:
            count = max(0, int(limit))
        except (TypeError, ValueError):
            count = 10
        return [dict(item) for item in self._episodes[-count:]] if count else []

    def search(self, query, limit=3):
        terms = set(re.findall(r"[a-z0-9_]+", str(query or "").lower()))
        if not terms:
            return []
        scored = []
        for item in self._episodes:
            haystack = " ".join(str(item.get(key, "")) for key in ("task", "tool", "status", "evidence", "message")).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        try:
            count = max(0, int(limit))
        except (TypeError, ValueError):
            count = 3
        return [dict(item) for _, item in scored[:count]]

    def context(self, query, limit=3):
        results = self.search(query, limit=limit)
        if not results:
            return ""
        lines = [
            "Historical tool outcomes are context only and do not prove the current outcome:"
        ]
        for item in results:
            lines.append(
                f"- Task: {item.get('task', '')}; tool: {item.get('tool', '')}; "
                f"status: {item.get('status', '')}; evidence: {item.get('evidence', '')}"
            )
        return "\n".join(lines)

    def clear(self):
        previous = self._episodes
        self._episodes = []
        if self._save():
            return True
        self._episodes = previous
        return False
