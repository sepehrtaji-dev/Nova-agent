"""Human-readable activity labels for Nova's live status line.

While Nova works, the desktop UI shows a tiny status chip ("Searching the
web…", "Reading the file…", "Writing…") so the user can always tell what
the model is doing. Tool execution publishes ``ACTIVITY:<phrase>`` events
through the regular status channel; the UI strips the prefix and renders
the phrase, the TUI does the same for its activity trace.
"""
from __future__ import annotations

# Exact matches for every tool in the registry manifest (config/tools.json).
TOOL_ACTIVITIES = {
    "web_search": "Searching the web",
    "read_file": "Reading the file",
    "write_file": "Writing the file",
    "edit_file": "Editing the file",
    "find_files": "Finding files",
    "list_files": "Listing files",
    "terminal": "Running the command",
    "git": "Working with git",
    "github": "Asking GitHub",
    "noviqx_github_get_file": "Reading from GitHub",
    "noviqx_github_update_file": "Updating GitHub file",
    "desktop": "Controlling the desktop",
}

# Fallback prefixes for tools registered outside the manifest default set
# (custom registries, plugins) whose names still hint at their purpose.
PREFIX_ACTIVITIES = (
    ("web_search", "Searching the web"),
    ("github", "Asking GitHub"),
    ("git_", "Working with git"),
    ("web_", "Searching the web"),
    ("file", "Working with files"),
)

ACTIVITY_PREFIX = "ACTIVITY:"

# Shared phase labels: every loop waits on the model (thinking) before the
# final answer streams out (writing). Tool calls publish their own phrases.
THINKING_ACTIVITY = ACTIVITY_PREFIX + "Thinking"
WRITING_ACTIVITY = ACTIVITY_PREFIX + "Writing"


def format_activity(name):
    """Return the ``ACTIVITY:<phrase>`` wire event for a tool call."""
    return ACTIVITY_PREFIX + activity_for(name)


def activity_for(name):
    """Return a short human phrase describing what running ``name`` does."""
    if not isinstance(name, str) or not name.strip():
        return "Working"
    name = name.strip()
    exact = TOOL_ACTIVITIES.get(name)
    if exact:
        return exact
    lowered = name.lower()
    for prefix, phrase in PREFIX_ACTIVITIES:
        if lowered.startswith(prefix):
            return phrase
    return f"Using {name}"
