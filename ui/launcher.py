"""CLI entry point selecting the Textual TUI or prompt_toolkit fallback."""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Nova local AI agent")
    parser.add_argument("--prompt-toolkit", action="store_true", help="Use the prompt_toolkit interactive CLI")
    parser.add_argument("--rich", action="store_true", help="Use the previous Rich-only interface")
    args = parser.parse_args()

    if args.prompt_toolkit:
        from ui.prompt_cli import main as run_prompt_cli
        run_prompt_cli()
        return
    if args.rich:
        from main import main as run_rich
        run_rich()
        return

    from ui.textual_app import NovaTextualApp
    NovaTextualApp().run()
