from memory.storage import MemoryStorage


class MemoryManager:


    def __init__(self):

        self.storage = MemoryStorage()

        self.data = self.storage.load()



    def remember(
        self,
        category,
        key,
        value
    ):

        if category not in self.data:

            self.data[category] = {}


        if isinstance(
            self.data[category],
            dict
        ):

            self.data[category][key] = value


        else:

            self.data[category].append(
                {
                    key:value
                }
            )


        self.storage.save(
            self.data
        )




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
            if any(token in str(key).casefold().split(".") for token in words):
                score += 1

            scored.append((score, key, value_text))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            {"key": key, "value": value, "score": score}
            for score, key, value in scored[:max(1, int(limit))]
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