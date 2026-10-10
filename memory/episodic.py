"""Small, bounded, evidence-based episodic memory for Nova.

Only concise task/tool outcome summaries are persisted. Raw tool outputs and raw
tool inputs are deliberately not saved. The JSON file is runtime data and is
ignored by git.
"""
import json
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
        default_path = Path(__file__).resolve().parent / "episodic.json"
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
        status = str(status or "unverifiable").strip().lower()
        if status not in {"confirmed", "failed", "unverifiable"}:
            status = "unverifiable"
        tool = self._clean(tool_name, 80)
        if not tool:
            return False

        episode = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "task": self._clean(goal, 180),
            "tool": tool,
            "status": status,
            "evidence": self._clean(evidence, 220),
            "outcome": self._clean(message, 220),
        }
        self._episodes.append(episode)
        self._episodes = self._episodes[-self.max_episodes:]
        return self._save()

    def recent(self, limit=10):
        try:
            count = max(1, min(int(limit), self.max_episodes))
        except (TypeError, ValueError):
            count = 10
        return [dict(item) for item in self._episodes[-count:]]

    def search(self, query, limit=5):
        if not isinstance(query, str) or not query.strip():
            return []
        words = {
            word for word in re.findall(r"\w+", query.casefold())
            if len(word) > 2
        }
        if not words:
            return []
        scored = []
        for episode in self._episodes:
            searchable = " ".join(str(episode.get(key, "")) for key in (
                "task", "tool", "status", "evidence", "outcome"
            )).casefold()
            overlap = sum(1 for word in words if word in searchable)
            if overlap:
                scored.append((overlap, episode))
        scored.sort(key=lambda pair: (-pair[0], pair[1].get("timestamp", "")), reverse=False)
        try:
            count = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            count = 5
        return [dict(item) for _, item in scored[:count]]

    def context(self, query, limit=4):
        matches = self.search(query, limit=limit)
        if not matches:
            return "No relevant episodic experience found."
        lines = [
            "PAST TOOL EXPERIENCES (historical evidence, not a guarantee):"
        ]
        for item in matches:
            task = item.get("task") or "Unspecified task"
            evidence = item.get("evidence") or item.get("outcome") or "No extra evidence recorded."
            lines.append(
                f"- Task: {task}; tool: {item.get('tool')}; "
                f"last status: {item.get('status')}; evidence: {evidence}"
            )
        lines.append(
            "Use these episodes as hints only. Re-check current state and verify every new action; "
            "a previous failure or success does not prove the current outcome."
        )
        return "\n".join(lines)

    def clear(self):
        self._episodes = []
        return self._save()
