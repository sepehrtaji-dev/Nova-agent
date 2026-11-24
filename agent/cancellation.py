"""Cooperative cancellation shared by the UI, agent loop, and providers."""
from __future__ import annotations


class GenerationCancelled(Exception):
    """Raised when the user asks Nova to stop the active generation."""


def raise_if_cancelled(event):
    if event is not None and event.is_set():
        raise GenerationCancelled("Generation stopped by user.")
