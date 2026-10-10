"""Textual full-screen terminal interface for Nova."""
from __future__ import annotations

from datetime import datetime
from time import perf_counter

from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from agent.core import NovaCore
from agent.introspection import inspect_model, runtime_profile


class NovaTextualApp(App):
    """Full-screen chat UI. Agent execution runs in a worker, not the UI loop."""

    TITLE = "NOVA · Local AI Agent"
    SUB_TITLE = "Textual interface · Ollama runtime"
    CSS = """
    Screen { background: #0b1020; color: #e5e7eb; }
    #topline { height: 3; padding: 0 1; border: round #22d3ee; background: #111827; }
    #workspace { height: 1fr; }
    #transcript { width: 2fr; height: 1fr; border: round #334155; margin: 0 1 0 0; padding: 0 1; background: #0f172a; }
    #sidebar { width: 1fr; min-width: 28; height: 1fr; border: round #334155; padding: 1; background: #0f172a; }
    #activity { height: 1fr; }
    #status { height: auto; min-height: 3; padding: 1; border: round #334155; margin-top: 1; }
    #prompt { dock: bottom; margin: 1; border: round #22d3ee; }
    #hint { height: 1; padding: 0 2; color: #94a3b8; }
    .muted { color: #94a3b8; }
    """
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_chat", "Clear chat"),
        ("f1", "show_help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.core: NovaCore | None = None
        self.started_at = perf_counter()
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("✦ NOVA     LOCAL AI AGENT                         Starting…", id="topline")
        with Horizontal(id="workspace"):
            yield RichLog(id="transcript", wrap=True, markup=False, auto_scroll=True)
            with Vertical(id="sidebar"):
                yield Static("LIVE RUNTIME", classes="muted")
                yield RichLog(id="activity", wrap=True, markup=False, auto_scroll=True)
                yield Static("Initializing local agent…", id="status")
        yield Static("Enter to send · /help commands · Ctrl+L clear · Ctrl+C quit", id="hint")
        yield Input(placeholder="Ask Nova anything, or type /help…", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.core = NovaCore(status_callback=self._status_from_core)
            profile = runtime_profile(self.core)
            self.query_one("#topline", Static).update(
                f"✦ NOVA     LOCAL AI AGENT     {profile['configured_model']}     "
                f"{profile['enabled_tools']}/{profile['registered_tools']} tools enabled"
            )
            self.query_one("#transcript", RichLog).write(
                Panel(
                    "Ask naturally. Nova can plan tasks, use enabled tools, inspect real results, and verify outcomes.\n\n"
                    "The interface displays observable activity, not private model reasoning.",
                    title="SESSION READY",
                    border_style="cyan",
                )
            )
            self._refresh_sidebar()
            self._set_status("Ready · local Ollama agent")
        except Exception as exc:
            self.query_one("#transcript", RichLog).write(
                Panel(f"{type(exc).__name__}: {exc}", title="Startup error", border_style="red")
            )
            self._set_status("Startup failed")

    def _refresh_sidebar(self) -> None:
        if self.core is None:
            return
        profile = runtime_profile(self.core)
        table = Table(show_header=False, expand=True, box=None, padding=(0, 1))
        table.add_column("key", style="dim")
        table.add_column("value", style="bold")
        table.add_row("Model", profile["configured_model"])
        table.add_row("Python", profile["python"])
        table.add_row("Context", f"{profile['context_budget']:,}")
        table.add_row("Output", f"{profile['output_budget']:,}")
        table.add_row("Tools", f"{profile['enabled_tools']}/{profile['registered_tools']}")
        table.add_row("Components", f"{profile['present_components']}/{profile['component_count']}")
        for name, enabled in profile["access"].items():
            table.add_row(name.upper(), "ON" if enabled else "OFF")
        self.query_one("#activity", RichLog).write(Panel(table, title="Runtime snapshot", border_style="cyan"))

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _status_from_core(self, message: str) -> None:
        try:
            self.call_from_thread(self._record_activity, str(message))
        except Exception:
            # The app may already be closing; status reporting must not break the agent.
            pass

    def _record_activity(self, message: str) -> None:
        log = self.query_one("#activity", RichLog)
        stamp = datetime.now().strftime("%H:%M:%S")
        log.write(Text(f"{stamp}  {message}", style="cyan"))
        self._set_status(message[:180])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message or self.busy:
            return
        event.input.value = ""
        if message.startswith("/"):
            self._handle_command(message)
            return
        self.query_one("#transcript", RichLog).write(
            Panel(message, title="YOU", border_style="grey50")
        )
        self.busy = True
        self.query_one("#prompt", Input).disabled = True
        self._set_status("Nova is working…")
        self.run_worker(lambda: self._process_request(message), thread=True, exclusive=True)

    def _process_request(self, message: str) -> None:
        if self.core is None:
            self.call_from_thread(self._finish_error, "Nova core is not initialized.")
            return
        started = perf_counter()
        try:
            response = self.core.ask(message)
            elapsed = perf_counter() - started
            self.call_from_thread(self._finish_response, str(response), elapsed)
        except Exception as exc:
            self.call_from_thread(self._finish_error, f"{type(exc).__name__}: {exc}")

    def _finish_response(self, response: str, elapsed: float) -> None:
        self.query_one("#transcript", RichLog).write(
            Panel(Markdown(response), title=f"NOVA · {elapsed:.2f}s", border_style="cyan")
        )
        self.busy = False
        self.query_one("#prompt", Input).disabled = False
        self.query_one("#prompt", Input).focus()
        self._set_status(f"Ready · last response {elapsed:.2f}s")

    def _finish_error(self, message: str) -> None:
        self.query_one("#transcript", RichLog).write(Panel(message, title="Request failed", border_style="red"))
        self.busy = False
        self.query_one("#prompt", Input).disabled = False
        self.query_one("#prompt", Input).focus()
        self._set_status("Request failed")

    def _handle_command(self, command: str) -> None:
        if self.core is None:
            self._set_status("Nova core is not initialized")
            return
        name = command.split(maxsplit=1)[0].lower()
        if name in {"/exit", "/quit"}:
            self.exit()
        elif name in {"/help", "/?"}:
            self.query_one("#transcript", RichLog).write(Panel(
                "/self  runtime + Ollama metadata\n/model  model metadata\n/status  local status\n"
                "/tools  tool registry\n/permissions  capability toggles\n/web, /git, /pc  toggle access\n"
                "/doctor  local health diagnostics\n/clear  clear conversation\n/reset  restart core\n/exit  quit",
                title="COMMANDS", border_style="cyan"))
        elif name == "/clear":
            self.query_one("#transcript", RichLog).clear()
        elif name == "/status":
            profile = runtime_profile(self.core)
            self.query_one("#transcript", RichLog).write(Panel(
                f"Model: {profile['configured_model']}\nPython: {profile['python']}\n"
                f"Tools: {profile['enabled_tools']}/{profile['registered_tools']}\n"
                f"Components: {profile['present_components']}/{profile['component_count']}\n"
                "This status snapshot does not contact Ollama.",
                title="STATUS", border_style="cyan"))
        elif name in {"/self", "/model"}:
            self.busy = True
            self.query_one("#prompt", Input).disabled = True
            self._set_status("Reading local Ollama metadata…")
            self.run_worker(lambda: self._inspect(name), thread=True, exclusive=True)
        elif name == "/doctor":
            self.busy = True
            self.query_one("#prompt", Input).disabled = True
            self._set_status("Running local diagnostics…")
            self.run_worker(self._diagnose, thread=True, exclusive=True)
        elif name == "/tools":
            profile = runtime_profile(self.core)
            table = Table(title="Tool registry", expand=True)
            table.add_column("Tool")
            table.add_column("Capability")
            table.add_column("Permission")
            for tool in profile["tools"]:
                table.add_row(tool["name"], tool["capability"], "ON" if tool["enabled"] else "OFF")
            self.query_one("#transcript", RichLog).write(table)
        elif name == "/permissions":
            profile = runtime_profile(self.core)
            self.query_one("#transcript", RichLog).write(Panel(
                "\n".join(f"{key}: {'ON' if enabled else 'OFF'}" for key, enabled in profile["access"].items()),
                title="PERMISSIONS", border_style="cyan"))
        elif name in {"/web", "/git", "/pc"}:
            key = name[1:]
            current = self.core.get_access().get(key, True)
            self.core.set_access(**{key: not current})
            self._refresh_sidebar()
            self._set_status(f"{key.upper()} access {'enabled' if not current else 'disabled'}")
        elif name == "/reset":
            self.busy = True
            self.query_one("#prompt", Input).disabled = True
            self.run_worker(self._reset_core, thread=True, exclusive=True)
        else:
            self._set_status(f"Unknown command: {name} · try /help")

    def _diagnose(self) -> None:
        if self.core is None:
            self.call_from_thread(self._finish_error, "Nova core is not initialized.")
            return
        try:
            report = self.core.diagnostics.snapshot(self.core, probe_model=True)
            lines = [
                f"{item['name']}: {item['status']} — {item['detail']}"
                for item in report["checks"]
            ]
            summary = report["summary"]
            lines.append(
                f"Tools: {summary['registered_tools']} registered · "
                f"{summary['verified_tools']} recently verified · "
                f"{summary['failed_tools']} failed · "
                f"{summary['untested_tools']} untested · "
                f"{summary['disabled_tools']} disabled"
            )
            lines.append("A model appearing in Ollama metadata does not prove generation works.")
            self.call_from_thread(self._finish_diagnose, "\n".join(lines))
        except Exception as exc:
            self.call_from_thread(self._finish_error, f"{type(exc).__name__}: {exc}")

    def _finish_diagnose(self, report: str) -> None:
        self.query_one("#transcript", RichLog).write(
            Panel(report, title="NOVA DIAGNOSTICS", border_style="yellow")
        )
        self.busy = False
        self.query_one("#prompt", Input).disabled = False
        self.query_one("#prompt", Input).focus()
        self._set_status("Diagnostics complete · generation not tested")

    def _inspect(self, command: str) -> None:
        if self.core is None:
            self.call_from_thread(self._finish_error, "Nova core is not initialized.")
            return
        profile = runtime_profile(self.core)
        model = inspect_model(self.core)
        table = Table(show_header=False, expand=True, box=None, padding=(0, 1))
        table.add_column("field", style="dim")
        table.add_column("value")
        rows = [
            ("Identity", f"{profile['identity']} · {profile['developer']}"),
            ("Version", profile["version"]),
            ("Provider / model", f"{profile['provider']} · {profile['configured_model']}"),
            ("Python", f"{profile['implementation']} {profile['python']}"),
            ("Platform", profile["platform"]),
            ("Working directory", profile["working_directory"]),
            ("Context / output", f"{profile['context_budget']:,} / {profile['output_budget']:,}"),
            ("Tools enabled", f"{profile['enabled_tools']}/{profile['registered_tools']}"),
            ("Components present", f"{profile['present_components']}/{profile['component_count']}"),
            ("Model metadata", model["status"]),
            ("Parameter count", model["parameter_count"]),
            ("Reported size", model["parameter_size"]),
            ("Architecture", model["architecture"]),
            ("Quantization", model["quantization"]),
            ("Model context length", model["model_context_length"]),
            ("Capabilities", ", ".join(model["capabilities"]) or "Unknown"),
            ("Evidence", model["detail"]),
        ]
        for key, value in rows:
            table.add_row(key, str(value))
        self.call_from_thread(self._finish_inspection, command, table)

    def _finish_inspection(self, command: str, table: Table) -> None:
        self.query_one("#transcript", RichLog).write(Panel(table, title="NOVA SELF-INSPECTION" if command == "/self" else "OLLAMA MODEL", border_style="cyan"))
        self.busy = False
        self.query_one("#prompt", Input).disabled = False
        self.query_one("#prompt", Input).focus()
        self._set_status("Metadata read complete · values are not guessed")

    def _reset_core(self) -> None:
        try:
            core = NovaCore(status_callback=self._status_from_core)
            self.call_from_thread(self._finish_reset, core)
        except Exception as exc:
            self.call_from_thread(self._finish_error, f"{type(exc).__name__}: {exc}")

    def _finish_reset(self, core: NovaCore) -> None:
        self.core = core
        self._refresh_sidebar()
        self.busy = False
        self.query_one("#prompt", Input).disabled = False
        self.query_one("#prompt", Input).focus()
        self._set_status("New Nova session ready")

    def action_clear_chat(self) -> None:
        self.query_one("#transcript", RichLog).clear()

    def action_show_help(self) -> None:
        self._handle_command("/help")
