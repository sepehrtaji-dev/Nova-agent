import logging

from tools.registry import ToolRegistry
from tools.terminal import TerminalTool
from tools.filesystem import FileSystemTool
from tools.web import WebSearchTool
from tools.git import GitTool
from tools.desktop import DesktopTool
from tools.image_gen import ImageGenTool


def load_tools():
    """Load each tool independently so an optional dependency cannot crash startup."""
    registry = ToolRegistry()
    definitions = (
        ("terminal", "Execute safe terminal/shell commands on the user's PC", TerminalTool, "run", "pc"),
        ("list_files", "List files and directories in the projects folder or desktop", FileSystemTool, "list_files", "pc"),
        ("read_file", "Read the contents of a text file from the projects folder or desktop", FileSystemTool, "read_file", "pc"),
        ("find_files", "Find files recursively with optional filename and created/modified time filters.", FileSystemTool, "find_files", "pc"),
        ("write_file", "Create or overwrite a file in the allowed filesystem locations.", FileSystemTool, "write_file", "pc"),
        ("edit_file", "Edit an existing file by replacing a specific string.", FileSystemTool, "edit_file", "pc"),
        ("delete_file", "Delete a file from an allowed filesystem location.", FileSystemTool, "delete_file", "pc"),
        ("create_directory", "Create a directory in an allowed filesystem location.", FileSystemTool, "create_directory", "pc"),
        ("web_search", "Search the public web for current information", WebSearchTool, "run", "web"),
        ("git", "Run supported Git operations on a local repository.", GitTool, "run", "git"),
        ("desktop", "Control the desktop and GUI. Actions include screenshot, click, move, type, key, scroll, open_app, close_app, get_windows, and focus_window.", DesktopTool, "run", "pc"),
        ("generate_image", "Generate an image using the configured local image model.", ImageGenTool, "run", "pc"),
    )
    instances = {}
    for name, description, factory, method_name, capability in definitions:
        try:
            if factory not in instances:
                instances[factory] = factory()
            handler = getattr(instances[factory], method_name)
            registry.register(name, description, handler, capability=capability)
        except Exception as exc:
            logging.warning(
                "Tool '%s' unavailable (%s): %s",
                name,
                type(exc).__name__,
                exc,
            )
    return registry
