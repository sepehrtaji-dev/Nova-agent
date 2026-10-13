import importlib
import logging

from tools.registry import ToolRegistry


def load_tools():
    """Load only web search for the temporary search-only Nova profile.

    Other tool implementations remain in the repository and can be re-enabled
    later by changing this allowlist; they are not imported or registered here.
    """
    registry = ToolRegistry()
    definitions = (
        (
            "web_search",
            "Search the public web for current information. Return real titles, URLs, and snippets.",
            "tools.web",
            "WebSearchTool",
            "run",
            "web",
            {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                },
            },
        ),
    )

    instances = {}
    for name, description, module_name, class_name, method_name, capability, input_schema in definitions:
        key = (module_name, class_name)
        try:
            if key not in instances:
                module = importlib.import_module(module_name)
                factory = getattr(module, class_name)
                instances[key] = factory()
            handler = getattr(instances[key], method_name)
            registry.register(
                name,
                description,
                handler,
                capability=capability,
                input_schema=input_schema,
            )
        except Exception as exc:
            logging.warning(
                "Tool '%s' unavailable (%s): %s",
                name,
                type(exc).__name__,
                exc,
            )
    return registry
