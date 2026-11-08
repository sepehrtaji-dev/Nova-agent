"""Small GitHub REST client authenticated as the NoviqX installation."""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from integrations.noviqx.auth import GitHubAppAuth

_REPO_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


class GitHubAPIError(RuntimeError):
    """A sanitized GitHub REST API error."""


class NoviqXGitHub:
    def __init__(self, auth=None, *, opener=None):
        self.auth = auth or GitHubAppAuth()
        self._opener = opener or urllib.request.urlopen

    @staticmethod
    def _repo(repo):
        parts = str(repo).split("/")
        if len(parts) != 2 or not all(_REPO_PART.fullmatch(p) for p in parts):
            raise ValueError("repo must be owner/name.")
        if any(p in {".", ".."} for p in parts):
            raise ValueError("repo must be owner/name.")
        return "/".join(parts)

    def request(self, method, path, *, payload=None, query=None):
        if not path.startswith("/") or path.startswith("//") or ".." in path.split("/"):
            raise ValueError("Invalid GitHub API path.")
        url = self.auth.api_root + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url, data=body, method=method.upper(),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.auth.get_installation_token()}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "Nova-NoviqX-MCP",
            },
        )
        try:
            with self._opener(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:
            raise GitHubAPIError(f"GitHub API request failed with HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise GitHubAPIError(
                f"GitHub API request failed ({type(exc).__name__})."
            ) from exc

    def get_repository(self, repo):
        return self.request("GET", f"/repos/{self._repo(repo)}")

    def list_issues(self, repo, state="open", limit=10):
        if state not in {"open", "closed", "all"}:
            raise ValueError("state must be open, closed, or all.")
        return self.request("GET", f"/repos/{self._repo(repo)}/issues",
                            query={"state": state, "per_page": max(1, min(int(limit), 50))})

    def get_pull_request(self, repo, number):
        if int(number) < 1:
            raise ValueError("number must be positive.")
        return self.request("GET", f"/repos/{self._repo(repo)}/pulls/{int(number)}")

    def list_workflow_runs(self, repo, limit=10):
        return self.request("GET", f"/repos/{self._repo(repo)}/actions/runs",
                            query={"per_page": max(1, min(int(limit), 50))})

    def create_branch(self, repo, branch, from_branch="main"):
        safe_repo = self._repo(repo)
        if not branch or branch.startswith("-") or ".." in branch or " " in branch:
            raise ValueError("Invalid branch name.")
        source_ref = urllib.parse.quote(from_branch, safe="")
        source = self.request("GET", f"/repos/{safe_repo}/git/ref/heads/{source_ref}")
        sha = source.get("object", {}).get("sha")
        if not isinstance(sha, str):
            raise GitHubAPIError("GitHub did not return the source branch SHA.")
        return self.request("POST", f"/repos/{safe_repo}/git/refs",
                            payload={"ref": f"refs/heads/{branch}", "sha": sha})

    def create_issue(self, repo, title, body=""):
        if not title.strip():
            raise ValueError("Issue title cannot be empty.")
        return self.request("POST", f"/repos/{self._repo(repo)}/issues",
                            payload={"title": title[:256], "body": body[:60000]})

    def create_pull_request(self, repo, title, head, base="main", body=""):
        if not title.strip() or not head.strip() or not base.strip():
            raise ValueError("title, head, and base are required.")
        return self.request("POST", f"/repos/{self._repo(repo)}/pulls",
                            payload={"title": title[:256], "head": head, "base": base,
                                     "body": body[:60000], "draft": True})

    def put_file(self, repo, path, content, message, branch):
        safe_repo = self._repo(repo)
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError("path must be a safe repository-relative path.")
        if not message.strip() or not branch.strip():
            raise ValueError("message and branch are required.")
        encoded_path = urllib.parse.quote(path, safe="/")
        endpoint = f"/repos/{safe_repo}/contents/{encoded_path}"
        # Contents API requires the current blob SHA when replacing a file.
        existing = None
        try:
            existing = self.request("GET", endpoint, query={"ref": branch})
        except GitHubAPIError as exc:
            if "HTTP 404" not in str(exc):
                raise
        payload = {"message": message[:256],
                   "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                   "branch": branch}
        if isinstance(existing, dict) and isinstance(existing.get("sha"), str):
            payload["sha"] = existing["sha"]
        return self.request("PUT", endpoint, payload=payload)
