from tools.registry import ToolRegistry

from tools.terminal import TerminalTool
from tools.filesystem import FileSystemTool
from tools.web import WebSearchTool
from tools.git import GitTool
from tools.desktop import DesktopTool
from tools.image_gen import ImageGenTool


def load_tools():
    registry = ToolRegistry()

    terminal = TerminalTool()
    filesystem = FileSystemTool()
    web = WebSearchTool()
    git = GitTool()
    image_gen = ImageGenTool()
    desktop = DesktopTool()

    registry.register(
        "terminal",
        "Execute safe terminal/shell commands on the user's PC",
        terminal.run,
        capability="pc"
    )

    registry.register(
        "list_files",
        "List files and directories in the projects folder or desktop",
        filesystem.list_files,
        capability="pc"
    )

    registry.register(
        "read_file",
        "Read the contents of a text file from the projects folder or desktop",
        filesystem.read_file,
        capability="pc"
    )

    registry.register(
        "find_files",
        (
            "Find files recursively with optional filename pattern and "
            "created/modified time filters. Input: {path, location, pattern, "
            "recursive, created_within_hours, modified_within_hours}."
        ),
        filesystem.find_files,
        capability="pc"
    )

    registry.register(
        "write_file",
        (
            "Create or overwrite a file on disk. "
            "location: 'projects' (default), 'desktop', or 'system' (absolute path). "
            "For system: path must be absolute e.g. /home/user/file.py"
        ),
        filesystem.write_file,
        capability="pc"
    )

    registry.register(
        "edit_file",
        (
            "Edit an existing file by replacing a specific string. "
            "Input: {path, location, old, new, replace_all}. "
            "Use this to modify existing files instead of rewriting them."
        ),
        filesystem.edit_file,
        capability="pc"
    )

    registry.register(
        "delete_file",
        "Delete a file from disk. Input: {path, location}.",
        filesystem.delete_file,
        capability="pc"
    )

    registry.register(
        "create_directory",
        (
            "Create a directory. "
            "location: 'projects', 'desktop', or 'system' (absolute path)."
        ),
        filesystem.create_directory,
        capability="pc"
    )

    registry.register(
        "web_search",
        "Search the public web for current information",
        web.run,
        capability="web"
    )

    registry.register(
        "git",
        (
            "Run git operations on a local repository. "
            "Supports: init, clone, status, add, commit, push, pull, "
            "log, diff, branch, checkout, create_branch, stash, create_repo. "
            "Input: {action, path, message, branch, url, files, remote, n, "
            "name, visibility, description}. "
            "create_repo creates a new GitHub repository (requires gh CLI)."
        ),
        git.run,
        capability="git"
    )

    registry.register(
        "desktop",
        (
            "Control the desktop and GUI. Actions: screenshot, click, move, type, key, scroll, open_app, close_app, get_windows, focus_window. Input uses an action field plus the fields required by that action."
        ),
        desktop.run,
        capability="pc"
    )

    registry.register(
        "generate_image",
        (
            "Generate an image using local Stable Diffusion (SD1.5) model. "
            "Input: {prompt, negative_prompt, width, height, num_inference_steps, "
            "guidance_scale, seed, filename}. Output saved to projects/generated_images/."
        ),
        image_gen.run,
        capability="pc"
    )

    return registry
