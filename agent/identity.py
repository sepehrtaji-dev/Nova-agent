"""Nova's product identity.

This module holds only facts that are true regardless of how Nova is running:
the name, who develops it, where the source lives. Everything that changes with
the runtime -- which model is answering, whether it runs locally or remotely, how
many parameters it has, which tools are enabled -- is deliberately NOT here. It
is derived at answer time from live state (see agent.capability_probe and
agent.tool_awareness).

That separation exists because hardcoding runtime claims has repeatedly made Nova
describe itself incorrectly: it asserted Anthropic's authorship, reported
"Ollama metadata" while running on a remote API, and stated "3 billion
parameters" for models that had nothing of the sort. A static string can only be
trusted for static facts.
"""
from __future__ import annotations

import os

# --- Static product facts ---------------------------------------------------
# Overridable by environment so a fork can rebrand without editing source.
NOVA_NAME = os.getenv("NOVA_NAME", "Nova")
NOVA_VERSION = os.getenv("NOVA_VERSION", "1.3")
NOVA_DEVELOPER = os.getenv("NOVA_DEVELOPER", "Taji-Soft team")
NOVA_REPOSITORY = os.getenv(
    "NOVA_REPOSITORY", "https://github.com/sepehrtaji-dev/Nova-agent"
)
NOVA_LICENSE = os.getenv("NOVA_LICENSE", "open source")

# What Nova can do when the corresponding tools are enabled. Phrased as
# capabilities, not as promises: the live registry decides what is actually
# unavailable in any given run.
NOVA_CAPABILITIES = (
    ("search", "search the public web and cite real sources"),
    ("code", "write, read, and edit code and run it in the workspace"),
    ("math", "solve math and arithmetic questions"),
)


def identity_lines() -> list[str]:
    """Static, prose-free identity facts safe to put in any prompt."""
    return [
        f"Name: {NOVA_NAME} {NOVA_VERSION}",
        f"Developer: {NOVA_DEVELOPER}",
        f"Source: {NOVA_REPOSITORY} ({NOVA_LICENSE})",
        "Capabilities when the matching tools are enabled: " + "; ".join(
            f"{name} — {detail}" for name, detail in NOVA_CAPABILITIES
        ),
    ]


def identity_sentence() -> str:
    """Static identity sentence. Contains no runtime claims."""
    return (
        f"I'm {NOVA_NAME} {NOVA_VERSION}, developed by {NOVA_DEVELOPER}. "
        f"I'm open source: {NOVA_REPOSITORY}. "
        "I can search the web, write and run code, and solve math questions "
        "when those tools are enabled."
    )
