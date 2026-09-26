import json
import os
from datetime import datetime, timedelta


class KnowledgeMemory:

    def __init__(self, path="memory/knowledge.json"):
        self.path = path
        self.data = []

        os.makedirs(
            os.path.dirname(self.path),
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
                self.data = json.load(f)

        except Exception:
            self.data = []

    def _save(self):

        with open(
            self.path,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                self.data,
                f,
                ensure_ascii=False,
                indent=2
            )

    def search(self, query, limit=8):

        if not query:
            return []

        words = [
            word.lower()
            for word in query.split()
            if len(word) > 2
        ]

        results = []

        for item in self.data:

            text = (
                str(item.get("topic", "")) + " " +
                str(item.get("fact", "")) + " " +
                str(item.get("source", ""))
            ).lower()

            score = sum(
                1
                for word in words
                if word in text
            )

            if score >= 2:
                results.append(
                    (score, item)
                )

        results.sort(
            key=lambda x: x[0],
            reverse=True
        )

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

            if (
                old.get("topic", "").lower()
                == topic.lower()
                and
                old.get("fact", "").lower()
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