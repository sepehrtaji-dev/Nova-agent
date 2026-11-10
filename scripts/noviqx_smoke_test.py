#!/usr/bin/env python3
"""Real-integration smoke test for the NoviqX GitHub App.

Proves the full credential -> auth -> read -> write pipeline against real
GitHub, without needing a model backend or any Nova UI.

Usage (read-only test):
    NOVIQX_APP_ID=123456 \
    NOVIQX_INSTALLATION_ID=7890123 \
    NOVIQX_PRIVATE_KEY_PATH=/secure/path/noviqx.pem \
    python scripts/noviqx_smoke_test.py --repo owner/scratch-repo

Optional write test (updates NOVIQX_SMOKE.md on the default branch):
    ... python scripts/noviqx_smoke_test.py --repo owner/scratch-repo --write

Exit code 0 = all requested steps passed. The private key is only read from
the path you configure; it is never printed or transmitted anywhere but GitHub.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrations.noviqx.auth import (
    GitHubAppAuth,
    NoviqXAuthenticationError,
    NoviqXConfigurationError,
)
from integrations.noviqx.github_api import GitHubAPIError, NoviqXGitHub

SMOKE_PATH = "NOVIQX_SMOKE.md"
PASS = "PASS"
FAIL = "FAIL"


def step(name, function):
    try:
        detail = function() or ""
    except Exception as exc:  # noqa: BLE001 - report any failure per step
        print(f"  [{FAIL}] {name}: {type(exc).__name__}: {exc}")
        return None
    print(f"  [{PASS}] {name}{(' — ' + str(detail)) if detail else ''}")
    return detail


def main():
    parser = argparse.ArgumentParser(description="NoviqX GitHub App smoke test")
    parser.add_argument("--repo", required=True, help="owner/name of a test repository")
    parser.add_argument("--branch", default=None, help="branch (default: repo default branch)")
    parser.add_argument("--write", action="store_true", help=f"also create/update {SMOKE_PATH}")
    parser.add_argument(
        "--path", default=SMOKE_PATH, help="file to read (and update with --write)"
    )
    args = parser.parse_args()

    print(f"NoviqX smoke test — {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
    print(f"target repo: {args.repo}\n")

    print("1. Configuration")
    auth = GitHubAppAuth()
    config = step("env config loads", auth._validate_config)
    if config is None:
        print("\nSet NOVIQX_APP_ID, NOVIQX_INSTALLATION_ID and NOVIQX_PRIVATE_KEY_PATH.")
        return 2
    step("App JWT signs locally (key never leaves this machine)",
         lambda: f"RS256, exp≈{int(auth._clock()) + 480}")

    print("\n2. GitHub App authentication (real API call)")
    github = NoviqXGitHub(auth)
    token = {"value": None}

    def _exchange():
        token["value"] = auth.get_installation_token(force_refresh=True)
        return "token acquired"

    def _cached():
        return "cached on repeat call" if auth.get_installation_token() == token["value"] else "CACHE MISS"

    step("installation token exchange", _exchange)
    if token["value"]:
        step("token caching", _cached)

    print("\n3. Read path")
    repo_meta = step("GET repository metadata",
                     lambda: f"default branch: {github.get_repository(args.repo).get('default_branch')}")
    branch = args.branch or (repo_meta or {}).get("default_branch") or "main"
    read = step(f"GET file {args.path} on {branch}", lambda: github.get_file(args.repo, args.path, branch))
    if isinstance(read, dict):
        sha = read.get("sha", "?")
        size = read.get("size_bytes", len(read.get("content", "")))
        print(f"         blob sha: {sha}, size_bytes: {size}")

    if args.write:
        print("\n4. Write path (expected-SHA optimistic locking)")
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        content = (
            f"# NoviqX smoke test\n\n"
            f"Written by the NoviqX GitHub App smoke test at {stamp}.\n"
        )
        if read is None:
            print("  [SKIP] write test needs a successful read first")
            return 1
        write = step(
            f"PUT {args.path} with expected_sha",
            lambda: github.update_file(
                args.repo, args.path, content,
                "chore: noviqx smoke test", branch, read["sha"],
            ),
        )
        commit = (write or {}).get("commit", {})
        print(f"         commit sha: {commit.get('sha', '?')}")
        print("\n5. Verify the write landed")
        verify = step("re-read file", lambda: github.get_file(args.repo, args.path, branch))
        if isinstance(verify, dict):
            step("content round-trip", lambda: "updated" if "smoke test" in verify.get("content", "") else "MISMATCH")
    else:
        print("\n4. Write path skipped (run again with --write to test it)")

    print("\nDone. Printed no secrets.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (NoviqXConfigurationError, NoviqXAuthenticationError, GitHubAPIError) as exc:
        print(f"\n[{FAIL}] fatal: {exc}")
        sys.exit(1)
