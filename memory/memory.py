import json
import os
import tempfile


class LongTermMemory:
    """Backward-compatible persistent memory adapter."""

    DEFAULT_DATA = {
        "profile": {},
        "projects": [],
        "preferences": [],
        "facts": [],
    }

    def __init__(self, path="memory/long_term.json"):
        self.path = os.path.abspath(path)
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.data = self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError):
            data = None

        if not isinstance(data, dict):
            data = {
                key: (value.copy() if isinstance(value, dict) else list(value))
                for key, value in self.DEFAULT_DATA.items()
            }
            self.save(data)

        return data

    def save(self, data):
        if not isinstance(data, dict):
            raise TypeError("Memory data must be a dictionary.")

        directory = os.path.dirname(self.path) or "."
        fd, temp_path = tempfile.mkstemp(
            prefix=".nova-long-term-",
            suffix=".json",
            dir=directory,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=4, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def add_fact(self, category, key, value):
        category = str(category).strip()
        key = str(key).strip()
        if not category or not key:
            raise ValueError("category and key are required.")

        if category == "profile":
            target = self.data.setdefault("profile", {})
            if not isinstance(target, dict):
                target = {}
                self.data["profile"] = target
            target[key] = value
        else:
            target = self.data.setdefault(category, [])
            if not isinstance(target, list):
                target = []
                self.data[category] = target
            target.append({key: value})

        self.save(self.data)

    def get_context(self):
        return self.data
