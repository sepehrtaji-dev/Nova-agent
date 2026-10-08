import json
import os
import tempfile


class MemoryStorage:
    def __init__(self, path="memory/long_term.json"):
        self.path = os.path.abspath(path)
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        if not os.path.exists(self.path):
            self.save({
                "profile": {},
                "projects": [],
                "skills": [],
                "preferences": [],
                "facts": [],
            })

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError):
            return {
                "profile": {},
                "projects": [],
                "skills": [],
                "preferences": [],
                "facts": [],
            }

        if not isinstance(data, dict):
            return {
                "profile": {},
                "projects": [],
                "skills": [],
                "preferences": [],
                "facts": [],
            }

        return data

    def save(self, data):
        directory = os.path.dirname(self.path) or "."
        fd, temp_path = tempfile.mkstemp(
            prefix=".nova-memory-",
            suffix=".json",
            dir=directory,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    data,
                    handle,
                    indent=4,
                    ensure_ascii=False,
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
