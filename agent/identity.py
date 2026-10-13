"""Nova's identity and capability facts, in one place.

These are declarations about the *product*, not observations about the running
process. Anything that can be measured at runtime (registered tools, model
metadata, network reachability) must be probed rather than asserted here, so a
stale string can never be reported as a live fact.
"""
from __future__ import annotations

import os

# --- Product identity -------------------------------------------------------
# Overridable by environment so a fork can rebrand without editing source.
NOVA_NAME = os.getenv("NOVA_NAME", "Nova")
NOVA_VERSION = os.getenv("NOVA_VERSION", "1.3")
NOVA_DEVELOPER = os.getenv("NOVA_DEVELOPER", "Taji-Soft team")
NOVA_REPOSITORY = os.getenv(
    "NOVA_REPOSITORY", "https://github.com/sepehrtaji-dev/Nova-agent"
)
NOVA_LICENSE = os.getenv("NOVA_LICENSE", "open source")
NOVA_KIND = os.getenv(
    "NOVA_KIND", "a local AI agent that runs on the developer's own machine"
)
NOVA_PARAMETER_COUNT = os.getenv("NOVA_PARAMETER_COUNT", "3 billion")
NOVA_PARAMETER_SOURCE = os.getenv(
    "NOVA_PARAMETER_SOURCE",
    "the default bundled model (qwen2.5:3b); the active model is always reported "
    "from live Ollama metadata instead",
)

# Capabilities Nova claims. Descriptions stay short; the live tool registry is
# the authority on what is actually enabled in this run.
NOVA_CAPABILITIES = (
    ("search", "search the public web and cite real sources"),
    ("code", "write, read, and edit code and run it in the workspace"),
    ("math", "solve math and arithmetic questions"),
)


def identity_lines() -> list[str]:
    """Canonical, prose-free identity facts for prompts and answers."""
    return [
        f"Name: {NOVA_NAME} {NOVA_VERSION}",
        f"Developer: {NOVA_DEVELOPER}",
        f"Project: {NOVA_KIND}",
        f"Repository: {NOVA_REPOSITORY} ({NOVA_LICENSE})",
        f"Default model size: {NOVA_PARAMETER_COUNT} parameters "
        f"({NOVA_PARAMETER_SOURCE})",
        "Capabilities: " + "; ".join(
            f"{name} — {detail}" for name, detail in NOVA_CAPABILITIES
        ),
    ]


def identity_sentence() -> str:
    return (
        f"I'm {NOVA_NAME} {NOVA_VERSION}, {NOVA_KIND}, developed by "
        f"{NOVA_DEVELOPER}. I'm open source: {NOVA_REPOSITORY}. "
        f"I can search the web, write and run code, and solve math questions. "
        f"I run locally, and the default model is {NOVA_PARAMETER_COUNT} "
        f"parameters."
    )
