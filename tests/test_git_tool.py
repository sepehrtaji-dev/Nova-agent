import unittest

from tools.git import GitTool


class GitToolTests(unittest.TestCase):
    def setUp(self):
        self.tool = GitTool()

    def test_force_push_variants_are_blocked(self):
        for args in (
            ["push", "origin", "main", "--force"],
            ["push", "origin", "--force-with-lease", "main"],
            ["push", "-f", "origin", "main"],
        ):
            blocked, _ = self.tool._is_blocked(args)
            self.assertTrue(blocked, args)

    def test_non_force_push_is_allowed(self):
        blocked, _ = self.tool._is_blocked(["push", "origin", "main"])
        self.assertFalse(blocked)

    def test_relative_repo_path_cannot_escape_workspace(self):
        with self.assertRaises(ValueError):
            self.tool._resolve_repo_path("../../outside")

    def test_clone_destination_is_sanitized_to_basename(self):
        data = {
            "action": "clone",
            "url": "https://example.invalid/owner/repo.git",
            "dest": "../../escape",
        }
        self.assertEqual(self.tool._parse_input(data), data)
        destination = data["dest"].replace("\\", "/").rstrip("/").split("/")[-1]
        self.assertEqual(destination, "escape")

    def test_run_returns_error_string_instead_of_raising(self):
        """Regression: run() resolved the path before checking 'action'.

        A payload with an escaping path and no action raised an uncaught
        ValueError, which can abort the agent turn instead of surfacing as a
        ordinary tool failure.
        """
        for payload in (
            {"path": "."},
            {"path": ".."},
            {"path": "../../outside"},
            {},
            {"action": ""},
        ):
            result = self.tool.run(payload)
            self.assertIsInstance(result, str, payload)
            self.assertIn("GIT ERROR", result, payload)

    def test_missing_action_is_reported_clearly(self):
        result = self.tool.run({})
        self.assertIn("action", result.lower())
        self.assertIn("required", result.lower())

    def test_unknown_action_is_reported(self):
        result = self.tool.run({"action": "definitely_not_a_git_action"})
        self.assertIsInstance(result, str)
        self.assertIn("GIT", result.upper())


if __name__ == "__main__":
    unittest.main()
