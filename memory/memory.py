import json
import os


class LongTermMemory:

    def __init__(
        self,
        path="memory/long_term.json"
    ):
        self.path = path

        if not os.path.exists(self.path):
            self.save(
                {
                    "profile": {},
                    "projects": [],
                    "preferences": [],
                    "facts": []
                }
            )

        self.data = self.load()


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


    def add_fact(
        self,
        category,
        key,
        value
    ):

        if category == "profile":

            self.data["profile"][key] = value

        else:

            self.data[category].append(
                {
                    key: value
                }
            )

        self.save(self.data)


    def get_context(self):

        return self.data