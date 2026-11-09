"""ToolRegistry adapter for the NoviqX GitHub App integration.

The MCP stdio server and Nova's native ToolRegistry share the same REST client.
Nova does not launch a second agent or hardcode GitHub-specific routing: the
model selects these registered tools through the normal tool-call loop.
"""
from __future__ import annotations

import json

from integrations.noviqx.github_api import NoviqXGitHub


class NoviqXGitHubTools:
    """Expose bounded GitHub App operations using Nova's existing tool contract."""

    def __init__(self, github=None):
        self.github = github or NoviqXGitHub()

    @staticmethod
    def _parse_input(input_data):
        if isinstance(input_data, dict):
            return dict(input_data)
        if isinstance(input_data, str):
            try:
                parsed = json.loads(input_data)
            except json.JSONDecodeError as exc:
                raise ValueError("Tool input must be a JSON object.") from exc
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("Tool input must be a JSON object.")

    @staticmethod
    def _required_text(data, name):
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string.")
        return value

    def get_file(self, input_data):
        """Input: repo, path, branch. Returns the remote UTF-8 content and blob SHA."""
        data = self._parse_input(input_data)
        repo = self._required_text(data, "repo")
        path = self._required_text(data, "path")
        branch = data.get("branch", "main")
        if not isinstance(branch, str) or not branch.strip():
            raise ValueError("branch must be a non-empty string.")
        result = self.github.get_file(repo, path, branch)
        return json.dumps(result, ensure_ascii=False)

    def update_file(self, input_data):
        """Input: repo, path, content, message, branch, expected_sha. Updates only the version read."""
        data = self._parse_input(input_data)
        repo = self._required_text(data, "repo")
        path = self._required_text(data, "path")
        content = data.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string.")
        message = self._required_text(data, "message")
        branch = self._required_text(data, "branch")
        expected_sha = self._required_text(data, "expected_sha")

        result = self.github.put_file(
            repo, path, content, message, branch, expected_sha=expected_sha
        )
        commit = result.get("commit") if isinstance(result, dict) else {}
        file_data = result.get("content") if isinstance(result, dict) else {}
        return json.dumps({
            "path": path,
            "branch": branch,
            "commit_sha": commit.get("sha") if isinstance(commit, dict) else None,
            "content_sha": file_data.get("sha") if isinstance(file_data, dict) else None,
            "html_url": file_data.get("html_url") if isinstance(file_data, dict) else None,
        }, ensure_ascii=False)
