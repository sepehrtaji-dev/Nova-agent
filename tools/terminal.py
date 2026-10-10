import subprocess
import os
import json
import shlex
import ntpath


class TerminalTool:
    def __init__(self):
        self.history = []
        self.base_path = os.path.abspath(os.getcwd())
        self.projects_path = os.path.abspath(
            os.path.join(self.base_path, "projects")
        )
        self.desktop_path = os.path.abspath(
            os.path.join(os.path.expanduser("~"), "Desktop")
        )
        os.makedirs(self.projects_path, exist_ok=True)

    def _get_cwd(self, location):
        location = (location or "projects").lower().strip()

        if location == "desktop":
            return self.desktop_path

        if location == "projects":
            return self.projects_path

        raise ValueError(
            "Invalid location. Use 'projects' or 'desktop'."
        )

    def _is_blocked(self, command):
        lower = command.lower().strip()

        # shell=False prevents shell metacharacter interpretation, but it does
        # not prevent launching a shell or asking an interpreter to execute
        # arbitrary inline code. Block those escape hatches while preserving
        # ordinary project commands (including Python test/script execution).
        try:
            tokens = shlex.split(command, posix=(os.name != "nt"))
        except ValueError:
            return True

        if not tokens:
            return True

        executable = ntpath.basename(tokens[0]).casefold()
        executable = executable.removesuffix(".exe")
        shell_launchers = {
            "sh", "bash", "zsh", "fish", "dash", "cmd", "powershell",
            "pwsh", "wscript", "cscript", "mshta", "rundll32", "regsvr32",
        }
        if executable in shell_launchers:
            return True

        # Inline interpreter modes can run arbitrary code without a script
        # path, so refuse them. Python's unittest and compileall modules remain
        # available for the project's normal verification workflow.
        inline_flags = {
            "python": {"-c", "--command"},
            "python3": {"-c", "--command"},
            "python3.11": {"-c", "--command"},
            "python3.12": {"-c", "--command"},
            "python3.13": {"-c", "--command"},
            "python3.14": {"-c", "--command"},
            "pypy": {"-c", "--command"},
            "node": {"-e", "--eval", "-p", "--print"},
            "ruby": {"-e", "--eval"},
            "perl": {"-e"},
            "php": {"-r"},
        }
        flags = inline_flags.get(executable, set())
        if any(token.casefold() in flags for token in tokens[1:]):
            return True

        if executable in {"python", "python3", "python3.11", "python3.12", "python3.13", "python3.14", "pypy"}:
            for index, token in enumerate(tokens[1:-1], start=1):
                if token == "-m":
                    module = tokens[index + 1].casefold()
                    if module not in {"unittest", "compileall", "pytest"}:
                        return True

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

    def _parse_input(self, input_data):
        command = input_data
        location = "projects"
        stdin_data = None

        if isinstance(input_data, dict):
            command = input_data.get("command")
            location = input_data.get("location", "projects")
            stdin_data = input_data.get("input")

        elif isinstance(input_data, str):
            text = input_data.strip()

            try:
                data = json.loads(text)

                if isinstance(data, dict):
                    command = data.get("command")
                    location = data.get(
                        "location",
                        "projects"
                    )
                    stdin_data = data.get("input")

            except json.JSONDecodeError:
                command = input_data

        if not isinstance(command, str):
            return None, None, None

        if not isinstance(location, str):
            location = "projects"

        if stdin_data is not None and not isinstance(
            stdin_data,
            str
        ):
            stdin_data = str(stdin_data)

        return command.strip(), location.strip(), stdin_data

    def run(self, input_data):
        command, location, stdin_data = self._parse_input(
            input_data
        )

        if not command:
            return (
                "Terminal error: command must be a non-empty string."
            )

        if self._is_blocked(command):
            return "Command blocked for safety."

        try:
            cwd = self._get_cwd(location)

            self.history.append({
                "command": command,
                "location": location,
                "input_provided": stdin_data is not None
            })
            # Limit history to last 100 entries
            if len(self.history) > 100:
                self.history = self.history[-100:]

            # Reject shell operators for safety
            shell_operators = ['|', '&&', ';', '>', '<', '`', '$(']
            for op in shell_operators:
                if op in command:
                    return (
                        f"Terminal error: shell operators ({op!r}) are not allowed. "
                        "Use a simple command without pipes, redirects, or chaining."
                    )

            try:
                cmd_args = shlex.split(command)
            except ValueError as e:
                return f"Terminal error: invalid command syntax: {e}"

            run_kwargs = {
                "shell": False,
                "cwd": cwd,
                "capture_output": True,
                "text": True,
                "timeout": 20,
            }

            if stdin_data is None:
                run_kwargs["stdin"] = subprocess.DEVNULL
            else:
                run_kwargs["input"] = stdin_data

            result = subprocess.run(
                cmd_args,
                **run_kwargs
            )

            output_parts = [
                f"Exit code: {result.returncode}",
                f"Working directory: {cwd}",
            ]

            if stdin_data is not None:
                output_parts.append(
                    "STDIN: PROVIDED"
                )
            else:
                output_parts.append(
                    "STDIN: EOF"
                )

            if result.stdout.strip():
                output_parts.append(
                    "STDOUT:\n" + result.stdout.strip()
                )

            if result.stderr.strip():
                output_parts.append(
                    "STDERR:\n" + result.stderr.strip()
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
                "Terminal command timed out after 20 seconds.\n"
                "If the program is interactive, provide test input "
                "through the terminal input field instead of waiting "
                "for interactive user input."
            )

        except Exception as e:
            return (
                "Terminal error: "
                f"{type(e).__name__}: {e}"
            )
