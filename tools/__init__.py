from tools.registry import ToolRegistry

from tools.terminal import TerminalTool
from tools.filesystem import FileSystemTool
from tools.web import WebSearchTool


def load_tools():

    registry = ToolRegistry()

    terminal = TerminalTool()
    filesystem = FileSystemTool()
    web = WebSearchTool()

    registry.register(
        "terminal",
        "Execute safe terminal commands on Windows",
        terminal.run
    )

    registry.register(
        "list_files",
        "List files inside a directory",
        filesystem.list_files
    )

    registry.register(
        "read_file",
        "Read a text file",
        filesystem.read_file
    )

    registry.register(
        "web_search",
        "Search the public web for current or unknown information",
        web.run
    )

    return registry