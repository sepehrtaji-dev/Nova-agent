"""Persisted NoviqX GitHub App credentials and wizard state.

Stores only references that identify the user's own App:
- App ID (numeric, public on GitHub)
- Installation ID (numeric, visible to anyone with access to the installation)
- Absolute path to the .pem on THIS machine

The .pem content itself is NEVER written here, never logged, never displayed.
The settings file is chmod 600 (owner-only) where the platform supports it.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

SETTINGS_ENV = "NOVA_NOVIQX_FILE"

DEFAULT_NOVIQX = {
    "app_id": "",
    "installation_id": "",
    "private_key_path": "",
    # Wizard UX state
    "setup_dismissed": False,   # user clicked "Never ask again"
    "setup_completed": False,   # user finished the wizard successfully
}

# Keys whose values are public identity references (safe to log/display).
_PUBLIC_KEYS = {"app_id", "installation_id"}
# Keys whose values are local filesystem paths — never displayed in full.
_PROTECTED_KEYS = {"private_key_path"}


def settings_path() -> Path:
    """Where the NoviqX settings live. Honors NOVA_HOME like the core settings."""
    configured = os.getenv(SETTINGS_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    home = Path(os.getenv("NOVA_HOME", Path.home() / ".nova"))
    return home / "noviqx.json"


def load_settings() -> dict:
    """Return stored settings merged over defaults. Never raises."""
    values = dict(DEFAULT_NOVIQX)
    path = settings_path()
    try:
        with path.open("r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            for key in DEFAULT_NOVIQX:
                if key in stored:
                    value = stored[key]
                    if key in {"setup_dismissed", "setup_completed"}:
                        values[key] = bool(value)
                    else:
                        values[key] = str(value or "").strip()
    except (OSError, json.JSONDecodeError):
        pass
    return values


def save_settings(updates: dict) -> tuple[bool, str]:
    """Merge `updates` into the on-disk settings and persist atomically.

    Only known keys are persisted; unknown keys are dropped to prevent
    accidental writes of secrets via this API. Returns (ok, message).
    """
    if not isinstance(updates, dict):
        return False, "updates must be a mapping"

    merged = load_settings()
    for key in DEFAULT_NOVIQX:
        if key not in updates:
            continue
        value = updates[key]
        if key in {"setup_dismissed", "setup_completed"}:
            merged[key] = bool(value)
        else:
            merged[key] = str(value or "").strip()

    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(merged, handle, indent=2)
            handle.write("\n")
        os.replace(temp, path)
        _restrict(path)
        return True, f"Saved to {path}"
    except OSError as exc:
        return False, f"Could not save NoviqX settings: {exc}"


def is_configured(settings: dict | None = None) -> bool:
    """True if App ID, Installation ID, and a readable .pem path are present.

    This is a fast check; it does not contact GitHub. Use it to decide whether
    to show the setup wizard or the "open NoviqX settings" action.
    """
    s = settings if isinstance(settings, dict) else load_settings()
    app_id = str(s.get("app_id", "")).strip()
    installation_id = str(s.get("installation_id", "")).strip()
    key_path = str(s.get("private_key_path", "")).strip()
    if not (app_id.isdigit() and installation_id.isdigit() and key_path):
        return False
    # Confirm the .pem actually exists — a stale path is the same as unconfigured
    # for the user's purposes. We do NOT read the file here.
    try:
        return Path(key_path).expanduser().is_file()
    except (OSError, ValueError):
        return False


def should_show_wizard(settings: dict | None = None) -> bool:
    """Show the wizard when NoviqX is not configured AND not permanently dismissed."""
    s = settings if isinstance(settings, dict) else load_settings()
    if bool(s.get("setup_dismissed")):
        return False
    return not is_configured(s)


def masked_display(settings: dict | None = None) -> dict:
    """User-facing display of the configured state — no secrets, no full paths."""
    s = settings if isinstance(settings, dict) else load_settings()
    key_path = str(s.get("private_key_path", "") or "").strip()
    if key_path:
        # Show only the filename, not the directory structure.
        displayed_path = "…" + "/" + Path(key_path).name if Path(key_path).name else "(set)"
    else:
        displayed_path = "(not set)"
    return {
        "app_id": str(s.get("app_id", "") or "(not set)"),
        "installation_id": str(s.get("installation_id", "") or "(not set)"),
        "private_key_path": displayed_path,
        "setup_completed": bool(s.get("setup_completed", False)),
    }


def _restrict(path: Path) -> None:
    """Best-effort owner-only permissions; a no-op where unsupported."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
