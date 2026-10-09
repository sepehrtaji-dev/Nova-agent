
import json
import logging
import re

logger = logging.getLogger(__name__)


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
        candidates = []

        for index, char in enumerate(response):
            if char != "{":
                continue

            try:
                data, _ = decoder.raw_decode(
                    response[index:]
                )

                if isinstance(data, dict):
                    candidates.append(data)

            except json.JSONDecodeError:
                continue

        if not candidates:
            return None

        # Prefer the last valid JSON object (most likely the intended result)
        # or one with expected keys like "memories".
        for candidate in reversed(candidates):
            if "memories" in candidate:
                return candidate

        return candidates[-1]

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

    def _validate(self, data, source_text=""):
        if not isinstance(data, dict):
            return {"memories": []}

        memories = data.get("memories", [])
        if not isinstance(memories, list):
            return {"memories": []}

        source = str(source_text or "").casefold()
        valid_memories = []

        for item in memories:
            normalized = self._normalize_memory(item)
            if normalized is None:
                continue

            value = str(normalized["value"]).strip()
            if not value:
                continue

            # A memory is trusted only when the value is explicitly present
            # in the user's own message. This blocks model-invented facts.
            if value.casefold() not in source:
                continue

            valid_memories.append(normalized)

        return {"memories": valid_memories}

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
            r"my pc|my gpu|my cpu|my setup|my workflow|my preference|"
            r"i have|i live|my favorite|my dog|my cat|my car|"
            r"my job|my work|my school|my university|my team|"
            r"my company|my boss|my colleague|my friend|my family|"
            r"my wife|my husband|my son|my daughter|my parent|"
            r"my mother|my father|my brother|my sister)\b",
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

Think step by step:
1. What did the user explicitly state about themselves?
2. Is this information durable and useful for future conversations?
3. Is it explicitly stated (not inferred or assumed)?

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

            return self._validate(data, source_text=text)

        except Exception as exc:
            logger.warning("Memory extraction failed: %s", exc)
            return {
                "memories": []
            }

