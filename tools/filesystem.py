import os
import json


class FileSystemTool:
    def __init__(self):
        self.base_path = os.path.abspath(os.getcwd())
        self.projects_path = os.path.join(self.base_path, "projects")
        self.desktop_path = os.path.join(
            os.path.expanduser("~"),
            "Desktop"
        )

        os.makedirs(self.projects_path, exist_ok=True)

    def _get_root(self, location):
        location = (location or "projects").lower().strip()

        if location == "desktop":
            return self.desktop_path

        if location == "projects":
            return self.projects_path

        raise ValueError(
            "Invalid location. Use 'projects' or 'desktop'."
        )

    def _resolve_path(self, path, location="projects"):
        root = os.path.abspath(self._get_root(location))
        path = str(path).strip()

        if not path:
            raise ValueError("Path cannot be empty.")

        full_path = os.path.abspath(
            os.path.join(root, path)
        )

        try:
            if os.path.commonpath([root, full_path]) != root:
                raise ValueError("Path is outside the allowed workspace.")
        except ValueError:
            raise ValueError("Path is outside the allowed workspace.")

        return full_path

    def list_files(self, input_data="."):
        try:
            location = "projects"
            path = "."

            if isinstance(input_data, str):
                try:
                    data = json.loads(input_data)

                    if isinstance(data, dict):
                        path = data.get("path", ".")
                        location = data.get("location", "projects")
                    else:
                        path = input_data
                except json.JSONDecodeError:
                    path = input_data

            full_path = self._resolve_path(path, location)

            if not os.path.exists(full_path):
                return f"Path does not exist: {path}"

            if not os.path.isdir(full_path):
                return f"Not a directory: {path}"

            entries = []

            for name in sorted(os.listdir(full_path)):
                entry = os.path.join(full_path, name)

                if os.path.isdir(entry):
                    entries.append(f"[DIR] {name}")
                else:
                    entries.append(f"[FILE] {name}")

            if not entries:
                return "Directory is empty."

            return "\n".join(entries)

        except Exception as e:
            return f"Filesystem error: {e}"

    def read_file(self, input_data):
        try:
            location = "projects"
            path = input_data

            try:
                data = json.loads(input_data)

                if isinstance(data, dict):
                    path = data.get("path")
                    location = data.get("location", "projects")
            except json.JSONDecodeError:
                pass

            if not path:
                return "File path is required."

            full_path = self._resolve_path(path, location)

            if not os.path.exists(full_path):
                return "File does not exist."

            if not os.path.isfile(full_path):
                return "Path is not a file."

            with open(
                full_path,
                "r",
                encoding="utf-8"
            ) as f:
                content = f.read()

            return content[:20000]

        except UnicodeDecodeError:
            return "File is not a UTF-8 text file."
        except Exception as e:
            return f"Filesystem error: {e}"

    def write_file(self, input_data):
        try:
            data = json.loads(input_data)

            if not isinstance(data, dict):
                return "write_file requires a JSON object."

            path = data.get("path")
            content = data.get("content")
            location = data.get("location", "projects")

            if not isinstance(path, str) or not path.strip():
                return "File path is required."

            if not isinstance(content, str):
                return "File content must be a string."

            full_path = self._resolve_path(
                path,
                location
            )

            parent = os.path.dirname(full_path)

            if parent:
                os.makedirs(
                    parent,
                    exist_ok=True
                )

            with open(
                full_path,
                "w",
                encoding="utf-8"
            ) as f:
                f.write(content)

            return (
                f"FILE_CREATED\n"
                f"Location: {full_path}\n"
                f"Bytes: {os.path.getsize(full_path)}"
            )

        except json.JSONDecodeError:
            return "Invalid JSON input for write_file."
        except Exception as e:
            return f"Filesystem error: {e}"

    def create_directory(self, input_data):
        try:
            data = json.loads(input_data)

            if not isinstance(data, dict):
                return "create_directory requires a JSON object."

            path = data.get("path")
            location = data.get("location", "projects")

            if not isinstance(path, str) or not path.strip():
                return "Directory path is required."

            full_path = self._resolve_path(
                path,
                location
            )

            os.makedirs(
                full_path,
                exist_ok=True
            )

            return (
                f"DIRECTORY_CREATED\n"
                f"Location: {full_path}"
            )

        except json.JSONDecodeError:
            return "Invalid JSON input for create_directory."
        except Exception as e:
            return f"Filesystem error: {e}"