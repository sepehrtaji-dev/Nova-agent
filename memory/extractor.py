import re


class MemoryExtractor:


    def extract(self, text):

        memories = []


        patterns = [

            (
                "profile",
                "name",
                r"my name is (.+)"
            ),

            (
                "projects",
                "project",
                r"i am working on (.+)"
            ),

            (
                "skills",
                "skill",
                r"i know (.+)"
            )

        ]


        for category,key,pattern in patterns:

            result = re.search(
                pattern,
                text,
                re.I
            )

            if result:

                memories.append(
                    (
                        category,
                        key,
                        result.group(1)
                    )
                )


        return memories