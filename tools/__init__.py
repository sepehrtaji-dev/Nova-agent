from tools.registry import ToolRegistry
from tools.terminal import run_command


def load_tools():

    registry = ToolRegistry()

    registry.register(
        "terminal",
        "Execute approved local terminal commands",
        run_command
    )

    return registry