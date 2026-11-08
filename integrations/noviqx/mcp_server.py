"""Local stdio MCP server for NoviqX GitHub operations.

Run: python -m integrations.noviqx.mcp_server
Install: python -m pip install -r requirements-noviqx.txt
"""
import json
from mcp.server.fastmcp import FastMCP

from integrations.noviqx.github_api import NoviqXGitHub

mcp = FastMCP("NoviqX GitHub")
github = NoviqXGitHub()


@mcp.tool()
def github_get_repository(repo: str) -> str:
    """Read repository metadata. repo must be owner/name."""
    return json.dumps(github.get_repository(repo), ensure_ascii=False)


@mcp.tool()
def github_list_issues(repo: str, state: str = "open", limit: int = 10) -> str:
    """List repository issues. state: open, closed, or all."""
    return json.dumps(github.list_issues(repo, state, limit), ensure_ascii=False)


@mcp.tool()
def github_get_pull_request(repo: str, number: int) -> str:
    """Read one pull request by number."""
    return json.dumps(github.get_pull_request(repo, number), ensure_ascii=False)


@mcp.tool()
def github_list_workflow_runs(repo: str, limit: int = 10) -> str:
    """Read recent Actions runs; this tool does not edit workflow files."""
    return json.dumps(github.list_workflow_runs(repo, limit), ensure_ascii=False)


@mcp.tool()
def github_create_branch(repo: str, branch: str, from_branch: str = "main") -> str:
    """Create a branch from an existing branch."""
    return json.dumps(github.create_branch(repo, branch, from_branch), ensure_ascii=False)


@mcp.tool()
def github_create_issue(repo: str, title: str, body: str = "") -> str:
    """Create a GitHub issue."""
    return json.dumps(github.create_issue(repo, title, body), ensure_ascii=False)


@mcp.tool()
def github_create_pull_request(repo: str, title: str, head: str,
                               base: str = "main", body: str = "") -> str:
    """Create a draft pull request from head into base."""
    return json.dumps(github.create_pull_request(repo, title, head, base, body),
                      ensure_ascii=False)


@mcp.tool()
def github_put_file(repo: str, path: str, content: str,
                    message: str, branch: str) -> str:
    """Create or update a repository file on a branch."""
    return json.dumps(github.put_file(repo, path, content, message, branch),
                      ensure_ascii=False)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
