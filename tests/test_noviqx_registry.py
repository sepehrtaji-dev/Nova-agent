"""Tests for Nova's ToolRegistry-facing NoviqX GitHub tools."""
import json
import unittest

from agent.verifier import Verifier
from integrations.noviqx.registry_tools import NoviqXGitHubTools
from tools.registry import ToolRegistry


class FakeGitHub:
    def __init__(self):
        self.updated = None

    def get_file(self, repo, path, branch):
        return {
            "path": path,
            "sha": "blob-sha",
            "content": "2.1\\n",
            "html_url": f"https://github.com/{repo}/blob/{branch}/{path}",
        }

    def put_file(self, repo, path, content, message, branch, expected_sha=None):
        self.updated = {
            "repo": repo,
            "path": path,
            "content": content,
            "message": message,
            "branch": branch,
            "expected_sha": expected_sha,
        }
        return {
            "commit": {"sha": "0123456789abcdef0123456789abcdef01234567"},
            "content": {"sha": "new-blob-sha"},
        }

    def get_commit(self, repo, commit_sha):
        return {"author": {"login": "noviqx[bot]"}}


class TestNoviqXRegistryTools(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.adapter = NoviqXGitHubTools(github=self.github)

    def test_get_file_returns_remote_content_and_sha(self):
        result = json.loads(self.adapter.get_file({
            "repo": "sepehrtaji-dev/Nova-agent",
            "path": "version.txt",
            "branch": "main",
        }))
        self.assertEqual(result["content"], "2.1\\n")
        self.assertEqual(result["sha"], "blob-sha")

    def test_update_file_passes_expected_sha_and_returns_commit(self):
        result = json.loads(self.adapter.update_file({
            "repo": "sepehrtaji-dev/Nova-agent",
            "path": "version.txt",
            "content": "2.2\\n",
            "message": "Bump version to 2.2",
            "branch": "main",
            "expected_sha": "blob-sha",
        }))
        self.assertEqual(self.github.updated["expected_sha"], "blob-sha")
        self.assertEqual(result["commit_sha"], "0123456789abcdef0123456789abcdef01234567")

    def test_update_file_requires_expected_sha(self):
        with self.assertRaises(ValueError):
            self.adapter.update_file({
                "repo": "sepehrtaji-dev/Nova-agent",
                "path": "version.txt",
                "content": "2.2\\n",
                "message": "Bump version to 2.2",
                "branch": "main",
            })

    def test_verifier_confirms_remote_content_and_bot_author(self):
        registry = ToolRegistry()
        registry.register(
            "noviqx_github_update_file",
            "Update remote GitHub file",
            self.adapter.update_file,
            capability="git",
            verifier_method="_verify_noviqx_github_update_file",
        )
        verifier = Verifier(registry)
        tool_input = {
            "repo": "sepehrtaji-dev/Nova-agent",
            "path": "version.txt",
            "content": "2.2\\n",
            "message": "Bump version to 2.2",
            "branch": "main",
            "expected_sha": "blob-sha",
        }
        result_payload = self.adapter.update_file(tool_input)
        result = verifier.verify(
            "noviqx_github_update_file",
            json.dumps(tool_input),
            result_payload,
        )
        self.assertTrue(result.confirmed(), result.message)
        self.assertIn("noviqx[bot]", result.evidence)


if __name__ == "__main__":
    unittest.main()
