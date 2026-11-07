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
    "effort": "medium",
    "assistant_font_size": "16",
    "remote_models": "[]",
    "active_remote_model_id": "",
    "model_instructions": "",
    "profile_name": "",
    "profile_age": "",
    "profile_occupation": "",
    "profile_avatar": "",
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
    """Apply the selected local or saved remote profile to Nova's runtime."""
    if not isinstance(settings, dict):
        return {}
    provider = str(settings.get("provider", "local")).strip().lower()
    if provider not in {"local", "remote"}:
        provider = "local"
    applied = {"NOVA_PROVIDER": provider}
    effort = str(settings.get("effort", "medium")).strip().lower()
    if effort not in {"off", "low", "medium", "high", "max", "novacode"}:
        effort = "medium"
    applied["NOVA_EFFORT"] = effort
    try:
        profiles = json.loads(settings.get("remote_models", "[]") or "[]")
        if not isinstance(profiles, list):
            profiles = []
    except (TypeError, json.JSONDecodeError):
        profiles = []
    selected_id = str(settings.get("active_remote_model_id", "") or "")
    profile = next((item for item in profiles if isinstance(item, dict)
                    and str(item.get("id", "")) == selected_id), None)
    if provider == "remote":
        api_provider = str((profile or {}).get("provider", "openai")).strip().lower()
        if api_provider not in {"openai", "anthropic"}:
            api_provider = "openai"
        values = {
            "NOVA_API_PROVIDER": api_provider,
            "NOVA_API_MODEL": str((profile or {}).get("model") or settings.get("api_model", "")).strip(),
            "NOVA_API_BASE_URL": str((profile or {}).get("base_url") or settings.get("api_base_url", "")).strip(),
            "NOVA_API_KEY": str((profile or {}).get("api_key") or settings.get("api_key", "")).strip(),
        }
        applied.update({key: value for key, value in values.items() if value})
    local_model = str(settings.get("local_model", "")).strip()
    if provider == "local" and local_model:
        applied["NOVA_MODEL"] = local_model
    for name, value in applied.items():
        os.environ[name] = value
    if provider == "local":
        for name in ("NOVA_API_KEY", "NOVA_API_MODEL", "NOVA_API_BASE_URL", "NOVA_API_PROVIDER"):
            os.environ.pop(name, None)
    os.environ["NOVA_MODEL_INSTRUCTIONS"] = str(settings.get("model_instructions", "") or "")
    profile_lines = []
    for key, label in (("profile_name", "User name"), ("profile_age", "User age"),
                       ("profile_occupation", "User occupation")):
        value = str(settings.get(key, "") or "").strip()
        if value:
            profile_lines.append(f"{label}: {value}")
    os.environ["NOVA_USER_PROFILE"] = "\n".join(profile_lines)
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
