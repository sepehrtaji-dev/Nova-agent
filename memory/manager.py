from memory.storage import MemoryStorage


class MemoryManager:
    """Persistent, user-controlled long-term memory stored as local JSON."""

    def __init__(self, path=None):
        self.storage = MemoryStorage(path=path) if path is not None else MemoryStorage()
        self.data = self.storage.load()

    def remember(self, category, key, value):
        if not isinstance(category, str) or not category.strip():
            raise TypeError("category must be a non-empty string.")
        if not isinstance(key, str) or not key.strip():
            raise TypeError("key must be a non-empty string.")
        if value is None:
            raise TypeError("value must not be None.")

        category = category.strip()
        key = key.strip()
        if category not in self.data:
            self.data[category] = {}

        if isinstance(self.data[category], dict):
            self.data[category][key] = value
        elif isinstance(self.data[category], list):
            replacement = {key: value}
            replaced = False
            for index, item in enumerate(self.data[category]):
                if isinstance(item, dict) and key in item:
                    self.data[category][index] = replacement
                    replaced = True
                    break
            if not replaced:
                self.data[category].append(replacement)
        else:
            self.data[category] = {key: value}

        self.storage.save(self.data)

    @staticmethod
    def _flatten(data, prefix=""):
        items = []
        if isinstance(data, dict):
            for key, value in data.items():
                current = f"{prefix}.{key}" if prefix else str(key)
                items.extend(MemoryManager._flatten(value, current))
        elif isinstance(data, list):
            for value in data:
                items.extend(MemoryManager._flatten(value, prefix))
        else:
            items.append((prefix, data))
        return items

    def entries(self):
        """Return a flattened view suitable for memory inspection."""
        return [
            {"key": key, "value": value}
            for key, value in self._flatten(self.data)
        ]

    def forget(self, category, key):
        """Forget one exact category/key entry; return whether anything changed."""
        if not isinstance(category, str) or not category.strip():
            return False
        if not isinstance(key, str) or not key.strip():
            return False

        category = category.strip()
        key = key.strip()
        values = self.data.get(category)
        changed = False

        if isinstance(values, dict) and key in values:
            del values[key]
            changed = True
        elif isinstance(values, list):
            kept = [
                item for item in values
                if not (isinstance(item, dict) and key in item)
            ]
            changed = len(kept) != len(values)
            if changed:
                self.data[category] = kept

        if changed:
            self.storage.save(self.data)
        return changed

    def relevant(self, query, limit=5):
        import re

        if not isinstance(query, str) or not query.strip():
            return []

        words = {
            item for item in re.findall(r"\b[\w]+\b", query.casefold())
            if len(item) > 2
        }
        if not words:
            return []

        scored = []
        for key, value in self._flatten(self.data):
            value_text = str(value)
            searchable = f"{key} {value_text}".casefold()
            value_words = set(re.findall(r"\b[\w]+\b", searchable))
            overlap = words & value_words
            if not overlap:
                continue

            score = len(overlap)
            key_text = re.sub(r"[_\-\.]+", " ", str(key).casefold())
            if any(
                word in key_text or word.rstrip("s") in key_text
                for word in words
            ):
                score += 1

            scored.append((score, key, value_text))

        scored.sort(key=lambda item: (-item[0], item[1]))
        try:
            count = max(0, min(int(limit), 50))
        except (TypeError, ValueError):
            count = 5
        return [
            {"key": key, "value": value, "score": score}
            for score, key, value in scored[:count]
        ]

    def get_relevant_context(self, query, limit=5):
        matches = self.relevant(query, limit=limit)
        if not matches:
            return "No relevant saved user memory."
        return "\n".join(
            f"- {item['key']}: {item['value']}"
            for item in matches
        )

    def get_memory(self):
        return self.data
