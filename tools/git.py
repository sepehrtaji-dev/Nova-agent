import subprocess
import os
import json
import sys
import urllib.request
import urllib.error
import shutil
import re


class GitTool:
    """
    Git tool for Nova agent.
    Supports: init, clone, status, add, commit, push, pull,
              log, diff, branch, checkout, create_branch, stash
    All operations run inside the projects workspace by default,
    or an absolute path the user supplies.
    """

    def __init__(self):
        self.base_path = os.path.abspath(os.getcwd())
        self.projects_path = os.path.abspath(
            os.path.join(self.base_path, "projects")
        )
        os.makedirs(self.projects_path, exist_ok=True)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolve_repo_path(self, path=None):
        """Resolve the repo path — default to projects/."""
        if not path:
            return self.projects_path

        path = str(path).strip()

        root = os.path.realpath(self.projects_path)

        # Absolute path supplied — must be within workspace
        if os.path.isabs(path):
            full = os.path.abspath(path)
            try:
                resolved = os.path.realpath(full)
                if os.path.commonpath([root, resolved]) != root:
                    raise ValueError(
                        f"Git path escapes projects workspace or traverses a symlink: {path!r}"
                    )
            except ValueError as exc:
                raise ValueError(str(exc))
            return resolved

        # Relative paths stay inside Nova's projects workspace.
        full = os.path.abspath(os.path.join(root, path))

        try:
            # Validate the destination itself and its nearest existing parent
            # so a symlink cannot redirect Git outside the workspace.
            parent_real = os.path.realpath(os.path.dirname(full))
            candidate_real = os.path.realpath(full)
            if os.path.commonpath([root, parent_real]) != root:
                raise ValueError(
                    f"Git path escapes projects workspace: {path!r}"
                )
            if os.path.exists(full) and os.path.commonpath([root, candidate_real]) != root:
                raise ValueError(
                    f"Git path escapes projects workspace through a symlink: {path!r}"
                )
        except ValueError as exc:
            raise ValueError(str(exc))

        return full

    def _run_git(self, args, cwd):
        """Run a git command and return structured output."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace",
            )

            parts = [
                f"Command: git {' '.join(args)}",
                f"Directory: {cwd}",
                f"Exit code: {result.returncode}",
            ]

            if result.stdout.strip():
                parts.append(f"OUTPUT:\n{result.stdout.strip()}")

            if result.stderr.strip():
                parts.append(f"STDERR:\n{result.stderr.strip()}")

            if result.returncode == 0:
                parts.append("STATUS: SUCCESS")
            else:
                parts.append("STATUS: ERROR")

            return "\n".join(parts)

        except subprocess.TimeoutExpired:
            return "STATUS: ERROR\nGit command timed out after 60 seconds."
        except FileNotFoundError:
            return (
                "STATUS: ERROR\n"
                "Git is not installed or not in PATH.\n"
                "Install git: https://git-scm.com/downloads"
            )
        except ValueError as e:
            return f"STATUS: ERROR\n{e}"
        except Exception as e:
            return f"STATUS: ERROR\nGit error: {type(e).__name__}: {e}"

    def _parse_input(self, input_data):
        """Parse JSON or plain string input."""
        if isinstance(input_data, dict):
            return input_data

        if not isinstance(input_data, str):
            return {}

        try:
            data = json.loads(input_data.strip())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        return {"action": input_data.strip()}

    # ── Blocked operations ────────────────────────────────────────────────────

    BLOCKED = {
        "reset --hard HEAD~",
        "clean -fd",
        "filter-branch",
        "gc --prune=all",
    }

    def _is_blocked(self, args):
        normalized = [str(arg).strip().lower() for arg in args]
        command = " ".join(normalized)

        if normalized and normalized[0] == "push":
            force_flags = {"--force", "--force-with-lease", "-f"}
            if any(flag in force_flags for flag in normalized[1:]):
                return True, "force push"

        for blocked in self.BLOCKED:
            if blocked in command:
                return True, blocked

        return False, None

    def _check_gh_cli(self):
        """Check if GitHub CLI (gh) is available."""
        return shutil.which("gh") is not None

    def _run_gh(self, args, cwd=None):
        """Run a gh command and return structured output."""
        try:
            result = subprocess.run(
                ["gh"] + args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace",
            )

            parts = [
                f"Command: gh {' '.join(args)}",
                f"Exit code: {result.returncode}",
            ]

            if result.stdout.strip():
                parts.append(f"OUTPUT:\n{result.stdout.strip()}")

            if result.stderr.strip():
                parts.append(f"STDERR:\n{result.stderr.strip()}")

            if result.returncode == 0:
                parts.append("STATUS: SUCCESS")
            else:
                parts.append("STATUS: ERROR")

            return "\n".join(parts)

        except subprocess.TimeoutExpired:
            return "STATUS: ERROR\nGitHub CLI command timed out after 60 seconds."
        except FileNotFoundError:
            return (
                "STATUS: ERROR\n"
                "GitHub CLI (gh) is not installed or not in PATH.\n"
                "Install: https://cli.github.com/"
            )
        except Exception as e:
            return f"STATUS: ERROR\nGitHub CLI error: {type(e).__name__}: {e}"

    # ── Public run() entry point ──────────────────────────────────────────────

    def run(self, input_data):
        """
        Main entry point. Input is JSON:

        {
            "action": "commit",
            "path": "my_project",       # optional, relative to projects/
            "message": "feat: add X",   # for commit
            "remote": "origin",         # for push/pull
            "branch": "main",           # for checkout/push/pull
            "new_branch": "feature/x",  # for create_branch
            "files": ["a.py", "b.py"],  # for add (omit = add all)
            "url": "https://...",       # for clone
            "n": 10,                    # for log (number of commits)
            "visibility": "public",     # for create_repo (public/private)
            "description": "Repo desc"  # for create_repo
        }

        Supported actions:
            init, clone, status, add, commit, push, pull,
            log, diff, branch, checkout, create_branch, stash,
            create_repo
        """
        data = self._parse_input(input_data)

        action = str(data.get("action", "")).strip().lower()
        path   = data.get("path")
        cwd    = self._resolve_repo_path(path)

        if not action:
            return "GIT ERROR: 'action' is required."

        # ── create_repo ───────────────────────────────────────────────────────
        if action == "create_repo":
            if not self._check_gh_cli():
                return (
                    "GIT ERROR: GitHub CLI (gh) not found.\n"
                    "Install it from https://cli.github.com/ and run 'gh auth login'"
                )

            name = data.get("name", "").strip()
            if not name:
                return "GIT ERROR: 'name' is required for create_repo."

            visibility = data.get("visibility", "public").strip().lower()
            if visibility not in ("public", "private"):
                visibility = "public"

            description = data.get("description", "").strip()

            # Create repo on GitHub
            args = ["repo", "create", name, f"--{visibility}"]
            if description:
                args.extend(["--description", description])

            # Clone it locally after creation. Use only the repository
            # basename so owner/repository cannot escape the workspace.
            clone_name = str(name).replace("\\", "/").rstrip("/").split("/")[-1]
            if not clone_name or clone_name in {".", ".."}:
                return "GIT ERROR: invalid repository name."
            clone_path = os.path.join(self.projects_path, clone_name)

            # Create repo first (without --clone)
            result = self._run_gh(args, self.projects_path)

            if "STATUS: SUCCESS" not in result:
                return result

            # Now clone the repo
            # Get the repo URL from the output or construct it
            # gh repo create outputs something like: https://github.com/user/repo.git
            import re
            url_match = re.search(r'(https?://github\.com/[^/\s]+/[^/\s]+)', result)
            if not url_match:
                # Fallback 1: try gh repo view with --json url
                view_result = self._run_gh(
                    ["repo", "view", name, "--json", "url", "--jq", ".url"],
                    self.projects_path,
                )
                if "STATUS: SUCCESS" in view_result:
                    match = re.search(r"OUTPUT:\s*\n(https?://\S+)", view_result)
                    if match:
                        repo_url = match.group(1).strip()
                    else:
                        # Fallback 2: try gh repo view with --json sshUrl
                        view_result2 = self._run_gh(
                            ["repo", "view", name, "--json", "sshUrl", "--jq", ".sshUrl"],
                            self.projects_path,
                        )
                        if "STATUS: SUCCESS" in view_result2:
                            match2 = re.search(r"OUTPUT:\s*\n(git@\S+)", view_result2)
                            if match2:
                                repo_url = match2.group(1).strip()
                            else:
                                return result + "\n\nRepository created, but its clone URL could not be verified."
                        else:
                            return result + "\n\nRepository created, but its clone URL could not be verified."
                else:
                    # Fallback 3: try gh repo view with plain text output
                    view_result3 = self._run_gh(
                        ["repo", "view", name],
                        self.projects_path,
                    )
                    if "STATUS: SUCCESS" in view_result3:
                        match3 = re.search(r'(https?://\S+)', view_result3)
                        if match3:
                            repo_url = match3.group(1).strip()
                        else:
                            return result + "\n\nRepository created, but its clone URL could not be verified."
                    else:
                        return result + "\n\nRepository created, but its clone URL could not be verified."
            else:
                repo_url = url_match.group(1)

            clone_result = self._run_git(["clone", repo_url, clone_path], self.projects_path)

            if "STATUS: SUCCESS" in clone_result:
                return result + "\n\n" + clone_result + "\n\nRepository created on GitHub and cloned locally."
            else:
                return result + f"\n\nRepository created on GitHub. Clone it with:\ngit clone {repo_url} {clone_path}"

        # ── init ──────────────────────────────────────────────────────────
        if action == "init":
            os.makedirs(cwd, exist_ok=True)
            return self._run_git(["init"], cwd)

        # ── clone ─────────────────────────────────────────────────────────
        if action == "clone":
            url = data.get("url", "").strip()
            if not url:
                return "GIT ERROR: 'url' is required for clone."

            # Only allow safe URL schemes
            allowed_schemes = ("https://", "git://")
            if not url.lower().startswith(allowed_schemes):
                return (
                    "GIT ERROR: clone URL must use https:// or git:// scheme. "
                    f"Got: {url[:50]!r}"
                )

            dest_name = data.get("dest") or url.rstrip("/").split("/")[-1].replace(".git", "")
            dest_name = os.path.basename(str(dest_name).replace("\\", "/"))
            if not dest_name or dest_name in {".", ".."}:
                return "GIT ERROR: invalid clone destination."
            dest_path = os.path.join(self.projects_path, dest_name)

            return self._run_git(["clone", url, dest_path], self.projects_path)

        # ── status ────────────────────────────────────────────────────────
        if action == "status":
            return self._run_git(["status"], cwd)

        # ── add ───────────────────────────────────────────────────────────
        if action == "add":
            files = data.get("files")
            if isinstance(files, list) and files:
                args = ["add"] + [str(f) for f in files]
            else:
                args = ["add", "."]
            return self._run_git(args, cwd)

        # ── commit ────────────────────────────────────────────────────────
        if action == "commit":
            message = data.get("message", "").strip()
            if not message:
                return "GIT ERROR: 'message' is required for commit."

            blocked, reason = self._is_blocked(["commit", "-m", message])
            if blocked:
                return f"GIT ERROR: Blocked operation: {reason}"

            return self._run_git(["commit", "-m", message], cwd)

        # ── push ──────────────────────────────────────────────────────────
        if action == "push":
            remote = data.get("remote", "origin")
            branch = data.get("branch", "")
            args   = ["push", remote]
            if branch:
                args.append(branch)

            blocked, reason = self._is_blocked(args)
            if blocked:
                return f"GIT ERROR: Blocked operation: {reason}"

            return self._run_git(args, cwd)

        # ── pull ──────────────────────────────────────────────────────────
        if action == "pull":
            remote = data.get("remote", "origin")
            branch = data.get("branch", "")
            args   = ["pull", remote]
            if branch:
                args.append(branch)
            return self._run_git(args, cwd)

        # ── log ───────────────────────────────────────────────────────────
        if action == "log":
            n    = int(data.get("n", 10))
            n    = min(max(n, 1), 100)
            args = [
                "log",
                f"-{n}",
                "--pretty=format:%h  %an  %ad  %s",
                "--date=short"
            ]
            return self._run_git(args, cwd)

        # ── diff ──────────────────────────────────────────────────────────
        if action == "diff":
            file_ = data.get("file")
            args  = ["diff"]
            if file_:
                args.append(str(file_))
            return self._run_git(args, cwd)

        # ── branch ───────────────────────────────────────────────────────
        if action == "branch":
            return self._run_git(["branch", "-a"], cwd)

        # ── checkout ─────────────────────────────────────────────────────
        if action == "checkout":
            branch = data.get("branch", "").strip()
            if not branch:
                return "GIT ERROR: 'branch' is required for checkout."
            return self._run_git(["checkout", branch], cwd)

        # ── create_branch ─────────────────────────────────────────────────
        if action == "create_branch":
            new_branch = data.get("new_branch", "").strip()
            if not new_branch:
                return "GIT ERROR: 'new_branch' is required for create_branch."
            return self._run_git(["checkout", "-b", new_branch], cwd)

        # ── stash ─────────────────────────────────────────────────────────
        if action == "stash":
            sub = data.get("sub", "push").strip().lower()
            if sub == "push":
                return self._run_git(["stash", "push"], cwd)
            if sub == "pop":
                return self._run_git(["stash", "pop"], cwd)
            if sub == "list":
                return self._run_git(["stash", "list"], cwd)
            return f"GIT ERROR: Unknown stash sub-action: {sub}"

        # ── unknown ───────────────────────────────────────────────────────
        return (
            f"GIT ERROR: Unknown action '{action}'.\n"
            "Supported: init, clone, status, add, commit, push, pull, "
            "log, diff, branch, checkout, create_branch, stash"
        )
