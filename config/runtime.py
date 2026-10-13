"""Runtime configuration helpers backed by the declarative tool manifest."""
import json
import os
from pathlib import Path


def manifest_path():
    configured = os.getenv("NOVA_TOOL_MANIFEST", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent / "tools.json"


def load_default_access():
    try:
        with manifest_path().open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    access = manifest.get("default_access", {}) if isinstance(manifest, dict) else {}
    if not isinstance(access, dict):
        return {}
    return {
        str(name): bool(enabled)
        for name, enabled in access.items()
        if isinstance(name, str)
    }
