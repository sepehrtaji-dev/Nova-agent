"""What the user actually asked for, and whether the tool loop has done it.

A model that stops calling tools has not necessarily finished: a request like
"search the web and write a README" has two deliverables, and a small model
will happily stop after the first one. Goals are inferred deterministically
from the request, ticked off only by tool calls that really succeeded, and
used by the loop to refuse an answer that skips a deliverable.
"""
from __future__ import annotations

import re

_VERB = r"(?:write|create|make|save|generate|produce|draft|export|put|store|output)"
# A file noun must be (nearly) the object of the verb, otherwise "write a
# python function that reads a file" would demand a file be written.
_GAP = r"(?:[\w'\-./]+\s+){0,4}?"
_FILE_OBJECT = re.compile(rf"\b{_VERB}\b\s+{_GAP}(?:files?|readme(?:\.md)?|read\s?me)\b")
_FILE_NAME = re.compile(
    rf"\b{_VERB}\b\s+(?:[\w'\-./]+\s+){{0,6}}?[\w\-]+\.(?:md|txt|json|csv|html?|py|js|ts|ya?ml|toml|ini|cfg|log|c|cpp|h|java|rs|go|sh|docx?|pdf)\b"
)
_NEGATED = re.compile(r"\b(?:don'?t|do not|without|never|no need to|not)\b[^.!?\n]{0,30}\b(?:write|create|save|make|generate)\b")
_WEB = re.compile(
    r"\b(?:search|google|look\s?up|research|browse|find out|look for)\b[^.!?\n]{0,40}\b(?:web|internet|online|net|google)\b"
)


class Goal:
    def __init__(self, key, description, tools, hint):
        self.key = key
        self.description = description
        self.tools = frozenset(tools)
        self.hint = hint
        self.satisfied = False


def infer_goals(message, allowed_tools):
    text = " ".join(str(message or "").casefold().split())
    allowed = set(allowed_tools or ())
    goals = []
    if "web_search" in allowed and _WEB.search(text):
        goals.append(Goal(
            "research", "searched the web as asked", {"web_search"},
            "Call web_search with a short keyword query.",
        ))
    wants_file = bool(_FILE_OBJECT.search(text) or _FILE_NAME.search(text)) and not _NEGATED.search(text)
    writers = {"write_file", "edit_file"} & allowed
    if wants_file and writers:
        goals.append(Goal(
            "file", "written the requested file", writers,
            "Call write_file now with a suitable path (for example README.md) and the "
            "COMPLETE document in 'content', written from the information you gathered. "
            "Do not paste the document into your reply instead.",
        ))
    return goals


def unmet_goals(goals):
    return [goal for goal in goals or [] if not goal.satisfied]


def record_goal_result(goals, tool_name):
    """Mark goals satisfied by a tool call that succeeded."""
    for goal in goals or []:
        if tool_name in goal.tools:
            goal.satisfied = True


def describe_unmet(goals):
    return "; ".join(f"you have not {goal.description}" for goal in goals)


def goal_tools(goals):
    tools = set()
    for goal in goals or []:
        tools |= set(goal.tools)
    return tools
