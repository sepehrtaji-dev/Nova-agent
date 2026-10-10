"""Evidence-based runtime profile for Nova's terminal UI.

This module reports only observable configuration and metadata returned by the
local runtime. Missing metadata stays unknown; model names are never used to
guess parameter counts or architecture.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


def _field(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _first(mapping, *keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _env_int(name, default, minimum):
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _format_parameter_count(value):
    if value in (None, ""):
        return "Unknown"
    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.2f}B ({count:,})"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.2f}M ({count:,})"
    return f"{count:,}"


def inspect_model(core, show_model=None):
    """Probe Ollama show metadata on demand; never infer from the model tag."""
    brain = getattr(core, "brain", None)
    model_name = str(getattr(brain, "model", "") or "").strip()
    result = {
        "configured_name": model_name or "Unknown",
        "status": "not_checked",
        "parameter_count": "Unknown",
        "parameter_count_raw": None,
        "parameter_size": "Unknown",
        "architecture": "Unknown",
        "quantization": "Unknown",
        "model_context_length": "Unknown",
        "capabilities": [],
        "metadata_fields": [],
        "detail": "Model metadata has not been queried.",
    }
    if not model_name:
        result.update(status="not_configured", detail="No model name is configured.")
        return result

    try:
        if show_model is None:
            import ollama
            show_model = ollama.show
        response = show_model(model_name)
    except Exception as exc:
        result.update(
            status="unreachable",
            detail=f"Ollama model metadata request failed ({type(exc).__name__}).",
        )
        return result

    model_info = _field(response, "model_info", {}) or {}
    details = _field(response, "details", {}) or {}
    if not isinstance(model_info, dict):
        try:
            model_info = dict(model_info)
        except (TypeError, ValueError):
            model_info = {}
    if not isinstance(details, dict):
        try:
            details = dict(details)
        except (TypeError, ValueError):
            details = {}

    parameter_count = _first(
        model_info,
        "general.parameter_count",
        "parameter_count",
    )
    if parameter_count is None:
        parameter_count = next(
            (value for key, value in model_info.items()
             if str(key).endswith(".parameter_count") and value not in (None, "")),
            None,
        )

    architecture = _first(model_info, "general.architecture", "architecture")
    context_length = _first(model_info, "context_length")
    if context_length is None and architecture:
        context_length = _first(model_info, f"{architecture}.context_length")
    if context_length is None:
        context_length = next(
            (value for key, value in model_info.items()
             if str(key).endswith(".context_length") and value not in (None, "")),
            None,
        )

    quantization = _first(details, "quantization_level", "quantization")
    parameter_size = _first(details, "parameter_size")
    capabilities = _field(response, "capabilities", []) or []
    if isinstance(capabilities, str):
        capabilities = [capabilities]

    result.update(
        status="available",
        parameter_count=_format_parameter_count(parameter_count),
        parameter_count_raw=parameter_count,
        parameter_size=str(parameter_size) if parameter_size else "Unknown",
        architecture=str(architecture) if architecture else "Unknown",
        quantization=str(quantization) if quantization else "Unknown",
        model_context_length=str(context_length) if context_length else "Unknown",
        capabilities=[str(item) for item in capabilities],
        metadata_fields=sorted(str(key) for key in model_info.keys()),
        detail="Ollama returned metadata for the configured model; this does not prove generation works.",
    )
    return result


def runtime_profile(core):
    """Return a low-risk local snapshot without making network/model requests."""
    brain = getattr(core, "brain", None)
    registry = getattr(core, "tools", None)
    registered = getattr(registry, "tools", {}) or {}
    if not isinstance(registered, dict):
        registered = {}

    access = getattr(core, "access", {}) or {}
    tools = []
    for name, raw in sorted(registered.items()):
        data = raw if isinstance(raw, dict) else {}
        capability = str(data.get("capability", "pc"))
        tools.append({
            "name": str(name),
            "description": str(data.get("description", "")).strip(),
            "capability": capability,
            "enabled": bool(access.get(capability, True)),
        })

    component_names = (
        ("brain", "Ollama model adapter"),
        ("router", "Tool router"),
        ("planner", "Task planner"),
        ("verifier", "Tool-result verifier"),
        ("self_knowledge", "Self-knowledge"),
        ("diagnostics", "Runtime diagnostics"),
        ("extractor", "Memory extractor"),
        ("long_memory", "Long-term memory manager"),
        ("short_memory", "Short-term memory"),
        ("knowledge", "Knowledge memory"),
        ("episodic_memory", "Episodic memory"),
    )
    components = []
    for attr, label in component_names:
        value = getattr(core, attr, None)
        components.append({
            "name": attr,
            "label": label,
            "present": value is not None,
            "implementation": type(value).__name__ if value is not None else "Missing",
        })

    return {
        "identity": "Nova",
        "developer": "Taji-Soft",
        "version": os.getenv("NOVA_VERSION", "Unknown"),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "system": sys.platform,
        "working_directory": str(Path.cwd()),
        "entrypoint": "main.py",
        "provider": "Ollama",
        "configured_model": str(getattr(brain, "model", "") or "Unknown"),
        "context_budget": _env_int("NOVA_NUM_CTX", 8192, 2048),
        "output_budget": _env_int("NOVA_NUM_PREDICT", 2048, 128),
        "tools": tools,
        "registered_tools": len(tools),
        "enabled_tools": sum(bool(tool["enabled"]) for tool in tools),
        "components": components,
        "present_components": sum(bool(item["present"]) for item in components),
        "component_count": len(components),
        "access": {
            key: bool(access.get(key, True))
            for key in ("web", "git", "pc")
        },
        "execution_state_available": isinstance(getattr(core, "execution_state", None), dict),
    }
