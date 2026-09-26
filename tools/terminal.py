import subprocess
import os
import json


class TerminalTool:
    def __init__(self):
        self.history = []

        self.base_path = os.path.abspath(os.getcwd())

        self.projects_path = os.path.abspath(
            os.path.join(
                self.base_path,
                "projects"
            )
        )

        self.desktop_path = os.path.abspath(
            os.path.join(
                os.path.expanduser("~"),
                "Desktop"
            )
        )

        os.makedirs(
            self.projects_path,
            exist_ok=True
        )

    def _get_cwd(self, location):
        location = (
            location or "projects"
        ).lower().strip()

        if location == "desktop":
            return self.desktop_path

        if location == "projects":
            return self.projects_path

        raise ValueError(
            "Invalid location. Use 'projects' or 'desktop'."
        )

    def _is_blocked(self, command):
        lower = command.lower().strip()

        blocked = [
            "format ",
            "format:",
            "diskpart",
            "shutdown",
            "restart-computer",
            "stop-computer",
            "remove-item",
            "del /f",
            "erase ",
            "rmdir /s",
            "rd /s",
            "rm -rf",
            "reg delete",
            "net user",
            "net localgroup",
            "takeown",
            "icacls",
            "cipher /w",
        ]

        for item in blocked:
            if item in lower:
                return True

        return False

    def run(self, input_data):
        if not isinstance(input_data, str):
            return "Terminal error: input must be a string."

        command = input_data.strip()
        location = "projects"

        try:
            data = json.loads(input_data)

            if isinstance(data, dict):
                command = data.get("command")
                location = data.get(
                    "location",
                    "projects"
                )

        except json.JSONDecodeError:
            pass

        if not isinstance(command, str):
            return "Terminal error: command must be a string."

        command = command.strip()

        if not command:
            return "Terminal error: empty command."

        if not isinstance(location, str):
            location = "projects"

        if self._is_blocked(command):
            return "Command blocked for safety."

        try:
            cwd = self._get_cwd(location)

            self.history.append({
                "command": command,
                "location": location
            })

            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30
            )

            output_parts = [
                f"Exit code: {result.returncode}",
                f"Working directory: {cwd}"
            ]

            if result.stdout.strip():
                output_parts.append(
                    "STDOUT:\n" +
                    result.stdout.strip()
                )

            if result.stderr.strip():
                output_parts.append(
                    "STDERR:\n" +
                    result.stderr.strip()
                )

            if result.returncode == 0:
                output_parts.append(
                    "STATUS: SUCCESS"
                )
            else:
                output_parts.append(
                    "STATUS: ERROR"
                )

            return "\n".join(output_parts)

        except subprocess.TimeoutExpired:
            return (
                "STATUS: ERROR\n"
                "Terminal command timed out after 30 seconds."
            )

        except Exception as e:
            return f"Terminal error: {e}"