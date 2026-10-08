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


if __name__ == "__main__":
    unittest.main()
