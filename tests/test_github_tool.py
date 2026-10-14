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

    def test_code_search_query_cannot_be_parsed_as_a_flag(self):
        """Regression: a query starting with "-" was passed straight to gh.

        Model-supplied text could therefore change which command gh ran
        (e.g. "--help") instead of being searched for. "--" ends option parsing.
        """
        from tools.github import GitHubTool

        tool = GitHubTool()
        args = tool._build_args(
            {"action": "code_search", "repo": "a/b", "query": "--help"}
        )
        self.assertIn("--", args)
        separator = args.index("--")
        self.assertEqual(args[separator + 1], "--help")
        # The query must sit after the separator, not before it.
        self.assertLess(args.index("search"), separator)

    def test_code_search_rejects_empty_query(self):
        from tools.github import GitHubTool

        tool = GitHubTool()
        with self.assertRaises(ValueError):
            tool._build_args(
                {"action": "code_search", "repo": "a/b", "query": "   "}
            )

    def test_write_actions_are_not_supported(self):
        from tools.github import GitHubTool

        tool = GitHubTool()
        for action in (
            "delete_repo",
            "repo_create",
            "issue_create",
            "pr_merge",
            "push",
        ):
            with self.assertRaises(ValueError, msg=action):
                tool._build_args({"action": action, "repo": "a/b"})

    def test_repo_is_strictly_validated(self):
        from tools.github import GitHubTool

        tool = GitHubTool()
        for repo in (
            "../../etc",
            "a/b/c",
            "a;rm -rf /",
            "",
            "a b/c",
            "a/..",
        ):
            with self.assertRaises(ValueError, msg=repo):
                tool._build_args({"action": "repo_view", "repo": repo})

    def test_limit_is_clamped(self):
        from tools.github import GitHubTool

        tool = GitHubTool()
        high = tool._build_args(
            {"action": "issue_list", "repo": "a/b", "limit": 9999}
        )
        self.assertIn("20", high)
        low = tool._build_args(
            {"action": "issue_list", "repo": "a/b", "limit": -5}
        )
        self.assertIn("1", low)


if __name__ == "__main__":
    unittest.main()
