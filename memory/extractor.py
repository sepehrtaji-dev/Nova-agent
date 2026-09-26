import re


class MemoryExtractor:


    def extract(self, text):

        memories = []


        name = re.search(
            r"my name is (.+)",
            text,
            re.I
        )

        if name:
            memories.append(
                (
                    "profile",
                    "name",
                    name.group(1)
                )
            )


        project = re.search(
            r"i am working on (.+)",
            text,
            re.I
        )

        if project:

            memories.append(
                (
                    "projects",
                    "project",
                    project.group(1)
                )
            )


        return memories