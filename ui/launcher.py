"""CLI entry point selecting the Textual TUI or prompt_toolkit fallback."""
from __future__ import annotations

import argparse
import os
import sys


def _bootstrap_sys_path() -> None:
    # Running "python ui/launcher.py" puts ui/ (not the repo root) on sys.path,
    # so every repo-root import below raised ModuleNotFoundError.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> None:
    _bootstrap_sys_path()
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
