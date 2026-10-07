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
        (
            "Create or overwrite a file on disk. "
            "location: 'projects' (default), 'desktop', or 'system' (absolute path). "
            "For system: path must be absolute e.g. /home/user/file.py"
        ),
        filesystem.write_file
    )

    registry.register(
        "edit_file",
        (
            "Edit an existing file by replacing a specific string. "
            "Input: {path, location, old, new, replace_all}. "
            "Use this to modify existing files instead of rewriting them."
        ),
        filesystem.edit_file
    )

    registry.register(
        "delete_file",
        "Delete a file from disk. Input: {path, location}.",
        filesystem.delete_file
    )

    registry.register(
        "create_directory",
        (
            "Create a directory. "
            "location: 'projects', 'desktop', or 'system' (absolute path)."
        ),
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
            "log, diff, branch, checkout, create_branch, stash, create_repo. "
            "Input: {action, path, message, branch, url, files, remote, n, "
            "name, visibility, description}. "
            "create_repo creates a new GitHub repository (requires gh CLI)."
        ),
        git.run
    )

    registry.register(
        "desktop",
        (
            "Control the desktop: screenshots, mouse, keyboard, apps, and windows."
        ),
        desktop.run
    )

    registry.register(
        "generate_image",
        (
            "Generate an image using local Stable Diffusion (SD1.5) model. "
            "Input: {prompt, negative_prompt, width, height, num_inference_steps, "
            "guidance_scale, seed, filename}. Output saved to projects/generated_images/."
        ),
        image_gen.run
    )

    return registry
