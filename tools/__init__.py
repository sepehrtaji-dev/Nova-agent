import importlib
import json
import logging
import os
from pathlib import Path

from tools.registry import ToolRegistry


def _manifest_path():
    configured = os.getenv("NOVA_TOOL_MANIFEST", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "config" / "tools.json"


def load_tools():
    """Load enabled tools from the declarative manifest, without a Python allowlist."""
    registry = ToolRegistry()
    path = _manifest_path()
    try:
        with path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logging.error("Could not load tool manifest '%s': %s", path, exc)
        return registry

    definitions = manifest.get("tools", []) if isinstance(manifest, dict) else []
    if not isinstance(definitions, list):
        logging.error("Tool manifest '%s' must contain a tools list.", path)
        return registry

    instances = {}
    for definition in definitions:
        if not isinstance(definition, dict) or not definition.get("enabled", True):
            continue
        name = definition.get("name")
        module_name = definition.get("module")
        class_name = definition.get("class")
        method_name = definition.get("method")
        capability = definition.get("capability")
        description = definition.get("description", "")
        schema = definition.get("input_schema")

        if not all(isinstance(value, str) and value.strip() for value in (
            name, module_name, class_name, method_name, capability
        )):
            logging.warning("Skipping malformed tool definition: %r", definition)
            continue
        if not isinstance(description, str) or not description.strip():
            logging.warning("Skipping tool '%s' without a description.", name)
            continue
        if schema is not None and not isinstance(schema, dict):
            logging.warning("Skipping tool '%s' with an invalid input schema.", name)
            continue

        key = (module_name, class_name)
        try:
            if key not in instances:
                module = importlib.import_module(module_name)
                factory = getattr(module, class_name)
                instances[key] = factory()
            handler = getattr(instances[key], method_name)
            if not callable(handler):
                raise TypeError("Configured tool method is not callable.")
            registry.register(
                name,
                description,
                handler,
                capability=capability,
                input_schema=schema,
            )
        except Exception as exc:
            logging.warning(
                "Tool '%s' unavailable (%s): %s",
                name,
                type(exc).__name__,
                exc,
            )
    return registry
