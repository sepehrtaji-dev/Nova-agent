"""Persisted model-backend settings for the Nova desktop app.

The desktop app lets the user pick a local Ollama model or enter an API key,
base URL, and model for a remote provider. Those choices are stored here so they
survive a restart, and are applied to the environment the rest of Nova already
reads (NOVA_PROVIDER, NOVA_API_*), so no other module needs to change.

The API key is stored in a separate file with restrictive permissions where the
platform supports it. It is never written to logs and never displayed in full.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

SETTINGS_ENV = "NOVA_SETTINGS_FILE"

DEFAULT_SETTINGS = {
    "provider": "local",          # local | remote
    "local_model": "",
    "api_base_url": "https://api.openai.com/v1",
    "api_model": "",
    "api_key": "",
}


def settings_path() -> Path:
    configured = os.getenv(SETTINGS_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    home = Path(os.getenv("NOVA_HOME", Path.home() / ".nova"))
    return home / "settings.json"


def load_settings() -> dict:
    """Return stored settings merged over the defaults. Never raises."""
    values = dict(DEFAULT_SETTINGS)
    path = settings_path()
    try:
        with path.open("r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            for key in DEFAULT_SETTINGS:
                if key in stored and isinstance(stored[key], str):
                    values[key] = stored[key]
    except (OSError, json.JSONDecodeError):
        pass
    return values


def save_settings(settings: dict) -> tuple[bool, str]:
    """Persist settings. Returns (ok, message). Never raises."""
    if not isinstance(settings, dict):
        return False, "settings must be a mapping"

    merged = dict(DEFAULT_SETTINGS)
    for key in DEFAULT_SETTINGS:
        value = settings.get(key, merged[key])
        merged[key] = str(value) if value is not None else ""

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
        return False, f"Could not save settings: {exc}"


def _restrict(path: Path):
    """Best-effort owner-only permissions; a no-op where unsupported."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def masked_key(key: str) -> str:
    """Short, non-reversible display form of an API key."""
    key = str(key or "")
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def apply_to_environment(settings: dict) -> dict:
    """Copy stored settings into the NOVA_* environment variables.

    Nova's provider layer reads these variables, so applying them here lets the
    desktop app switch backends without any change to the agent code.
    Returns the variables that were set.
    """
    if not isinstance(settings, dict):
        return {}

    provider = str(settings.get("provider", "local")).strip().lower()
    if provider not in {"local", "remote"}:
        provider = "local"

    applied = {"NOVA_PROVIDER": provider}

    api_model = str(settings.get("api_model", "")).strip()
    base_url = str(settings.get("api_base_url", "")).strip()
    api_key = str(settings.get("api_key", "")).strip()

    if provider == "remote":
        if api_model:
            applied["NOVA_API_MODEL"] = api_model
        if base_url:
            applied["NOVA_API_BASE_URL"] = base_url
        if api_key:
            applied["NOVA_API_KEY"] = api_key

    local_model = str(settings.get("local_model", "")).strip()
    if provider == "local" and local_model:
        applied["NOVA_MODEL"] = local_model

    for name, value in applied.items():
        os.environ[name] = value

    # A stale key from a previous remote session must not linger once the user
    # switches back to local, or content could leave the machine unexpectedly.
    if provider == "local":
        for name in ("NOVA_API_KEY", "NOVA_API_MODEL", "NOVA_API_BASE_URL"):
            os.environ.pop(name, None)

    return applied


def remote_ready(settings: dict) -> bool:
    return bool(
        str(settings.get("provider", "")).strip().lower() == "remote"
        and str(settings.get("api_model", "")).strip()
        and str(settings.get("api_key", "")).strip()
    )


def summarise(settings: dict) -> str:
    """One-line, honest description of the configured backend for display."""
    if remote_ready(settings):
        host = str(settings.get("api_base_url", "")).split("//")[-1].split("/")[0]
        return (
            f"Remote model '{settings.get('api_model')}' via {host or 'remote'} "
            "\u2014 prompts and tool results are sent to that provider."
        )
    if str(settings.get("provider", "")).strip().lower() == "remote":
        return "Remote selected but incomplete \u2014 a model and API key are required."
    model = str(settings.get("local_model", "")).strip() or "auto-detected model"
    return f"Local Ollama model '{model}' \u2014 nothing leaves this computer."
