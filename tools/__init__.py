from tools.registry import ToolRegistry
from tools.terminal import TerminalTool



def load_tools():

    registry = ToolRegistry()


    terminal = TerminalTool()


    registry.register(
        "terminal",
        "Execute safe terminal commands on the local computer",
        terminal.run
    )


    return registry