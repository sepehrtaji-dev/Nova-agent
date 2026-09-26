import json
import os


class Memory:
    def __init__(self, path="memory/nova_memory.json"):
        self.path = path
        self.data = self.load()

    def load(self):
        if not os.path.exists(self.path):
            return []

        with open(self.path, "r", encoding="utf-8") as file:
            return json.load(file)

    def save(self):
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(
                self.data,
                file,
                indent=4,
                ensure_ascii=False
            )

    def add(self, role, content):
        self.data.append(
            {
                "role": role,
                "content": content
            }
        )

        self.save()

    def get_recent(self, limit=10):
        return self.data[-limit:]