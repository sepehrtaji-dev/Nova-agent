import json
import os
import re
import tempfile
from datetime import datetime, timedelta


class KnowledgeMemory:

    def __init__(self, path="memory/knowledge.json"):
        self.path = path
        self.data = []

        os.makedirs(
            os.path.dirname(os.path.abspath(self.path)) or ".",
            exist_ok=True
        )

        self._load()

    def _load(self):

        if not os.path.exists(self.path):
            self.data = []
            self._save()
            return

        try:
            with open(
                self.path,
                "r",
                encoding="utf-8"
            ) as f:
                loaded = json.load(f)

            self.data = (
                loaded
                if isinstance(loaded, list)
                else []
            )

        except (OSError, json.JSONDecodeError, TypeError):
            self.data = []

    def _save(self):

        directory = os.path.dirname(self.path) or "."
        fd, temp_path = tempfile.mkstemp(
            prefix=".nova-knowledge-",
            suffix=".json",
            dir=directory,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    self.data,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def search(self, query, limit=8):
        if not isinstance(query, str) or not query.strip():
            return []

        try:
            limit = max(0, int(limit))
        except (TypeError, ValueError):
            limit = 8
        if limit == 0:
            return []

        query_words = set(
            re.findall(r"\b[\w]+\b", query.lower())
        )
        query_words = {
            word for word in query_words
            if len(word) > 2
        }
        if not query_words:
            return []

        results = []
        now = datetime.utcnow()

        for item in self.data:
            if not isinstance(item, dict):
                continue

            expires_at = item.get("expires_at")
            if expires_at:
                try:
                    if datetime.fromisoformat(str(expires_at)) <= now:
                        continue
                except (TypeError, ValueError):
                    continue

            searchable = " ".join(
                str(item.get(field, ""))
                for field in ("topic", "fact")
            ).lower()
            words = set(
                re.findall(r"\b[\w]+\b", searchable)
            )
            overlap = query_words & words
            if len(overlap) < min(2, len(query_words)):
                continue

            try:
                confidence = float(item.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0

            score = (
                len(overlap)
                + max(0.0, min(1.0, confidence)) * 0.25
            )
            results.append((score, item))

        results.sort(key=lambda item: item[0], reverse=True)

        return [
            item
            for _, item in results[:limit]
        ]

    def add(
        self,
        topic,
        fact,
        source="",
        confidence=0.8,
        freshness="stable"
    ):

        topic = str(topic).strip()
        fact = str(fact).strip()

        if not topic or not fact:
            return

        now = datetime.utcnow()

        if freshness == "volatile":
            expires = now + timedelta(days=7)

        elif freshness == "temporary":
            expires = now + timedelta(days=30)

        else:
            expires = None

        item = {
            "topic": topic,
            "fact": fact,
            "source": source,
            "confidence": float(confidence),
            "learned_at": now.isoformat(),
            "last_verified": now.isoformat(),
            "expires_at": (
                expires.isoformat()
                if expires
                else None
            )
        }

        existing = None

        for old in self.data:
            if not isinstance(old, dict):
                continue

            if (
                str(old.get("topic", "")).lower()
                == topic.lower()
                and
                str(old.get("fact", "")).lower()
                == fact.lower()
            ):
                existing = old
                break

        if existing:

            existing.update(item)

        else:

            self.data.append(item)

        self._save()

    def get_context(self, query):

        results = self.search(query)

        if not results:
            return "No stored knowledge."

        lines = []

        for item in results:

            lines.append(
                f"Topic: {item['topic']}\n"
                f"Fact: {item['fact']}\n"
                f"Source: {item.get('source', 'unknown')}\n"
                f"Confidence: {item.get('confidence', 0.0)}\n"
                f"Last verified: {item.get('last_verified', 'unknown')}"
            )

        return "\n\n".join(lines)