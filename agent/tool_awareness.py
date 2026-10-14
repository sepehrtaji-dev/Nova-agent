"""Registry-driven tool awareness.

Everything here is derived from the live tool registry. No tool name, count, or
capability is hardcoded: adding, removing, renaming, or disabling a tool in
config/tools.json changes what the model is told, automatically.

This exists because the model previously described its own tools incorrectly
(claiming it had no way to read a file while read_file was enabled). The fix is
to render the registry into the prompt on every generation rather than relying
on the model's memory of a list it saw once.
"""
from __future__ import annotations

import inspect


def _field(metadata, key, default=None):
    if isinstance(metadata, dict):
        return metadata.get(key, default)
    return getattr(metadata, key, default)


def _schema_summary(metadata):
    """Human-readable argument summary derived from the declared JSON schema."""
    schema = _field(metadata, "input_schema")
    if not isinstance(schema, dict):
        return ""

    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return ""

    required = schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()

    parts = []
    for name, definition in properties.items():
        definition = definition if isinstance(definition, dict) else {}
        kind = definition.get("type", "any")
        allowed = definition.get("enum")
        if isinstance(allowed, list) and allowed:
            shown = "|".join(str(item) for item in allowed[:6])
            kind = f"{kind}: {shown}"
        marker = "" if name in required_names else "?"
        parts.append(f"{name}{marker}:{kind}")
    return ", ".join(parts)


def tool_entries(core):
    """Live tool records for the current core instance, sorted by name."""
    registry = getattr(getattr(core, "tools", None), "tools", None)
    if not isinstance(registry, dict):
        return []

    access = getattr(core, "access", None)
    access = access if isinstance(access, dict) else {}

    entries = []
    for name, raw in sorted(registry.items(), key=lambda item: str(item[0])):
        metadata = raw if isinstance(raw, dict) else {}
        capability = _field(metadata, "capability")
        # A tool is usable only when its capability is switched on. A tool with
        # no declared capability is always usable, matching _allowed_tools().
        enabled = bool(access.get(capability, False)) if capability else True
        entries.append({
            "name": str(name),
            "description": str(_field(metadata, "description", "") or "").strip(),
            "capability": str(capability) if capability else "",
            "enabled": enabled,
            "arguments": _schema_summary(metadata),
            "returns": _returns_summary(metadata),
        })
    return entries


def _returns_summary(metadata):
    """First line of the handler's own docstring, if it documents its output."""
    function = _field(metadata, "function")
    if not callable(function):
        return ""
    doc = inspect.getdoc(function)
    if not doc:
        return ""
    first = doc.strip().splitlines()[0].strip()
    return first if first.lower().startswith(("input", "returns", "output")) else ""


def render_tools(core, include_disabled=True):
    """Registry-derived tool listing for prompts. Never hardcodes tool names."""
    entries = tool_entries(core)
    if not entries:
        return "No tools are registered in this instance."

    enabled = [entry for entry in entries if entry["enabled"]]
    disabled = [entry for entry in entries if not entry["enabled"]]

    lines = []
    if enabled:
        lines.append("TOOLS YOU CAN USE RIGHT NOW:")
        for entry in enabled:
            line = f"- {entry['name']}"
            if entry["arguments"]:
                line += f"({entry['arguments']})"
            if entry["description"]:
                line += f": {entry['description']}"
            lines.append(line)
    else:
        lines.append("TOOLS YOU CAN USE RIGHT NOW: none. No tool is currently "
                     "enabled, so do not claim you can perform tool actions.")

    if include_disabled and disabled:
        lines.append("")
        lines.append("REGISTERED BUT DISABLED BY PERMISSION (you cannot use "
                     "these until enabled):")
        for entry in disabled:
            line = f"- {entry['name']}"
            if entry["capability"]:
                line += f" (capability: {entry['capability']})"
            lines.append(line)

    return "\n".join(lines)


def render_memory(core):
    """Compact tool facts the model should carry into every turn."""
    entries = tool_entries(core)
    if not entries:
        return "No tools are registered."

    enabled_names = [entry["name"] for entry in entries if entry["enabled"]]
    disabled_names = [entry["name"] for entry in entries if not entry["enabled"]]

    lines = [
        f"You currently have {len(enabled_names)} usable tool(s): "
        f"{', '.join(enabled_names) if enabled_names else 'none'}.",
    ]
    if disabled_names:
        lines.append(
            "These tools exist but are switched off by permission, so you cannot "
            f"call them: {', '.join(disabled_names)}."
        )
    lines.append(
        "This list is generated live from the running registry. Trust it over "
        "any assumption: never say you lack a tool that appears above, and "
        "never claim a tool that is absent or disabled."
    )
    return " ".join(lines)


def render_workspace(core):
    """Describe the real workspace roots so paths are never guessed.

    The model otherwise invents a plausible absolute path (the source tree it
    was told about) and passes location='system', writing outside the intended
    workspace. Printing the resolved roots removes the guesswork.
    """
    lines = []
    try:
        import os

        root = os.path.abspath(os.getcwd())
        lines.append(f"Current working directory: {root}")
        lines.append(f"Default projects folder: {os.path.join(root, 'projects')}")
        lines.append(
            "When a task refers to 'the projects folder' or 'the workspace', use "
            "location='projects' with a path relative to that folder "
            "(for example path='todo.txt'). Do not build an absolute path "
            "yourself and do not use location='system' unless the user gave you "
            "an absolute path outside the workspace."
        )
    except Exception:
        return "Workspace roots are unavailable."
    return "\n".join(lines)


def render_platform():
    """Tell the model which shell utilities exist, so it stops guessing POSIX ones."""
    import os

    if os.name == "nt":
        return (
            "Operating system: Windows. There is no touch, grep, cat, ls, rm, "
            "cp, mv, sed, or awk. Prefer the file tools over shell commands for "
            "creating, reading, and listing files. If you must run a program, "
            "use one that exists on Windows (python, git, pip, dir is a shell "
            "builtin and cannot be run directly)."
        )
    return (
        "Operating system: POSIX. Standard shell utilities may exist, but prefer "
        "the file tools for creating, reading, and listing files."
    )


def render_for_prompt(core):
    """Full tool awareness block for prompts: listing plus memory statement."""
    return (
        render_tools(core)
        + "\n\n"
        + render_memory(core)
        + "\n\n"
        + render_workspace(core)
        + "\n\n"
        + render_platform()
    )
