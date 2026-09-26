import json
import os


class MemoryStorage:

    def __init__(self, path="memory/long_term.json"):
        self.path = path

        if not os.path.exists(path):
            self.save({
                "profile": {},
                "projects": [],
                "skills": [],
                "preferences": [],
                "facts": []
            })


    def load(self):

        with open(
            self.path,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)


    def save(self, data):

        with open(
            self.path,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )