import json
import logging
import re

logger = logging.getLogger(__name__)

# Long-term memory is not a password manager. Never persist values attached to
# credential labels, bearer credentials, or private-key blocks.
_SECRET_VALUE_PATTERNS = (
    re.compile(
        r"(?is)\b(?:password|passwd|api[_ -]?key|access[_ -]?token|"
        r"refresh[_ -]?token|auth[_ -]?token|client[_ -]?secret|secret)\b"
        r"\s*(?:is\s+|[:=]\s*)?([^\s,;]+)"
    ),
    re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/=-]+)"),
)
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    re.DOTALL,
)


class MemoryExtractor:

    def __init__(self, brain):
        self.brain = brain

    def _extract_json(self, response):
        if not response:
            return None

        response = str(response).strip()
        response = re.sub(r"^\s*\x60\x60\x60json\s*", "", response, flags=re.IGNORECASE)
        response = re.sub(r"^\s*\x60\x60\x60\s*", "", response)
        response = re.sub(r"\s*\x60\x60\x60\s*$", "", response).strip()

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
                data, _ = decoder.raw_decode(response[index:])
                if isinstance(data, dict):
                    candidates.append(data)
            except json.JSONDecodeError:
                continue

        if not candidates:
            return None
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
        if not isinstance(category, str) or not isinstance(key, str) or value is None:
            return None
        category = category.strip()
        key = key.strip()
        if not category or not key:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        return {"category": category, "key": key, "value": value}

    @staticmethod
    def _secret_values(source_text):
        """Return credential-like values explicitly labeled in the source text."""
        source = str(source_text or "")
        secrets = []
        for pattern in _SECRET_VALUE_PATTERNS:
            for match in pattern.finditer(source):
                candidate = match.group(1).strip().strip("'").strip('"')
                if candidate:
                    secrets.append(candidate.casefold())
        for match in _PRIVATE_KEY_PATTERN.finditer(source):
            secrets.append(match.group(0).casefold())
        return secrets

    def _validate(self, data, source_text=""):
        if not isinstance(data, dict):
            return {"memories": []}
        memories = data.get("memories", [])
        if not isinstance(memories, list):
            return {"memories": []}

        source = str(source_text or "").casefold()
        secret_values = self._secret_values(source_text)
        valid_memories = []
        for item in memories:
            normalized = self._normalize_memory(item)
            if normalized is None:
                continue
            value = str(normalized["value"]).strip()
            if not value or value.casefold() not in source:
                continue
            # Credential values should never be persisted as long-term memory.
            if any(value.casefold() in secret or secret in value.casefold() for secret in secret_values):
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
        if not isinstance(text, str) or not text.strip():
            return {"memories": []}
        text = text.strip()
        prompt = f"""
You are Nova's long-term memory extraction system.

Identify durable information the user explicitly stated about themselves:
name, skills, programming languages, projects, hardware, software setup,
persistent preferences, and workflow preferences.

Do not store greetings, temporary questions, one-time requests, examples,
model guesses, assumptions, temporary tool results, passwords, API keys,
access tokens, secrets, or private keys. Never copy credential values into
memory, even when the user explicitly mentions them.

Return JSON only:
{{
  "memories": [
    {{"category": "profile", "key": "name", "value": "example"}}
  ]
}}
If there is nothing worth remembering, return {{"memories":[]}}.

USER MESSAGE:
{text}
"""
        try:
            response = self.brain.generate(prompt, json_mode=True)
            return self._validate(self._extract_json(response), source_text=text)
        except Exception as exc:
            logger.warning("Memory extraction failed: %s", exc)
            return {"memories": []}
