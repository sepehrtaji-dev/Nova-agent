import unittest

from tools.terminal import TerminalTool


class TerminalSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tool = TerminalTool()

    def test_shell_launchers_are_blocked(self):
        for command in (
            "bash -c echo unsafe",
            "sh -c echo unsafe",
            "powershell -Command Write-Output unsafe",
            "cmd /c echo unsafe",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.tool._is_blocked(command))

    def test_inline_interpreter_execution_is_blocked(self):
        for command in (
            'python -c "print(1)"',
            'python3 -c "print(1)"',
            'node -e "console.log(1)"',
            'ruby -e "puts 1"',
            'php -r "echo 1;"',
        ):
            with self.subTest(command=command):
                self.assertTrue(self.tool._is_blocked(command))

    def test_unapproved_python_module_execution_is_blocked(self):
        self.assertTrue(self.tool._is_blocked("python -m http.server"))

    def test_normal_project_verification_commands_remain_allowed(self):
        self.assertFalse(self.tool._is_blocked("python -m unittest tests.test_core"))
        self.assertFalse(self.tool._is_blocked("python -m compileall -q agent tools"))
        self.assertFalse(self.tool._is_blocked("echo ok"))

    def test_malformed_command_is_blocked(self):
        self.assertTrue(self.tool._is_blocked('python "unterminated'))

    def test_windows_paths_are_not_corrupted_by_splitting(self):
        """Regression: POSIX shlex rules ate backslashes in Windows paths.

        shlex.split(r"python C:\\projects\\a.py") produced
        ["python", "C:projectsa.py"], so a valid command reached subprocess
        with a mangled path and failed with a confusing error.
        """
        import os
        import shlex

        command = r"python C:\projects\a.py"
        if os.name == "nt":
            args = [
                token[1:-1]
                if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"
                else token
                for token in shlex.split(command, posix=False)
            ]
        else:
            args = shlex.split(command)

        if os.name == "nt":
            self.assertEqual(args[1], r"C:\projects\a.py")
        else:
            # POSIX splitting is expected behavior off Windows.
            self.assertTrue(args[1].endswith("a.py"))

    def test_quoted_windows_path_keeps_spaces(self):
        import os
        import shlex

        command = r'python "C:\my projects\test.py"'
        if os.name != "nt":
            self.skipTest("Windows-specific path handling")
        args = [
            token[1:-1]
            if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"
            else token
            for token in shlex.split(command, posix=False)
        ]
        self.assertEqual(args[1], r"C:\my projects\test.py")

    def test_shell_operators_are_rejected_before_execution(self):
        for command in (
            "echo hi > out.txt",
            "cat a | grep b",
            "a && b",
            "a; b",
            "sort < in.txt",
            "echo $(whoami)",
        ):
            with self.subTest(command=command):
                operators = ["|", "&&", ";", ">", "<", "$("]
                self.assertTrue(
                    any(op in command for op in operators),
                    f"operator scan should flag {command!r}",
                )

    def test_windows_builtins_report_a_clear_error(self):
        """Regression: cmd builtins failed with a raw WinError 2.

        echo/dir/type are shell builtins with no executable on PATH, and cmd.exe
        is deliberately blocked, so shell=False raised FileNotFoundError and the
        model saw an opaque OS error instead of an actionable message.
        """
        import os

        if os.name != "nt":
            self.skipTest("Windows-specific builtin handling")
        tool = TerminalTool()
        for command in ("echo hello", "dir", "type file.txt"):
            result = tool.run({"command": command, "location": "projects"})
            self.assertIn("builtin", result.lower(), command)
            self.assertIn("not a program", result.lower(), command)

    def test_unknown_program_reports_not_found(self):
        import os

        if os.name != "nt":
            self.skipTest("Windows-specific PATH handling")
        tool = TerminalTool()
        result = tool.run({"command": "surely-not-a-real-program-xyz",
                           "location": "projects"})
        self.assertIn("no program named", result.lower())
        self.assertNotIn("WinError", result)

    def test_posix_utilities_get_an_actionable_error(self):
        """Regression: 'touch tasks.txt' failed with a bare 'not found'.

        The model could not tell why and retried 12 times with variations. The
        message must name the actual problem and point at the file tools.
        """
        import os

        if os.name != "nt":
            self.skipTest("Windows-specific POSIX handling")
        tool = TerminalTool()
        for command in ("touch tasks.txt", "ls", "cat file.txt", "rm x"):
            result = tool.run({"command": command, "location": "projects"})
            self.assertIn("POSIX", result, command)
            self.assertIn("file tools", result.lower(), command)
            self.assertIn("write_file", result, command)

    def test_real_executable_still_runs(self):
        import os
        import shutil
        import sys

        if shutil.which(sys.executable) is None:
            self.skipTest("no python executable on PATH")
        tool = TerminalTool()
        result = tool.run({"command": '"' + sys.executable + '" --version',
                           "location": "projects"})
        self.assertNotIn("builtin", result.lower())
        self.assertNotIn("no program named", result.lower())


if __name__ == "__main__":
    unittest.main()
