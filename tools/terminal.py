import subprocess
import os
import json
import shlex
import shutil
import ntpath

# Windows cmd.exe builtins: they exist only inside the shell, so shell=False
# cannot run them. Listed so the tool can explain instead of failing obscurely.
_WINDOWS_BUILTINS = {
    "echo", "dir", "type", "cd", "chdir", "copy", "move", "del", "erase",
    "ren", "rename", "md", "mkdir", "rd", "rmdir", "cls", "set", "path",
    "ver", "vol", "date", "time", "title", "prompt", "mklink", "assoc",
    "ftype", "color", "pause", "start", "call", "exit", "if", "for",
}

# POSIX utilities a model may reach for on Windows. Naming them lets the tool
# point at the file tools instead of emitting a bare "not found".
_POSIX_ONLY = {
    "touch", "ls", "cat", "grep", "rm", "cp", "mv", "sed", "awk", "chmod",
    "chown", "find", "xargs", "head", "tail", "wc", "sort", "uniq", "tee",
    "ln", "df", "du", "ps", "kill", "which", "bash", "sh", "env",
}


def _has_recursive_flag(token):
    """True when a token is a recursive flag for rm ("-r", "-rf", "--recursive")."""
    folded = token.casefold()
    if folded == "--recursive":
        return True
    return (
        folded.startswith("-")
        and not folded.startswith("--")
        and "r" in folded[1:]
    )


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
            # Process wrappers can hide a shell/interpreter as a later argument.
            # This tool is not an OS sandbox; refuse these wrappers entirely.
            "env", "command", "busybox", "sudo", "doas", "nohup", "setsid",
        }
        if executable in shell_launchers:
            return True

        # Processes that can spawn other programs from within their own
        # language (awk's system(), find -exec, xargs) are shell launchers in
        # disguise; this tool is not an OS sandbox, so refuse them.
        if executable in {"awk", "gawk", "mawk", "nawk", "xargs"}:
            return True
        if executable == "find" and any(
            token.casefold() in {"-exec", "-execdir", "-ok", "-okdir"}
            for token in tokens[1:]
        ):
            return True

        # Inline interpreter modes can run arbitrary code without a script
        # path, so refuse them. Python's unittest and compileall modules remain
        # available for the project's normal verification workflow.
        #
        # Match interpreter FAMILIES by prefix instead of exact names: an
        # exact-name blocklist is trivially bypassed by any unlisted version
        # suffix (python3.10, python3.9, pypy3, nodejs, py.exe, ...).
        interpreter_families = {
            # family -> (short-flag letters that execute inline code, long flags)
            "python": ("c", {"--command"}),
            "pypy": ("c", {"--command"}),
            "py": ("c", {"--command"}),
            "node": ("ep", {"--eval", "--print"}),
            "ruby": ("e", {"--eval"}),
            "perl": ("e", {"--eval"}),
            "php": ("r", {"--run"}),
        }
        family = None
        for name, config in interpreter_families.items():
            if executable == name or (len(name) > 2 and executable.startswith(name)):
                family = name
                break

        if family is not None:
            inline_chars, inline_long = interpreter_families[family]
            for token in tokens[1:]:
                folded = token.casefold()
                if folded in inline_long:
                    return True
                # Catch combined short-flag clusters too ("python -ec 'code'").
                if (
                    folded.startswith("-")
                    and not folded.startswith("--")
                    and any(ch in inline_chars for ch in folded[1:])
                ):
                    return True

        # Python -m whitelist; accepts both "-m module" and "-mmodule".
        if family in {"python", "pypy", "py"}:
            rest = tokens[1:]
            for index, token in enumerate(rest):
                folded = token.casefold()
                if folded == "-m":
                    if index + 1 >= len(rest):
                        return True
                    module = rest[index + 1].casefold()
                    if module not in {"unittest", "compileall", "pytest"}:
                        return True
                elif folded.startswith("-m") and len(folded) > 2:
                    if folded[2:] not in {"unittest", "compileall", "pytest"}:
                        return True

        # Structural destructive-command checks. Flag order and combined short
        # flags ("rm -fr", "rm -r -f", "rm --recursive --force") must be caught
        # no matter how they are written, which raw substring matching misses.
        if executable == "rm" and any(
            _has_recursive_flag(token) for token in tokens[1:]
        ):
            return True
        if executable in {
            "format", "diskpart", "shutdown", "takeown", "icacls",
            "restart-computer", "stop-computer",
        }:
            return True
        if executable == "cipher" and any(
            token.casefold() in {"/w", "-w"} for token in tokens[1:]
        ):
            return True
        if executable == "reg" and any(
            token.casefold() == "delete" for token in tokens[1:]
        ):
            return True
        if executable == "net" and any(
            token.casefold() in {"user", "localgroup"} for token in tokens[1:]
        ):
            return True
        if executable == "remove-item":
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
        """Input object: {\"command\": \"program and arguments\", \"location\": \"projects\"|\"desktop\", \"input\": \"optional stdin\"}. Command is required; shell wrappers are restricted."""
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

            # POSIX shlex rules strip backslashes, which corrupts unquoted
            # Windows paths ("C:\projects\a.py" -> "C:projectsa.py"). Split with
            # platform-appropriate rules, and drop any surrounding quotes that
            # the Windows (non-POSIX) splitter leaves attached to a token.
            try:
                if os.name == "nt":
                    cmd_args = [
                        token[1:-1]
                        if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"
                        else token
                        for token in shlex.split(command, posix=False)
                    ]
                else:
                    cmd_args = shlex.split(command)
            except ValueError as e:
                return f"Terminal error: invalid command syntax: {e}"

            if not cmd_args:
                return "Terminal error: command must be a non-empty string."

            # On Windows, echo/dir/type/cd/copy/del are cmd.exe builtins with no
            # executable on PATH. shell=False cannot run them, and cmd.exe is
            # deliberately blocked as a shell launcher, so an unresolved first
            # token would otherwise surface as a confusing WinError 2. Detect it
            # and explain, rather than silently failing.
            if os.name == "nt":
                resolved = shutil.which(cmd_args[0])
                if resolved is None and cmd_args[0].casefold() in _WINDOWS_BUILTINS:
                    return (
                        f"Terminal error: '{cmd_args[0]}' is a Windows shell "
                        "builtin, not a program, so it cannot be run directly. "
                        "Use a real executable instead "
                        "(for example 'python script.py' or 'git status')."
                    )
                if resolved is None and cmd_args[0].casefold() in _POSIX_ONLY:
                    return (
                        f"Terminal error: '{cmd_args[0]}' is a POSIX shell "
                        "utility that does not exist on Windows. To create, read, "
                        "write, or list files, use the file tools (write_file, "
                        "read_file, list_files) instead of a shell command."
                    )
                if resolved is None:
                    return (
                        f"Terminal error: no program named '{cmd_args[0]}' was "
                        "found on PATH."
                    )

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
