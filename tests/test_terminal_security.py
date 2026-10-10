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


if __name__ == "__main__":
    unittest.main()
