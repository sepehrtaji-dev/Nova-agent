from tools.registry import ToolRegistry

from tools.terminal import TerminalTool
from tools.filesystem import FileSystemTool
from tools.web import WebSearchTool
from tools.git import GitTool


def load_tools():
    registry = ToolRegistry()

    terminal   = TerminalTool()
    filesystem = FileSystemTool()
    web        = WebSearchTool()
    git        = GitTool()

    registry.register(
        "terminal",
        "Execute safe terminal/shell commands on the user's PC",
        terminal.run
    )

    registry.register(
        "list_files",
        "List files and directories in the projects folder or desktop",
        filesystem.list_files
    )

    registry.register(
        "read_file",
        "Read the contents of a text file from the projects folder or desktop",
        filesystem.read_file
    )

    registry.register(
        "write_file",
        "Create or overwrite a file on disk. Requires path, content, and location.",
        filesystem.write_file
    )

    registry.register(
        "create_directory",
        "Create a new directory in the projects folder or desktop",
        filesystem.create_directory
    )

    registry.register(
        "web_search",
        "Search the public web for current information",
        web.run
    )

    registry.register(
        "git",
        (
            "Run git operations on a local repository. "
            "Supports: init, clone, status, add, commit, push, pull, "
            "log, diff, branch, checkout, create_branch, stash. "
            "Input: {action, path, message, branch, url, files, remote, n}"
        ),
        git.run
    )

    return registry
