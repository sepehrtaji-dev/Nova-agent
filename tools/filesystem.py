"""
Nova FileSystem Tool
────────────────────
Supports three location modes:

  "projects"  → Nova's own projects/ workspace (sandboxed, default)
  "desktop"   → User's Desktop folder
  "system"    → Absolute path anywhere on the system (PC access required)

When location is "system", the path field must be an absolute path.
Example:
    {"path": "/home/user/Documents/notes.txt", "location": "system"}
    {"path": "C:/Users/user/Documents/notes.txt", "location": "system"}

Protected system paths are blocked even in system mode.
"""

import os
import json
import stat


class FileSystemTool:

    # ── Paths blocked even in system mode ─────────────────────────────────────
    _BLOCKED_PREFIXES = [
        "/proc",
        "/sys",
        "/dev",
        "/boot",
        "/etc/shadow",
        "/etc/sudoers",
        "/etc/passwd",
    ]

    _BLOCKED_EXTENSIONS = {
        ".so", ".dll", ".sys", ".ko",  # shared libs / kernel modules
    }

    def __init__(self):
        self.base_path    = os.path.abspath(os.getcwd())
        self.projects_path = os.path.join(self.base_path, "projects")
        self.desktop_path  = os.path.join(os.path.expanduser("~"), "Desktop")
        os.makedirs(self.projects_path, exist_ok=True)

    # ── Path resolution ───────────────────────────────────────────────────────

    def _resolve_path(self, path, location="projects"):
        path     = str(path).strip()
        location = str(location or "projects").lower().strip()

        if not path:
            raise ValueError("Path cannot be empty.")

        if location == "system":
            # Must be absolute
            if not os.path.isabs(path):
                raise ValueError(
                    f"System location requires an absolute path. Got: {path!r}\n"
                    "Example: /home/user/file.txt  or  C:/Users/user/file.txt"
                )
            full_path = os.path.abspath(path)
            self._check_system_path(full_path)
            return full_path

        if location == "desktop":
            root = os.path.abspath(self.desktop_path)
        elif location == "projects":
            root = os.path.abspath(self.projects_path)
        else:
            raise ValueError(
                f"Invalid location: {location!r}. "
                "Use 'projects', 'desktop', or 'system'."
            )

        # Relative path — join with root and security check
        full_path = os.path.abspath(os.path.join(root, path))

        try:
            common = os.path.commonpath([root, full_path])
            if common != root:
                raise ValueError(
                    f"Path escapes workspace root. "
                    f"Root: {root}  Path: {full_path}"
                )
        except ValueError:
            raise ValueError(
                f"Path escapes workspace root. "
                f"Root: {root}  Path: {full_path}"
            )

        return full_path

    def _check_system_path(self, full_path):
        """Block dangerous system paths even in system mode."""
        norm = full_path.replace("\\", "/")

        for blocked in self._BLOCKED_PREFIXES:
            if norm.startswith(blocked):
                raise PermissionError(
                    f"Access denied: {full_path!r} is a protected system path."
                )

        _, ext = os.path.splitext(full_path)
        if ext.lower() in self._BLOCKED_EXTENSIONS:
            raise PermissionError(
                f"Access denied: cannot read/write binary system files ({ext})."
            )

    def _parse_input(self, input_data, default_path="."):
        """Parse JSON or plain string input. Returns (path, location, extra_data)."""
        location   = "projects"
        path       = default_path
        extra_data = {}

        if isinstance(input_data, dict):
            path       = input_data.get("path", default_path)
            location   = input_data.get("location", "projects")
            extra_data = input_data
            return path, location, extra_data

        if not isinstance(input_data, str):
            return path, location, extra_data

        try:
            data = json.loads(input_data.strip())
            if isinstance(data, dict):
                path       = data.get("path", default_path)
                location   = data.get("location", "projects")
                extra_data = data
                return path, location, extra_data
        except json.JSONDecodeError:
            pass

        # Plain string — treat as path
        path = input_data.strip()
        return path, location, extra_data

    # ── list_files ────────────────────────────────────────────────────────────

    def list_files(self, input_data="."):
        try:
            path, location, _ = self._parse_input(input_data, default_path=".")
            full_path = self._resolve_path(path, location)

            if not os.path.exists(full_path):
                return f"Path does not exist: {full_path}"

            if not os.path.isdir(full_path):
                return f"Not a directory: {full_path}"

            entries = []
            for name in sorted(os.listdir(full_path)):
                entry = os.path.join(full_path, name)
                try:
                    if os.path.isdir(entry):
                        entries.append(f"[DIR]  {name}")
                    else:
                        size = os.path.getsize(entry)
                        entries.append(f"[FILE] {name}  ({size:,} bytes)")
                except PermissionError:
                    entries.append(f"[????] {name}  (permission denied)")

            if not entries:
                return f"Directory is empty: {full_path}"

            return f"Location: {full_path}\n\n" + "\n".join(entries)

        except PermissionError as e:
            return f"Permission denied: {e}"
        except Exception as e:
            return f"Filesystem error: {e}"

    # ── read_file ─────────────────────────────────────────────────────────────

    def read_file(self, input_data):
        try:
            path, location, _ = self._parse_input(input_data)

            if not path or path == ".":
                return "File path is required."

            full_path = self._resolve_path(path, location)

            if not os.path.exists(full_path):
                return f"File does not exist: {full_path}"

            if not os.path.isfile(full_path):
                return f"Path is not a file: {full_path}"

            size = os.path.getsize(full_path)

            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read(50000)  # max 50k chars
            except UnicodeDecodeError:
                # Try latin-1 as fallback
                try:
                    with open(full_path, "r", encoding="latin-1") as f:
                        content = f.read(50000)
                    content = f"[Warning: file decoded as latin-1]\n{content}"
                except Exception:
                    return f"File is not a readable text file: {full_path}"

            truncated = ""
            if size > 50000:
                truncated = f"\n\n[Truncated: showing first 50,000 of {size:,} bytes]"

            return content + truncated

        except PermissionError as e:
            return f"Permission denied: {e}"
        except Exception as e:
            return f"Filesystem error: {e}"

    # ── write_file ────────────────────────────────────────────────────────────

    def write_file(self, input_data):
        try:
            path, location, data = self._parse_input(input_data)

            if isinstance(input_data, str):
                try:
                    data = json.loads(input_data)
                except json.JSONDecodeError:
                    return "write_file requires a JSON object."

            if not isinstance(data, dict):
                return "write_file requires a JSON object."

            path     = data.get("path")
            content  = data.get("content")
            location = data.get("location", "projects")

            if not isinstance(path, str) or not path.strip():
                return "File path is required."

            if not isinstance(content, str):
                return "File content must be a string."

            full_path = self._resolve_path(path, location)

            # Create parent directories
            parent = os.path.dirname(full_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            size = os.path.getsize(full_path)

            return (
                f"FILE_CREATED\n"
                f"Location: {full_path}\n"
                f"Bytes: {size:,}"
            )

        except PermissionError as e:
            return f"Permission denied: {e}"
        except json.JSONDecodeError:
            return "Invalid JSON input for write_file."
        except Exception as e:
            return f"Filesystem error: {e}"

    # ── edit_file ─────────────────────────────────────────────────────────────

    def edit_file(self, input_data):
        """
        Edit a file by replacing a specific string with another.
        Input:
        {
            "path": "file.py",
            "location": "projects",
            "old": "text to find",
            "new": "replacement text",
            "replace_all": false   (optional, default false)
        }
        """
        try:
            if isinstance(input_data, str):
                try:
                    data = json.loads(input_data)
                except json.JSONDecodeError:
                    return "edit_file requires a JSON object."
            else:
                data = input_data

            if not isinstance(data, dict):
                return "edit_file requires a JSON object."

            path        = data.get("path")
            location    = data.get("location", "projects")
            old_str     = data.get("old")
            new_str     = data.get("new", "")
            replace_all = data.get("replace_all", False)

            if not isinstance(path, str) or not path.strip():
                return "edit_file requires a path."

            if not isinstance(old_str, str):
                return "edit_file requires 'old' string to find."

            if not isinstance(new_str, str):
                return "edit_file requires 'new' replacement string."

            full_path = self._resolve_path(path, location)

            if not os.path.isfile(full_path):
                return f"File does not exist: {full_path}"

            with open(full_path, "r", encoding="utf-8") as f:
                original = f.read()

            if old_str not in original:
                return (
                    f"String not found in file: {full_path}\n"
                    f"Searched for: {old_str[:100]!r}"
                )

            count = original.count(old_str)

            if replace_all:
                updated = original.replace(old_str, new_str)
                replaced = count
            else:
                if count > 1:
                    return (
                        f"Found {count} occurrences of the search string in {full_path}.\n"
                        "Use replace_all=true to replace all, or make old_str more specific."
                    )
                updated  = original.replace(old_str, new_str, 1)
                replaced = 1

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(updated)

            size = os.path.getsize(full_path)

            return (
                f"FILE_EDITED\n"
                f"Location: {full_path}\n"
                f"Replacements: {replaced}\n"
                f"Bytes: {size:,}"
            )

        except PermissionError as e:
            return f"Permission denied: {e}"
        except Exception as e:
            return f"Filesystem error: {e}"

    # ── create_directory ──────────────────────────────────────────────────────

    def create_directory(self, input_data):
        try:
            if isinstance(input_data, str):
                try:
                    data = json.loads(input_data)
                except json.JSONDecodeError:
                    return "create_directory requires a JSON object."
            else:
                data = input_data

            if not isinstance(data, dict):
                return "create_directory requires a JSON object."

            path     = data.get("path")
            location = data.get("location", "projects")

            if not isinstance(path, str) or not path.strip():
                return "Directory path is required."

            full_path = self._resolve_path(path, location)
            os.makedirs(full_path, exist_ok=True)

            return (
                f"DIRECTORY_CREATED\n"
                f"Location: {full_path}"
            )

        except PermissionError as e:
            return f"Permission denied: {e}"
        except json.JSONDecodeError:
            return "Invalid JSON input for create_directory."
        except Exception as e:
            return f"Filesystem error: {e}"

    # ── delete_file ───────────────────────────────────────────────────────────

    def delete_file(self, input_data):
        """
        Delete a file. Refuses to delete directories.
        Input: {"path": "file.py", "location": "projects"}
        """
        try:
            if isinstance(input_data, str):
                try:
                    data = json.loads(input_data)
                except json.JSONDecodeError:
                    return "delete_file requires a JSON object."
            else:
                data = input_data

            path     = data.get("path")
            location = data.get("location", "projects")

            if not isinstance(path, str) or not path.strip():
                return "File path is required."

            full_path = self._resolve_path(path, location)

            if not os.path.exists(full_path):
                return f"File does not exist: {full_path}"

            if os.path.isdir(full_path):
                return (
                    f"Path is a directory, not a file: {full_path}\n"
                    "Use terminal with 'rmdir' to remove directories."
                )

            os.remove(full_path)

            return (
                f"FILE_DELETED\n"
                f"Location: {full_path}"
            )

        except PermissionError as e:
            return f"Permission denied: {e}"
        except Exception as e:
            return f"Filesystem error: {e}"
