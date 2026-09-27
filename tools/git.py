import subprocess
import os
import json
import sys


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

        # Absolute path supplied
        if os.path.isabs(path):
            return os.path.abspath(path)

        # Relative to projects/
        full = os.path.abspath(os.path.join(self.projects_path, path))
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
        "push --force",
        "push -f",
        "reset --hard HEAD~",
        "clean -fd",
        "filter-branch",
        "gc --prune=all",
    }

    def _is_blocked(self, args):
        cmd = " ".join(args).lower()
        for b in self.BLOCKED:
            if b in cmd:
                return True, b
        return False, None

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
            "n": 10                     # for log (number of commits)
        }

        Supported actions:
            init, clone, status, add, commit, push, pull,
            log, diff, branch, checkout, create_branch, stash
        """
        data = self._parse_input(input_data)

        action = str(data.get("action", "")).strip().lower()
        path   = data.get("path")
        cwd    = self._resolve_repo_path(path)

        if not action:
            return "GIT ERROR: 'action' is required."

        # ── init ──────────────────────────────────────────────────────────
        if action == "init":
            os.makedirs(cwd, exist_ok=True)
            return self._run_git(["init"], cwd)

        # ── clone ─────────────────────────────────────────────────────────
        if action == "clone":
            url = data.get("url", "").strip()
            if not url:
                return "GIT ERROR: 'url' is required for clone."

            dest_name = data.get("dest") or url.rstrip("/").split("/")[-1].replace(".git", "")
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
