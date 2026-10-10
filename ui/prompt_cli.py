"""Optional prompt_toolkit-based CLI for terminals where a full-screen TUI is not wanted."""
from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from agent.core import NovaCore
from agent.introspection import inspect_model, runtime_profile

COMMANDS = [
    "/help", "/self", "/model", "/status", "/tools", "/permissions",
    "/web", "/git", "/pc", "/doctor", "/memory", "/forget", "/clear", "/reset", "/exit",
]
console = Console()
STYLE = Style.from_dict({"prompt": "#22d3ee bold", "": "ansidefault"})


def main() -> None:
    core = NovaCore()
    session = PromptSession(history=InMemoryHistory())
    completer = WordCompleter(COMMANDS, sentence=True, match_middle=True)
    console.print(Panel("Nova · prompt_toolkit mode\nType /help for commands. Tab completes slash commands.", border_style="cyan"))
    while True:
        try:
            message = session.prompt([("class:prompt", "› ")], completer=completer, complete_while_typing=True, style=STYLE).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message:
            continue
        command = message.split(maxsplit=1)[0].lower()
        if command in {"/exit", "/quit"}:
            break
        if command == "/help":
            console.print("  " + "  ".join(COMMANDS))
        elif command == "/memory":
            entries = core.long_memory.entries()
            body = "\n".join(f"{item['key']}: {item['value']}" for item in entries)
            console.print(Panel(body or "No saved long-term memories.", title=f"Saved memory · {len(entries)} entries", border_style="cyan"))
        elif command == "/forget":
            parts = message.split(maxsplit=2)
            if len(parts) != 3:
                console.print("Usage: /forget <category> <key>  (example: /forget profile gpu)")
            elif core.long_memory.forget(parts[1], parts[2]):
                console.print(f"Forgot {parts[1]}.{parts[2]}.")
            else:
                console.print(f"No saved memory found for {parts[1]}.{parts[2]}.")
        elif command == "/clear":
            console.clear()
        elif command in {"/web", "/git", "/pc"}:
            key = command[1:]
            enabled = not core.get_access().get(key, True)
            core.set_access(**{key: enabled})
            console.print(f"{key.upper()} access {'enabled' if enabled else 'disabled'}")
        elif command == "/status":
            profile = runtime_profile(core)
            console.print(Panel(f"Model: {profile['configured_model']}\nPython: {profile['python']}\nTools: {profile['enabled_tools']}/{profile['registered_tools']}\nComponents: {profile['present_components']}/{profile['component_count']}", title="Runtime status", border_style="cyan"))
        elif command in {"/self", "/model"}:
            profile = runtime_profile(core)
            model = inspect_model(core)
            console.print(Panel(
                f"Identity: {profile['identity']} · {profile['developer']}\n"
                f"Model: {model['configured_name']}\nParameter count: {model['parameter_count']}\n"
                f"Architecture: {model['architecture']}\nQuantization: {model['quantization']}\n"
                f"Evidence: {model['detail']}",
                title="Nova self-inspection", border_style="cyan"))
        elif command == "/doctor":
            report = core.diagnostics.snapshot(core, probe_model=True)
            lines = [
                f"{item['name']}: {item['status']} — {item['detail']}"
                for item in report["checks"]
            ]
            lines.append("A listed model does not prove text generation works.")
            console.print(Panel("\n".join(lines), title="Nova diagnostics", border_style="yellow"))
        elif command == "/tools":
            profile = runtime_profile(core)
            for tool in profile["tools"]:
                console.print(f"{tool['name']} · {tool['capability']} · {'ON' if tool['enabled'] else 'OFF'}")
        elif command == "/permissions":
            console.print(core.get_access())
        elif command == "/reset":
            core = NovaCore()
            console.print("Started a fresh session.")
        else:
            try:
                response = core.ask(message)
                console.print(Panel(Markdown(str(response)), title="NOVA", border_style="cyan"))
            except Exception as exc:
                console.print(Panel(f"{type(exc).__name__}: {exc}", title="Request failed", border_style="red"))
    console.print("[dim]Nova session ended.[/dim]")
