"""
Nova Verifier
─────────────
After every tool call, this module performs a real verification step.
It does not trust the tool's own success marker alone — it re-checks
with an independent method wherever possible.

Verification results:
    status   : "confirmed" | "failed" | "unverifiable"
    evidence : what was actually observed
    message  : human-readable explanation shown to the user
"""

import json
import os
import subprocess
import re
from urllib.parse import urlsplit


class VerificationResult:
    def __init__(self, status, evidence, message):
        # status: "confirmed" | "failed" | "unverifiable"
        self.status   = status
        self.evidence = evidence
        self.message  = message

    def confirmed(self):
        return self.status == "confirmed"

    def failed(self):
        return self.status == "failed"

    def __str__(self):
        return (
            f"[{self.status.upper()}] {self.message}"
        )

    def to_dict(self):
        return {
            "status":   self.status,
            "evidence": self.evidence,
            "message":  self.message,
        }


class Verifier:
    """
    Verifies that a tool call actually did what it claimed.
    Each verify_* method accepts the tool input dict and the
    raw tool result string, then returns a VerificationResult.
    """

    def __init__(self, tools):
        # tools: the ToolRegistry instance from load_tools()
        self.tools = tools

    # ── Public entry point ────────────────────────────────────────────────────
    def _resolve_path_for_verification(self, tool_input):
        path = str(tool_input.get("path", "")).strip()
        location = str(tool_input.get("location", "projects")).strip().lower()

        if not path:
            return None

        if location == "system":
            return os.path.abspath(path) if os.path.isabs(path) else None

        roots = {
            "projects": os.path.abspath(os.path.join(os.getcwd(), "projects")),
            "desktop": os.path.abspath(os.path.join(os.path.expanduser("~"), "Desktop")),
        }
        root = roots.get(location)
        if root is None:
            return None

        root = os.path.realpath(root)
        actual_path = os.path.abspath(os.path.join(root, path))
        resolved_path = os.path.realpath(actual_path)
        try:
            common = os.path.commonpath([root, resolved_path])
        except ValueError:
            return None
        # Keep the lexical absolute path returned by FileSystemTool so the
        # verifier compares the same path the tool reports. The canonical path
        # above is still used to reject symlink escapes.
        return actual_path if common == root else None


    def verify(self, tool_name, tool_input_str, tool_result):
        """
        Dispatch to the correct verifier.
        Returns a VerificationResult.
        """
        if isinstance(tool_input_str, dict):
            tool_input = tool_input_str
        else:
            try:
                tool_input = json.loads(tool_input_str)
                if not isinstance(tool_input, dict):
                    tool_input = {}
            except (json.JSONDecodeError, TypeError):
                tool_input = {}

        if tool_result is None:
            tool_result = ""
        elif isinstance(tool_result, bytes):
            tool_result = tool_result.decode("utf-8", errors="replace")
        else:
            tool_result = str(tool_result)

        dispatch = {
            "write_file":       self._verify_write_file,
            "read_file":        self._verify_read_file,
            "edit_file":        self._verify_edit_file,
            "delete_file":      self._verify_delete_file,
            "create_directory": self._verify_create_directory,
            "list_files":       self._verify_list_files,
            "find_files":       self._verify_find_files,
            "terminal":         self._verify_terminal,
            "git":              self._verify_git,
            "web_search":       self._verify_web_search,
            "web_fetch":        self._verify_web_fetch,
            "github":            self._verify_github,
            "generate_image":   self._verify_generate_image,
            "desktop":          self._verify_desktop,
        }

        fn = dispatch.get(tool_name)
        if fn is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:200],
                message=f"No verifier for tool '{tool_name}'."
            )

        try:
            return fn(tool_input, tool_result)
        except Exception as exc:
            import logging
            logging.exception("Verifier crashed for '%s'", tool_name)
            return VerificationResult(
                status="unverifiable",
                evidence=str(exc),
                message=f"Verifier crashed for '{tool_name}': {exc}"
            )

    # ── write_file ────────────────────────────────────────────────────────────

    def _verify_write_file(self, tool_input, tool_result):
        """Verify a write against the actual filesystem state and requested content."""
        path = str(tool_input.get("path", "")).strip()
        expected = tool_input.get("content")
        if "FILE_CREATED" not in tool_result:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message=f"write_file did not return FILE_CREATED for '{path}'.",
            )

        actual_path = None
        for line in tool_result.splitlines():
            if line.startswith("Location:"):
                actual_path = line.replace("Location:", "", 1).strip()
                break

        if not actual_path:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="write_file succeeded but reported no concrete path.",
            )

        # BUG 1+2: Validate the reported path matches the requested path
        requested_path = self._resolve_path_for_verification(tool_input)
        if requested_path is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="write_file could not resolve its requested location safely.",
            )
        if os.path.abspath(actual_path) != requested_path:
            return VerificationResult(
                status="failed",
                evidence=f"Tool reported: {actual_path}, Expected: {requested_path}",
                message="write_file reported a different path than requested.",
            )

        if not os.path.isfile(actual_path):
            return VerificationResult(
                status="failed",
                evidence=f"os.path.isfile({actual_path!r}) = False",
                message=f"File does not exist on disk: {actual_path}",
            )

        # BUG 23+28: Wrap getsize in try/except for TOCTOU protection
        try:
            size = os.path.getsize(actual_path)
        except Exception as exc:
            return VerificationResult(
                status="unverifiable",
                evidence=str(exc),
                message=f"Could not get file size for verification: {actual_path}",
            )
        if isinstance(expected, str):
            try:
                with open(actual_path, "r", encoding="utf-8") as handle:
                    actual = handle.read()
            except Exception as exc:
                return VerificationResult(
                    status="unverifiable",
                    evidence=str(exc),
                    message=f"Could not read written file for verification: {actual_path}",
                )
            if actual != expected:
                return VerificationResult(
                    status="failed",
                    evidence=f"Expected {len(expected)} chars, found {len(actual)} chars.",
                    message=f"Written file content does not match the requested content: {actual_path}",
                )
        # BUG 19: Check expected is None separately
        elif expected is None and size == 0:
            return VerificationResult(
                status="failed",
                evidence=f"File size = {size} bytes",
                message=f"File was created but is empty: {actual_path}",
            )

        preview = ""
        try:
            with open(actual_path, "r", encoding="utf-8", errors="replace") as handle:
                preview = handle.read(200)
        except Exception as exc:
            preview = f"(could not read: {exc})"

        return VerificationResult(
            status="confirmed",
            evidence=f"Path: {actual_path}\nSize: {size} bytes\nPreview: {preview!r}",
            message=f"✓ File confirmed on disk: {actual_path} ({size} bytes)",
        )

    def _verify_find_files(self, tool_input, tool_result):
        if "STATUS: ERROR" in tool_result or "FILESYSTEM ERROR" in tool_result or "Permission denied:" in tool_result:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:400],
                message="find_files returned an error.",
            )

        if "STATUS: SUCCESS" not in tool_result or "Match count:" not in tool_result:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:400],
                message="find_files result is missing its success/count evidence.",
            )

        requested_path = self._resolve_path_for_verification(tool_input)
        if requested_path is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="find_files could not resolve its requested location safely.",
            )
        reported_path = None
        for line in tool_result.splitlines():
            if line.startswith("Location:"):
                reported_path = line.split(":", 1)[1].strip()
                break
        if not reported_path:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="find_files did not report the searched directory.",
            )
        if os.path.abspath(reported_path) != requested_path:
            return VerificationResult(
                status="failed",
                evidence=f"Tool reported: {reported_path}, Expected: {requested_path}",
                message="find_files reported a different directory than requested.",
            )
        if not os.path.isdir(requested_path):
            return VerificationResult(
                status="failed",
                evidence=f"Directory does not exist: {requested_path}",
                message="find_files searched a directory that cannot be confirmed.",
            )

        match = re.search(r"Match count:\s*(-?\d+)", tool_result)
        if not match:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:400],
                message="find_files did not report a valid match count.",
            )
        count = int(match.group(1))
        if count < 0:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:900],
                message=f"find_files returned negative count: {count}.",
            )
        if count == 0:
            return VerificationResult(
                status="confirmed",
                evidence=f"Directory: {requested_path}\nMatch count: 0",
                message=f"✓ File search completed: no matching files in {requested_path}.",
            )
        return VerificationResult(
            status="confirmed",
            evidence=tool_result[:900],
            message=f"✓ File search confirmed: {count} matching file(s).",
        )

    # ── read_file ─────────────────────────────────────────────────────────────

    def _verify_read_file(self, tool_input, tool_result):
        """Verify a read by checking the requested file exists on disk."""
        path = str(tool_input.get("path", "")).strip()
        location = str(tool_input.get("location", "projects")).strip().lower()

        error_prefixes = (
            "Filesystem error:",
            "Permission denied:",
            "File does not exist",
            "Path is not a file",
            "File is not a readable text file:",
        )
        if any(prefix in tool_result for prefix in error_prefixes):
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message=f"read_file failed: {tool_result[:120]}",
            )

        actual_path = self._resolve_path_for_verification(tool_input)
        if actual_path is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:200],
                message="read_file could not resolve its requested location safely.",
            )

        if not os.path.isfile(actual_path):
            return VerificationResult(
                status="failed",
                evidence=f"os.path.isfile({actual_path!r}) = False",
                message=f"File could not be confirmed on disk: {actual_path}",
            )

        return VerificationResult(
            status="confirmed",
            evidence=f"Path: {actual_path}\nChars returned: {len(tool_result)}",
            message=f"✓ File read confirmed: {actual_path}",
        )


    # ── create_directory ──────────────────────────────────────────────────────

    def _verify_create_directory(self, tool_input, tool_result):
        """
        1. Check DIRECTORY_CREATED in result.
        2. OS-level check that directory exists.
        """
        if "DIRECTORY_CREATED" not in tool_result:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="create_directory did not return DIRECTORY_CREATED."
            )

        actual_path = None
        for line in tool_result.splitlines():
            if line.startswith("Location:"):
                actual_path = line.replace("Location:", "").strip()
                break

        if not actual_path:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="create_directory succeeded but path not found in result."
            )

        requested_path = self._resolve_path_for_verification(tool_input)
        if requested_path is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="create_directory could not resolve its requested location safely.",
            )
        if os.path.abspath(actual_path) != requested_path:
            return VerificationResult(
                status="failed",
                evidence=f"Tool reported: {actual_path}, Expected: {requested_path}",
                message="create_directory reported a different path than requested.",
            )

        if not os.path.isdir(actual_path):
            return VerificationResult(
                status="failed",
                evidence=f"os.path.isdir({actual_path!r}) = False",
                message=f"Directory does not exist on disk: {actual_path}"
            )

        return VerificationResult(
            status="confirmed",
            evidence=f"Path: {actual_path}",
            message=f"✓ Directory confirmed on disk: {actual_path}"
        )

    # ── list_files ────────────────────────────────────────────────────────────

    def _verify_list_files(self, tool_input, tool_result):
        """Confirm the requested directory was the one actually listed."""
        if any(err in tool_result for err in (
            "Filesystem error:", "Permission denied:", "Path does not exist:", "Not a directory:"
        )):
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message=f"list_files failed: {tool_result[:120]}",
            )

        requested_path = self._resolve_path_for_verification(tool_input)
        if requested_path is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:200],
                message="list_files could not resolve its requested location safely.",
            )

        reported_path = None
        for line in tool_result.splitlines():
            if line.startswith("Location:"):
                reported_path = line.split(":", 1)[1].strip()
                break
            if line.startswith("Directory is empty:"):
                reported_path = line.split(":", 1)[1].strip()
                break
        if not reported_path:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="list_files did not report the listed directory.",
            )
        if os.path.abspath(reported_path) != requested_path:
            return VerificationResult(
                status="failed",
                evidence=f"Tool reported: {reported_path}, Expected: {requested_path}",
                message="list_files reported a different directory than requested.",
            )
        if not os.path.isdir(requested_path):
            return VerificationResult(
                status="failed",
                evidence=f"os.path.isdir({requested_path!r}) = False",
                message=f"Directory could not be confirmed on disk: {requested_path}",
            )
        return VerificationResult(
            status="confirmed",
            evidence=f"Directory: {requested_path}",
            message=f"✓ Directory listing confirmed: {requested_path}",
        )

    # ── terminal ──────────────────────────────────────────────────────────────

    def _verify_terminal(self, tool_input, tool_result):
        """Verify terminal success from an explicit zero exit code."""
        exit_match = re.search(r"^Exit code:\s*(-?\d+)", tool_result, flags=re.MULTILINE)
        status_error = "STATUS: ERROR" in tool_result
        status_success = "STATUS: SUCCESS" in tool_result

        if status_error:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:500],
                message="Terminal command reported a non-success result.",
            )

        if not status_success:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="Terminal result has no STATUS: SUCCESS marker.",
            )

        if exit_match is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:400],
                message="Terminal result did not expose an exit code.",
            )

        exit_code = int(exit_match.group(1))
        if exit_code != 0:
            return VerificationResult(
                status="failed",
                evidence=f"Exit code: {exit_code}\n{tool_result[:300]}",
                message=f"Terminal command failed with exit code {exit_code}.",
            )

        # BUG 10: Make STDOUT parsing more robust
        stdout = ""
        capture = False
        for line in tool_result.splitlines():
            if line.startswith("STDOUT:") or line.startswith("Stdout:") or line.startswith("Output:"):
                capture = True
                continue
            if capture and (line.startswith("STDERR:") or line.startswith("STATUS:")):
                break
            if capture:
                stdout += line + "\n"

        command = str(tool_input.get("command", "(unknown)"))
        return VerificationResult(
            status="confirmed",
            evidence=f"Exit code: 0\n{stdout[:260]}".strip(),
            message=f"✓ Command exited successfully: {command[:80]}",
        )

    # ── git ───────────────────────────────────────────────────────────────────

    def _verify_git(self, tool_input, tool_result):
        """
        1. Check STATUS: SUCCESS.
        2. For clone: check directory was created.
        3. For commit: check commit hash in output.
        4. For push: check output contains remote ref.
        """
        action = tool_input.get("action", "")

        if "STATUS: ERROR" in tool_result:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:400],
                message=f"git {action} failed."
            )

        if "STATUS: SUCCESS" not in tool_result:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message=f"git {action} has no STATUS marker.",
            )

        exit_match = re.search(r"^Exit code:\s*(-?\d+)", tool_result, flags=re.MULTILINE)
        if exit_match is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message=f"git {action} did not expose an exit code.",
            )
        if int(exit_match.group(1)) != 0:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message=f"git {action} reported a non-zero exit code.",
            )

        # Action-specific checks
        if action == "clone":
            url  = tool_input.get("url", "")
            # Derive expected folder name
            dest = url.rstrip("/").split("/")[-1].replace(".git", "")
            # BUG 3: Check destination directory exists and contains .git
            dest_path = os.path.join(os.getcwd(), "projects", dest)
            if os.path.isdir(dest_path) and os.path.isdir(os.path.join(dest_path, ".git")):
                return VerificationResult(
                    status="confirmed",
                    evidence=tool_result[:300],
                    message=f"✓ git clone confirmed: {dest}"
                )
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message=f"git clone reported success but destination directory not found: {dest_path}"
            )

        if action == "commit":
            # Look for commit hash pattern in output
            import re
            if re.search(r"[a-f0-9]{7,}", tool_result):
                return VerificationResult(
                    status="confirmed",
                    evidence=tool_result[:300],
                    message=f"✓ git commit confirmed with hash."
                )
            # BUG 4: No commit hash found — return unverifiable
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message=f"git commit reported success but no commit hash found."
            )

        if action in {"push", "push_with_token"}:
            # BUG 5: Parse output for rejection indicators
            rejection_indicators = ["rejected", "failed", "error", "could not resolve"]
            if any(indicator in tool_result.lower() for indicator in rejection_indicators):
                return VerificationResult(
                    status="failed",
                    evidence=tool_result[:300],
                    message=f"git push was rejected."
                )
            return VerificationResult(
                status="confirmed",
                evidence=tool_result[:300],
                message=f"✓ git push confirmed."
            )

        if action == "create_repo":
            if "Repository created:" in tool_result:
                url_line = ""
                for line in tool_result.splitlines():
                    if line.startswith("Repository created:"):
                        url_line = line
                        break
                # BUG 6: Validate URL matches https://github.com/ pattern
                if "https://github.com/" in url_line:
                    return VerificationResult(
                        status="confirmed",
                        evidence=tool_result[:300],
                        message=f"✓ GitHub repo created. {url_line}"
                    )
                return VerificationResult(
                    status="unverifiable",
                    evidence=tool_result[:300],
                    message=f"git create_repo reported success but URL is not a valid GitHub URL."
                )

        return VerificationResult(
            status="confirmed",
            evidence=tool_result[:300],
            message=f"✓ git {action} confirmed."
        )


    # ── edit_file ─────────────────────────────────────────────────────────────

    def _verify_edit_file(self, tool_input, tool_result):
        if "FILE_EDITED" not in tool_result:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="edit_file did not return FILE_EDITED.",
            )
        actual_path = None
        for line in tool_result.splitlines():
            if line.startswith("Location:"):
                actual_path = line.replace("Location:", "", 1).strip()
                break
        if not actual_path:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="edit_file reported success but did not provide a concrete path.",
            )

        requested_path = self._resolve_path_for_verification(tool_input)
        if requested_path is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="edit_file could not resolve its requested location safely.",
            )
        if os.path.abspath(actual_path) != requested_path:
            return VerificationResult(
                status="failed",
                evidence=f"Tool reported: {actual_path}, Expected: {requested_path}",
                message="edit_file reported a different path than requested.",
            )
        if not os.path.isfile(actual_path):
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="edit_file reported success but the target file could not be confirmed on disk.",
            )

        # BUG 20: Handle non-string old_value gracefully
        old_value = tool_input.get("old")
        if old_value is not None and not isinstance(old_value, str):
            old_value = str(old_value)
        new_value = tool_input.get("new", "")
        try:
            with open(actual_path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read()
        except Exception as exc:
            return VerificationResult(
                status="unverifiable",
                evidence=str(exc),
                message=f"Could not reread edited file: {actual_path}",
            )

        # Require the edit tool's explicit replacement count. Avoid false
        # failures when the old text legitimately remains inside the replacement
        # (for example, replacing "cat" with "concatenate").
        replacements = None
        for line in tool_result.splitlines():
            if line.startswith("Replacements:"):
                try:
                    replacements = int(line.split(":", 1)[1].strip())
                except (TypeError, ValueError):
                    replacements = None
                break
        if replacements is None or replacements < 1:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="edit_file did not report a valid positive replacement count.",
            )

        if (
            isinstance(old_value, str)
            and old_value
            and old_value not in str(new_value or "")
            and old_value in content
        ):
            return VerificationResult(
                status="failed",
                evidence=f"Old text is still present in {actual_path}.",
                message="edit_file reported success but the old text remains.",
            )

        if isinstance(new_value, str) and new_value and new_value not in content:
            logging.warning("edit_file: new_value not found in %s", actual_path)
            return VerificationResult(
                status="failed",
                evidence=f"Replacement text was not found in {actual_path}.",
                message="edit_file reported success but the replacement text is missing.",
            )

        # BUG 24+28: Wrap getsize in try/except for TOCTOU protection
        try:
            size = os.path.getsize(actual_path)
        except Exception as exc:
            return VerificationResult(
                status="unverifiable",
                evidence=str(exc),
                message=f"Could not get file size for verification: {actual_path}",
            )
        return VerificationResult(
            status="confirmed",
            evidence=f"Path: {actual_path}\nSize: {size} bytes",
            message=f"✓ File edit confirmed on disk: {actual_path}",
        )

    # ── delete_file ───────────────────────────────────────────────────────────

    def _verify_delete_file(self, tool_input, tool_result):
        if "FILE_DELETED" not in tool_result:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="delete_file did not return FILE_DELETED.",
            )
        # Require a concrete reported path as well as independent filesystem
        # evidence; a bare FILE_DELETED marker is not enough to confirm an action.
        reported_path = None
        for line in tool_result.splitlines():
            if line.startswith("Location:"):
                reported_path = line.split(":", 1)[1].strip()
                break
        if not reported_path:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="delete_file reported no concrete path.",
            )

        actual_path = self._resolve_path_for_verification(tool_input)
        if actual_path is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="delete_file could not resolve its requested location safely.",
            )
        if os.path.abspath(reported_path) != actual_path:
            return VerificationResult(
                status="failed",
                evidence=f"Tool reported: {reported_path}, Expected: {actual_path}",
                message="delete_file reported a different path than requested.",
            )
        if os.path.exists(actual_path):
            return VerificationResult(
                status="failed",
                evidence=f"File still exists: {actual_path}",
                message=f"✗ delete_file claimed success but the file still exists: {actual_path}",
            )
        return VerificationResult(
            status="confirmed",
            evidence=f"Confirmed absent: {actual_path}",
            message=f"✓ File deletion confirmed: {actual_path}",
        )


    # ── generate_image ────────────────────────────────────────────────────────

    def _verify_generate_image(self, tool_input, tool_result):
        """Confirm image generation produced a real non-empty output file."""
        if "IMAGE GENERATED" not in tool_result or "STATUS: SUCCESS" not in tool_result:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:400],
                message="generate_image did not report a successful generation.",
            )

        saved_path = None
        for line in tool_result.splitlines():
            if line.startswith("Saved to:"):
                saved_path = line.replace("Saved to:", "", 1).strip()
                break

        if not saved_path:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="Image generation succeeded but no output path was reported.",
            )

        if not os.path.isfile(saved_path):
            return VerificationResult(
                status="failed",
                evidence=f"os.path.isfile({saved_path!r}) = False",
                message=f"Generated image was not found on disk: {saved_path}",
            )

        # BUG 25+28: Wrap getsize in try/except for TOCTOU protection
        try:
            size = os.path.getsize(saved_path)
        except Exception as exc:
            return VerificationResult(
                status="unverifiable",
                evidence=str(exc),
                message=f"Could not get file size for verification: {saved_path}",
            )
        if size <= 0:
            return VerificationResult(
                status="failed",
                evidence=f"File size = {size} bytes",
                message=f"Generated image is empty: {saved_path}",
            )

        return VerificationResult(
            status="confirmed",
            evidence=f"Image: {saved_path} ({size:,} bytes)",
            message=f"✓ Image confirmed on disk: {saved_path}",
        )

    # ── desktop ───────────────────────────────────────────────────────────────

    def _verify_desktop(self, tool_input, tool_result):
        """
        Verify desktop action by checking STATUS: SUCCESS
        and whether a screenshot was saved.
        """
        action = tool_input.get("action", "")

        if "DESKTOP ERROR" in tool_result:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:400],
                message=f"desktop {action} failed: {tool_result[:100]}"
            )

        if "STATUS: SUCCESS" not in tool_result:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message=f"desktop {action} has no STATUS marker."
            )

        # If a screenshot was saved, confirm it exists on disk
        # BUG 17: Check "Screenshot saved:" BEFORE "Screenshot:" since "Screenshot saved:" also starts with "Screenshot:"
        screenshot_path = None
        for line in tool_result.splitlines():
            if line.startswith("Screenshot saved:"):
                screenshot_path = line.replace("Screenshot saved:", "", 1).strip()
                break
            if line.startswith("Screenshot:"):
                screenshot_path = line.replace("Screenshot:", "").strip()
                break

        if screenshot_path:
            if os.path.isfile(screenshot_path):
                # BUG 26+28: Wrap getsize in try/except for TOCTOU protection
                try:
                    size = os.path.getsize(screenshot_path)
                except Exception as exc:
                    return VerificationResult(
                        status="unverifiable",
                        evidence=str(exc),
                        message=f"Could not get screenshot size for verification: {screenshot_path}",
                    )
                return VerificationResult(
                    status="confirmed",
                    evidence=f"Screenshot: {screenshot_path} ({size:,} bytes)",
                    message=f"✓ desktop {action} confirmed. Screenshot saved."
                )
            else:
                return VerificationResult(
                    status="unverifiable",
                    evidence=f"Screenshot path not found: {screenshot_path}",
                    message=f"desktop {action} reported success but screenshot missing."
                )

        # BUG 7: For non-screenshot actions, check that some output was produced
        if not tool_result.strip():
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message=f"desktop {action} reported success but produced no output."
            )

        return VerificationResult(
            status="confirmed",
            evidence=tool_result[:300],
            message=f"✓ desktop {action} confirmed."
        )

    # ── web_search ────────────────────────────────────────────────────────────

    def _verify_web_search(self, tool_input, tool_result):
        """
        Check result contains Title: and URL: markers.
        """
        if tool_result.startswith("Web search error:") or \
           tool_result.startswith("Web search failed:"):
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="web_search returned an error."
            )

        has_title = "Title:" in tool_result
        has_url   = "URL:"   in tool_result

        if not has_title or not has_url:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="web_search result missing Title/URL markers."
            )

        # Every result entry must contain a non-empty title and a public
        # HTTP(S) URL. Do not treat arbitrary strings or javascript: links as
        # evidence that a real search result was returned.
        titles = [value.strip() for value in re.findall(r"^Title:\s*(.*)$", tool_result, flags=re.MULTILINE)]
        urls = [value.strip() for value in re.findall(r"^URL:\s*(.*)$", tool_result, flags=re.MULTILINE)]
        if not titles or not urls or len(titles) != len(urls):
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="web_search result has missing or mismatched Title/URL entries."
            )
        if any(not title for title in titles):
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="web_search result contains an empty title."
            )

        for url in urls:
            try:
                parsed = urlsplit(url)
                valid_url = parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
            except ValueError:
                valid_url = False
            if not valid_url:
                return VerificationResult(
                    status="failed",
                    evidence=f"Invalid result URL: {url[:160]}",
                    message="web_search returned a result with an invalid or unsafe URL.",
                )

        query = str(tool_input.get("query", "(unknown)"))
        count = len(titles)
        return VerificationResult(
            status="confirmed",
            evidence=tool_result[:400],
            message=f"✓ Web search confirmed: {count} result(s) for '{query[:60]}'"
        )


    def _verify_web_fetch(self, tool_input, tool_result):
        """Verify a bounded webpage fetch returned a public URL and page text."""
        if tool_result.startswith("WEB_FETCH_ERROR:"):
            return VerificationResult(
                status="failed",
                evidence=tool_result[:400],
                message="web_fetch returned an error.",
            )
        if "WEB_FETCH_SUCCESS" not in tool_result:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="web_fetch result is missing its success marker.",
            )

        fetched_url = None
        for line in tool_result.splitlines():
            if line.startswith("URL:"):
                fetched_url = line.split(":", 1)[1].strip()
                break
        if not fetched_url:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="web_fetch did not report the final URL.",
            )
        try:
            parsed = urlsplit(fetched_url)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                raise ValueError("unsafe URL")
        except ValueError:
            return VerificationResult(
                status="failed",
                evidence=f"Invalid URL: {fetched_url[:160]}",
                message="web_fetch reported an invalid URL.",
            )

        begin = tool_result.rfind("BEGIN_PAGE_TEXT")
        end = tool_result.rfind("END_PAGE_TEXT")
        if begin < 0 or end <= begin:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="web_fetch result has no complete page-text block.",
            )
        page_text = tool_result[begin + len("BEGIN_PAGE_TEXT"):end].strip()
        if not page_text:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="web_fetch returned an empty page-text block.",
            )
        return VerificationResult(
            status="confirmed",
            evidence=f"URL: {fetched_url}\nCharacters observed: {len(page_text)}",
            message=f"✓ Webpage text fetched from {fetched_url}",
        )


    def _verify_github(self, tool_input, tool_result):
        """Require the GitHub CLI's explicit successful exit status."""
        if "GITHUB_STATUS: ERROR" in tool_result:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:400],
                message="GitHub CLI reported an error.",
            )
        if "GITHUB_STATUS: SUCCESS" not in tool_result:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="GitHub result is missing its success marker.",
            )
        match = re.search(r"^Exit code:\s*(-?\d+)\s*$", tool_result, flags=re.MULTILINE)
        if not match:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="GitHub result did not include an exit code.",
            )
        if int(match.group(1)) != 0:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:400],
                message=f"GitHub CLI exited with code {match.group(1)}.",
            )
        action = str(tool_input.get("action", "query"))
        repo = str(tool_input.get("repo", "unknown repository"))
        return VerificationResult(
            status="confirmed",
            evidence=tool_result[:800],
            message=f"✓ GitHub {action} query completed for {repo}.",
        )
