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
        "Execute safe terminal commands",
        terminal.run
    )

    registry.register(
        "list_files",
        "List files in projects or desktop",
        filesystem.list_files
    )

    registry.register(
        "read_file",
        "Read a text file from projects or desktop",
        filesystem.read_file
    )

    registry.register(
        "write_file",
        "Create or overwrite a text file in projects or desktop",
        filesystem.write_file
    )

    registry.register(
        "create_directory",
        "Create a directory in projects or desktop",
        filesystem.create_directory
    )

    registry.register(
        "web_search",
        "Search the public web",
        web.run
    )

    return registry