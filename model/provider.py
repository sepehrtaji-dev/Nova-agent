"""Choose Nova's model backend: local Ollama, or a remote OpenAI-compatible API.

Selection is configuration-driven so nothing else in the codebase needs to know
which backend is active:

    NOVA_PROVIDER=local   (default)  -> OllamaBrain
    NOVA_PROVIDER=remote            -> OpenAICompatibleBrain
    NOVA_PROVIDER=auto              -> remote when fully configured, else local

A remote fallback back to local is deliberately NOT automatic. Silently
answering from a different model than the user configured would hide both the
provider outage and the fact that their prompts stopped leaving the machine.
"""
from __future__ import annotations

import os

from model.ollama import OllamaBrain
from model.remote import OpenAICompatibleBrain, RemoteBrainError

VALID_PROVIDERS = ("local", "remote", "auto")


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def requested_provider():
    provider = os.getenv("NOVA_PROVIDER", "local").strip().lower()
    return provider if provider in VALID_PROVIDERS else "local"


def remote_is_configured():
    """True when enough is set to attempt a remote call."""
    return bool(
        os.getenv("NOVA_API_KEY", "").strip()
        and os.getenv("NOVA_API_MODEL", "").strip()
    )


def build_brain(model=None):
    """Return the configured brain instance.

    Raises RuntimeError when remote mode was explicitly requested but is not
    configured, rather than quietly falling back to a local model.
    """
    provider = requested_provider()

    if provider == "remote" or (provider == "auto" and remote_is_configured()):
        brain = OpenAICompatibleBrain(model=model)
        if not brain.is_configured():
            raise RuntimeError(
                "NOVA_PROVIDER is set to 'remote' but the remote provider is not "
                "configured. " + brain.configuration_help()
            )
        return brain

    return OllamaBrain(model=model)


def describe_brain(brain):
    """One-line, honest description of the active backend for the user."""
    if isinstance(brain, OpenAICompatibleBrain):
        return brain.describe()
    model = getattr(brain, "model", "") or "unknown"
    return (
        f"local model '{model}' via Ollama (runs on this computer; nothing is "
        "sent to a remote provider)"
    )


def backend_kind(brain):
    return "remote" if isinstance(brain, OpenAICompatibleBrain) else "local"
