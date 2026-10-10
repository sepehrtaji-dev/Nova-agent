import importlib
import logging

from tools.registry import ToolRegistry


def load_tools():
    """Load tools independently; optional imports and constructors may fail safely."""
    registry = ToolRegistry()
    definitions = (
        ("terminal", "Execute terminal commands in an allowed workspace.", "tools.terminal", "TerminalTool", "run", "pc"),
        ("list_files", "List files and directories in the projects folder or desktop.", "tools.filesystem", "FileSystemTool", "list_files", "pc"),
        ("read_file", "Read a text file from an allowed filesystem location.", "tools.filesystem", "FileSystemTool", "read_file", "pc"),
        ("find_files", "Find files with optional filename and time filters.", "tools.filesystem", "FileSystemTool", "find_files", "pc"),
        ("write_file", "Create or overwrite a file in an allowed filesystem location.", "tools.filesystem", "FileSystemTool", "write_file", "pc"),
        ("edit_file", "Edit an existing file by replacing a specific string.", "tools.filesystem", "FileSystemTool", "edit_file", "pc"),
        ("delete_file", "Delete a file from an allowed filesystem location.", "tools.filesystem", "FileSystemTool", "delete_file", "pc"),
        ("create_directory", "Create a directory in an allowed filesystem location.", "tools.filesystem", "FileSystemTool", "create_directory", "pc"),
        ("web_search", "Search the public web for current information.", "tools.web", "WebSearchTool", "run", "web"),
        ("web_fetch", "Fetch readable text from a public HTTP/HTTPS webpage.", "tools.web", "WebSearchTool", "fetch", "web"),
        ("git", "Run supported Git operations on a local repository.", "tools.git", "GitTool", "run", "git"),
        ("github", "Read GitHub repository metadata, issues, pull requests, workflows, releases, and code search.", "tools.github", "GitHubTool", "run", "git"),
        ("desktop", "Control the desktop and GUI using supported desktop actions.", "tools.desktop", "DesktopTool", "run", "pc"),
        ("generate_image", "Generate images using the configured local image model.", "tools.image_gen", "ImageGenTool", "run", "pc"),
    )

    instances = {}
    for name, description, module_name, class_name, method_name, capability in definitions:
        key = (module_name, class_name)
        try:
            if key not in instances:
                module = importlib.import_module(module_name)
                factory = getattr(module, class_name)
                instances[key] = factory()
            handler = getattr(instances[key], method_name)
            registry.register(name, description, handler, capability=capability)
        except Exception as exc:
            logging.warning(
                "Tool '%s' unavailable (%s): %s",
                name,
                type(exc).__name__,
                exc,
            )
    return registry
