import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.verifier import Verifier
from tools.github import GitHubTool


class GitHubToolTests(unittest.TestCase):
    def setUp(self):
        self.tool = GitHubTool()

    def test_builds_read_only_pull_request_query(self):
        args = self.tool._build_args({
            "action": "pr_list",
            "repo": "owner/project",
            "state": "open",
            "limit": 99,
        })
        self.assertEqual(args[:5], ["pr", "list", "--repo", "owner/project", "--state"])
        self.assertIn("20", args)
        self.assertNotIn("merge", args)

    def test_rejects_invalid_repository_identifier(self):
        with self.assertRaises(ValueError):
            self.tool._build_args({"action": "repo_view", "repo": "../other"})

    def test_rejects_unknown_or_mutating_action(self):
        with self.assertRaises(ValueError):
            self.tool._build_args({"action": "delete_repo", "repo": "owner/project"})

    def test_issue_view_requires_positive_number(self):
        with self.assertRaises(ValueError):
            self.tool._build_args({"action": "issue_view", "repo": "owner/project", "number": "-1"})

    @patch("tools.github.shutil.which", return_value="/usr/bin/gh")
    @patch("tools.github.subprocess.run")
    def test_runs_gh_without_shell_and_reports_exit_status(self, run_mock, _which):
        run_mock.return_value = SimpleNamespace(returncode=0, stdout="[]\n", stderr="")
        result = self.tool.run({"action": "issue_list", "repo": "owner/project"})
        self.assertIn("GITHUB_STATUS: SUCCESS", result)
        self.assertIn("Exit code: 0", result)
        self.assertFalse(run_mock.call_args.kwargs["shell"])
        self.assertEqual(run_mock.call_args.args[0][0], "gh")

    @patch("tools.github.shutil.which", return_value=None)
    def test_missing_gh_is_reported_without_exception(self, _which):
        result = self.tool.run({"action": "repo_view", "repo": "owner/project"})
        self.assertIn("GITHUB_STATUS: ERROR", result)
        self.assertIn("not installed", result)

    def test_verifier_requires_zero_exit_code(self):
        verifier = Verifier(tools=None)
        failed = verifier.verify(
            "github", {"action": "pr_list", "repo": "owner/project"},
            "GITHUB_STATUS: SUCCESS\nExit code: 1\nSTDERR:\npermission denied",
        )
        self.assertEqual(failed.status, "failed")
        success = verifier.verify(
            "github", {"action": "pr_list", "repo": "owner/project"},
            "GITHUB_STATUS: SUCCESS\nExit code: 0\nOUTPUT:\n[]",
        )
        self.assertTrue(success.confirmed())


if __name__ == "__main__":
    unittest.main()
