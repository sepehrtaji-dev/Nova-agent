
import json
import re


class MemoryExtractor:

    def __init__(self, brain):
        self.brain = brain

    def _extract_json(self, response):
        if not response:
            return None

        response = str(response).strip()

        response = re.sub(
            r"^\s*```json\s*",
            "",
            response,
            flags=re.IGNORECASE
        )

        response = re.sub(
            r"^\s*```\s*",
            "",
            response
        )

        response = re.sub(
            r"\s*```\s*$",
            "",
            response
        ).strip()

        try:
            data = json.loads(response)

            if isinstance(data, dict):
                return data

        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()

        for index, char in enumerate(response):
            if char != "{":
                continue

            try:
                data, _ = decoder.raw_decode(
                    response[index:]
                )

                if isinstance(data, dict):
                    return data

            except json.JSONDecodeError:
                continue

        return None

    def _normalize_memory(self, item):
        if not isinstance(item, dict):
            return None

        category = item.get("category")
        key = item.get("key")
        value = item.get("value")

        if not isinstance(category, str):
            return None

        if not isinstance(key, str):
            return None

        if value is None:
            return None

        category = category.strip()
        key = key.strip()

        if not category or not key:
            return None

        if isinstance(value, str):
            value = value.strip()

            if not value:
                return None

        return {
            "category": category,
            "key": key,
            "value": value
        }

    def _validate(self, data):
        if not isinstance(data, dict):
            return {
                "memories": []
            }

        memories = data.get("memories", [])

        if not isinstance(memories, list):
            return {
                "memories": []
            }

        valid_memories = []

        for item in memories:
            normalized = self._normalize_memory(item)

            if normalized is not None:
                valid_memories.append(normalized)

        return {
            "memories": valid_memories
        }

    def should_extract(self, text):
        if not isinstance(text, str):
            return False

        text = text.strip().lower()
        if not text:
            return False

        return bool(re.search(
            r"\b(?:remember|don't forget|do not forget|call me|my name is|"
            r"i am|i'm|i use|i prefer|i like|i want you to remember|"
            r"my project|i am working on|i'm working on|my computer|"
            r"my pc|my gpu|my cpu|my setup|my workflow|my preference)\b",
            text,
        ))

    def extract(self, text):
        if not isinstance(text, str):
            return {
                "memories": []
            }

        text = text.strip()

        if not text:
            return {
                "memories": []
            }

        prompt = f"""
You are Nova's long-term memory extraction system.

Analyze ONLY the user's current message.

Extract useful information that should remain available
to Nova in future conversations.

Good memories include:

- user's name
- user's skills
- user's programming languages
- user's projects
- user's hardware
- user's software setup
- persistent preferences
- important workflow preferences
- important facts explicitly stated by the user

Do NOT store:

- greetings
- temporary questions
- one-time requests
- random examples
- information invented by you
- assumptions
- guesses
- temporary tool results
- normal casual conversation

Only extract information explicitly supported by the user's message.

Return exactly this JSON structure:

{{
  "memories": [
    {{
      "category": "profile",
      "key": "name",
      "value": "example"
    }}
  ]
}}

If there is nothing worth remembering, return:

{{"memories":[]}}

USER MESSAGE:

{text}
"""

        try:
            response = self.brain.generate(
                prompt,
                json_mode=True
            )

            data = self._extract_json(response)

            return self._validate(data)

        except Exception:
            return {
                "memories": []
            }

