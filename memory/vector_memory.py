import json
import math
import os

from memory.embeddings import EmbeddingModel


class VectorMemory:
    def __init__(self, path="memory/database/memories.json", dimensions=256):
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            self._write([])
        self.embedder = EmbeddingModel(dimensions=dimensions)
        self.memories = self.load()

    def _write(self, data):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def save(self):
        self._write(self.memories)

    def add(self, text):
        text = str(text or "").strip()
        if not text:
            return
        self.memories.append({
            "text": text,
            "vector": self.embedder.encode(text),
        })
        self.save()

    @staticmethod
    def _cosine(left, right):
        if len(left) != len(right):
            return 0.0
        denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(
            sum(x * x for x in right)
        )
        if denominator == 0:
            return 0.0
        return sum(a * b for a, b in zip(left, right)) / denominator

    def search(self, query, limit=3):
        query = str(query or "").strip()
        if not query:
            return []

        vector = self.embedder.encode(query)
        results = []

        for item in self.memories:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            candidate = item.get("vector")
            if not isinstance(text, str) or not isinstance(candidate, list):
                continue
            score = self._cosine(vector, candidate)
            results.append((score, text))

        results.sort(key=lambda item: item[0], reverse=True)
        return [text for _, text in results[:max(0, int(limit))]]
