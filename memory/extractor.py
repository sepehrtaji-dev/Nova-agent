import json


class MemoryExtractor:

    def __init__(self, brain):
        self.brain = brain


    def extract(self, text):

        prompt = f"""
You are Nova's memory system.

Analyze the user's message.

Extract ONLY useful long-term memories.

Store things like:
- name
- skills
- projects
- hardware
- preferences
- important facts

Do NOT store:
- greetings
- temporary questions
- casual conversation


Return ONLY valid JSON.

Format:

{{
    "memories": [
        {{
            "category": "profile",
            "key": "name",
            "value": "example"
        }}
    ]
}}


User message:

{text}
"""


        response = self.brain.generate(prompt)


        try:
            data = json.loads(response)
            return data

        except Exception:

            return {
                "memories": []
            }