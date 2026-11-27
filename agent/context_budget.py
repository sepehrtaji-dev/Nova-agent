"""Keep native tool-loop prompts inside the model's context window.

A local model only has a few thousand tokens. When the prompt is longer than
that, the server silently drops the OLDEST text, which is exactly where the
user's request lives. These helpers fit the conversation into a token budget
without ever dropping the user's request, and without mutating the loop's own
full message history (every turn is re-fitted from the full history, so the
newest results stay complete whenever there is room for them).
"""
from __future__ import annotations

import copy
import json

# Conservative: mixed prose, JSON and code average ~3 characters per token.
CHARS_PER_TOKEN = 3
OUTPUT_RESERVE_TOKENS = 1536
MIN_ALLOWANCE_TOKENS = 1000
OLD_RESULT_CHARS = 600
MIN_LATEST_RESULT_CHARS = 1200
SESSION_MARKER = "\n\nSESSION CONTEXT"
_SHORTENED = "\n[shortened to fit the model's context window]"


def estimate_tokens(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def message_tokens(message):
    if not isinstance(message, dict):
        return estimate_tokens(str(message))
    total = 4
    for key in ("content", "thinking", "tool_calls"):
        value = message.get(key)
        if value:
            total += estimate_tokens(value)
    return total


def _cut(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:max(0, limit)].rstrip() + _SHORTENED


def _first_sentences(text, limit):
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut = max(window.rfind(". "), window.rfind("; "))
    if cut >= limit // 3:
        return window[:cut + 1]
    cut = window.rfind(" ")
    return (window[:cut] if cut > 0 else window).rstrip(",;:") + "."


def _shrink_schema(node, limit):
    if isinstance(node, dict):
        description = node.get("description")
        if isinstance(description, str) and len(description) > limit:
            node["description"] = _first_sentences(description, limit)
        for value in node.values():
            _shrink_schema(value, limit)
    elif isinstance(node, list):
        for value in node:
            _shrink_schema(value, limit)


def compact_definitions(definitions, *, max_description=220, max_property_description=100):
    """Shorten tool descriptions so the tool list leaves room for the work."""
    compacted = []
    for definition in definitions or []:
        item = copy.deepcopy(definition)
        function = item.get("function") if isinstance(item, dict) else None
        if isinstance(function, dict):
            function["description"] = _first_sentences(function.get("description", ""), max_description)
            _shrink_schema(function.get("parameters"), max_property_description)
        compacted.append(item)
    return compacted


def _shorten_tool_message(message, limit):
    """Shorten the 'output' of a tool message (a JSON string) to ``limit`` chars."""
    content = message.get("content")
    if not isinstance(content, str):
        return message
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        output = data.get("output")
        if isinstance(output, str) and len(output) > limit:
            data["output"] = _cut(output, limit)
        data.pop("verification_evidence", None)
        shortened = dict(message)
        shortened["content"] = json.dumps(data, ensure_ascii=False, default=str)
        return shortened
    shortened = dict(message)
    shortened["content"] = _cut(content, limit)
    return shortened


def _round_groups(messages, first, last):
    """Yield (start, end) index ranges of assistant tool-call + tool-result groups."""
    index = first
    while index < last:
        message = messages[index]
        if isinstance(message, dict) and message.get("role") == "assistant" and message.get("tool_calls"):
            end = index + 1
            while end < last and isinstance(messages[end], dict) and messages[end].get("role") == "tool":
                end += 1
            yield index, end
            index = end
        else:
            index += 1


def fit_messages(messages, *, budget_tokens, fixed_tokens=0, protect_index=None):
    """Return a copy of ``messages`` that fits the budget. Never mutates the input.

    ``protect_index`` is the user's request: it is never dropped, and only its
    trailing SESSION CONTEXT block may be shortened.
    """
    work = [dict(m) if isinstance(m, dict) else m for m in messages]
    allowance = max(MIN_ALLOWANCE_TOKENS, int(budget_tokens) - int(fixed_tokens) - OUTPUT_RESERVE_TOKENS)

    def total():
        return sum(message_tokens(m) for m in work)

    if total() <= allowance:
        return work

    last_assistant = max(
        (i for i, m in enumerate(work) if isinstance(m, dict) and m.get("role") == "assistant"),
        default=-1,
    )
    # 1. Replayed thinking of earlier turns is the cheapest thing to lose.
    for i, message in enumerate(work):
        if isinstance(message, dict) and message.get("role") == "assistant" and i != last_assistant:
            message.pop("thinking", None)
    if total() <= allowance:
        return work

    latest_round_start = max(
        (i for i, m in enumerate(work) if isinstance(m, dict) and m.get("role") == "assistant" and m.get("tool_calls")),
        default=-1,
    )
    # 2. Results of earlier rounds shrink to a short head.
    for i, message in enumerate(work):
        if isinstance(message, dict) and message.get("role") == "tool" and i < latest_round_start:
            work[i] = _shorten_tool_message(message, OLD_RESULT_CHARS)
    if total() <= allowance:
        return work

    # 3. Results of the latest round share whatever room is left.
    latest = [
        i for i, m in enumerate(work)
        if isinstance(m, dict) and m.get("role") == "tool" and i > latest_round_start >= 0
    ]
    if latest:
        others = total() - sum(message_tokens(work[i]) for i in latest)
        room_chars = max(0, allowance - others) * CHARS_PER_TOKEN
        per_message = max(MIN_LATEST_RESULT_CHARS, room_chars // len(latest))
        for i in latest:
            work[i] = _shorten_tool_message(work[i], per_message)
    if total() <= allowance:
        return work

    # 4. Shorten the reference block that follows the user's request.
    if protect_index is not None and 0 <= protect_index < len(work) and isinstance(work[protect_index], dict):
        prompt = work[protect_index].get("content")
        if isinstance(prompt, str) and SESSION_MARKER in prompt:
            head, _, tail = prompt.partition(SESSION_MARKER)
            for keep in (2500, 1200, 500, 0):
                work[protect_index]["content"] = head + (SESSION_MARKER + _cut(tail, keep) if keep else "")
                if total() <= allowance:
                    return work

    # 5. Drop whole earlier rounds, oldest first.
    first = (protect_index + 1) if protect_index is not None else 0
    while total() > allowance:
        groups = list(_round_groups(work, first, max(first, latest_round_start)))
        if not groups:
            break
        start, end = groups[0]
        del work[start:end]
        latest_round_start -= end - start

    # 6. Drop earlier conversation history, oldest first (never the request).
    if protect_index is not None:
        while total() > allowance and protect_index > 0:
            del work[0]
            protect_index -= 1
    return work
