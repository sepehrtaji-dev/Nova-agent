"""Read-only GitHub operations through the locally authenticated GitHub CLI."""
from __future__ import annotations

import json
import re
import shutil
import subprocess


class GitHubTool:
    """Expose bounded, read-only GitHub queries; this tool never mutates remotes."""

    _ACTIONS = {
        "repo_view",
        "issue_list",
        "issue_view",
        "pr_list",
        "pr_view",
        "run_list",
        "release_list",
        "code_search",
    }

    def _parse_input(self, input_data):
        if isinstance(input_data, dict):
            return dict(input_data)
        if not isinstance(input_data, str):
            return {}
        try:
            value = json.loads(input_data.strip())
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _build_args(self, data):
        action = str(data.get("action", "")).strip().lower()
        repo = str(data.get("repo", "")).strip()
        if action not in self._ACTIONS:
            raise ValueError(
                f"Unsupported read-only GitHub action {action!r}. "
                f"Supported actions: {', '.join(sorted(self._ACTIONS))}."
            )
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("repo must be an owner/name GitHub repository.")
        limit = data.get("limit", 10)
        try:
            limit = max(1, min(20, int(limit)))
        except (TypeError, ValueError):
            limit = 10

        if action == "repo_view":
            return ["repo", "view", repo, "--json", "name,description,url,visibility,defaultBranchRef"]
        if action == "issue_list":
            state = str(data.get("state", "open")).lower()
            if state not in {"open", "closed", "all"}:
                raise ValueError("issue_list state must be open, closed, or all.")
            return ["issue", "list", "--repo", repo, "--state", state, "--limit", str(limit),
                    "--json", "number,title,state,url,labels,assignees"]
        if action == "issue_view":
            number = data.get("number")
            if not str(number).isdigit() or int(number) < 1:
                raise ValueError("issue_view requires a positive issue number.")
            return ["issue", "view", str(int(number)), "--repo", repo,
                    "--json", "number,title,state,body,url,labels,assignees,comments"]
        if action == "pr_list":
            state = str(data.get("state", "open")).lower()
            if state not in {"open", "closed", "merged", "all"}:
                raise ValueError("pr_list state must be open, closed, merged, or all.")
            return ["pr", "list", "--repo", repo, "--state", state, "--limit", str(limit),
                    "--json", "number,title,state,url,headRefName,baseRefName,isDraft"]
        if action == "pr_view":
            number = data.get("number")
            if not str(number).isdigit() or int(number) < 1:
                raise ValueError("pr_view requires a positive pull-request number.")
            return ["pr", "view", str(int(number)), "--repo", repo,
                    "--json", "number,title,state,body,url,headRefName,baseRefName,isDraft,mergeStateStatus"]
        if action == "run_list":
            return ["run", "list", "--repo", repo, "--limit", str(limit),
                    "--json", "databaseId,name,status,conclusion,headBranch,url,createdAt"]
        if action == "release_list":
            return ["release", "list", "--repo", repo, "--limit", str(limit)]
        if action == "code_search":
            query = str(data.get("query", "")).strip()
            if not query:
                raise ValueError("code_search requires a non-empty query.")
            return ["search", "code", query, "--repo", repo, "--limit", str(limit),
                    "--json", "path,repository,url"]
        raise ValueError("Unsupported GitHub action.")

    def run(self, input_data):
        data = self._parse_input(input_data)
        try:
            args = self._build_args(data)
        except (ValueError, TypeError) as exc:
            return f"GITHUB_STATUS: ERROR\nGITHUB_ERROR: {exc}"

        if shutil.which("gh") is None:
            return (
                "GITHUB_STATUS: ERROR\n"
                "GitHub CLI (gh) is not installed or not in PATH. "
                "Install GitHub CLI and run 'gh auth login'."
            )

        try:
            result = subprocess.run(
                ["gh", *args],
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return "GITHUB_STATUS: ERROR\nGitHub CLI timed out after 30 seconds."
        except OSError as exc:
            return f"GITHUB_STATUS: ERROR\n{type(exc).__name__}: {exc}"

        status = "SUCCESS" if result.returncode == 0 else "ERROR"
        parts = [
            f"GITHUB_STATUS: {status}",
            f"Exit code: {result.returncode}",
            f"Action: {data.get('action', '')}",
            f"Repository: {data.get('repo', '')}",
        ]
        if result.stdout:
            parts.append("OUTPUT:\n" + result.stdout[:20000].strip())
        if result.stderr:
            parts.append("STDERR:\n" + result.stderr[:4000].strip())
        return "\n".join(parts)
