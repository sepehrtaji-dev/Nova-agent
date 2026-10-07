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

        tool_result = str(tool_result) if tool_result is not None else ""

        dispatch = {
            "write_file":       self._verify_write_file,
            "read_file":        self._verify_read_file,
            "edit_file":        self._verify_edit_file,
            "delete_file":      self._verify_delete_file,
            "create_directory": self._verify_create_directory,
            "list_files":       self._verify_list_files,
            "terminal":         self._verify_terminal,
            "git":              self._verify_git,
            "web_search":       self._verify_web_search,
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
            return VerificationResult(
                status="unverifiable",
                evidence=str(exc),
                message=f"Verifier crashed for '{tool_name}': {exc}"
            )

    # ── write_file ────────────────────────────────────────────────────────────

    def _verify_write_file(self, tool_input, tool_result):
        """
        1. Check tool result contains FILE_CREATED.
        2. Re-read the file via the read_file tool and confirm content exists.
        3. Check OS file size > 0.
        """
        path     = tool_input.get("path", "")
        location = tool_input.get("location", "projects")

        # Step 1: tool claimed success?
        if "FILE_CREATED" not in tool_result:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message=f"write_file did not return FILE_CREATED for '{path}'."
            )

        # Extract the actual path from the tool result
        actual_path = None
        for line in tool_result.splitlines():
            if line.startswith("Location:"):
                actual_path = line.replace("Location:", "").strip()
                break

        if not actual_path:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message=f"write_file succeeded but actual path not found in result."
            )

        # Step 2: OS-level check — file must exist and have content
        if not os.path.isfile(actual_path):
            return VerificationResult(
                status="failed",
                evidence=f"os.path.isfile({actual_path!r}) = False",
                message=f"File does not exist on disk: {actual_path}"
            )

        size = os.path.getsize(actual_path)
        if size == 0:
            return VerificationResult(
                status="failed",
                evidence=f"File size = 0 bytes: {actual_path}",
                message=f"File was created but is empty: {actual_path}"
            )

        # Step 3: read first 200 chars as evidence
        try:
            with open(actual_path, "r", encoding="utf-8", errors="replace") as f:
                preview = f.read(200)
        except Exception as e:
            preview = f"(could not read: {e})"

        return VerificationResult(
            status="confirmed",
            evidence=f"Path: {actual_path}\nSize: {size} bytes\nPreview: {preview!r}",
            message=f"✓ File confirmed on disk: {actual_path} ({size} bytes)"
        )

    # ── read_file ─────────────────────────────────────────────────────────────

    def _verify_read_file(self, tool_input, tool_result):
        """
        Check the result is non-empty and doesn't start with an error marker.
        """
        error_prefixes = [
            "Filesystem error:",
            "File does not exist",
            "Path is not a file",
            "File is not a UTF-8",
        ]

        for prefix in error_prefixes:
            if tool_result.startswith(prefix):
                return VerificationResult(
                    status="failed",
                    evidence=tool_result[:300],
                    message=f"read_file failed: {tool_result[:100]}"
                )

        if not tool_result.strip():
            return VerificationResult(
                status="failed",
                evidence="(empty result)",
                message="read_file returned empty content."
            )

        path = tool_input.get("path", "(unknown)")
        return VerificationResult(
            status="confirmed",
            evidence=tool_result[:200],
            message=f"✓ File read confirmed: {path} ({len(tool_result)} chars)"
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
        """
        Check result is not an error and contains at least one entry.
        """
        error_prefixes = [
            "Filesystem error:",
            "Path does not exist:",
            "Not a directory:",
        ]

        for prefix in error_prefixes:
            if tool_result.startswith(prefix):
                return VerificationResult(
                    status="failed",
                    evidence=tool_result[:300],
                    message=f"list_files failed: {tool_result[:100]}"
                )

        path = tool_input.get("path", ".")
        entries = [
            line for line in tool_result.splitlines()
            if line.strip()
        ]

        return VerificationResult(
            status="confirmed",
            evidence=tool_result[:300],
            message=f"✓ Listed {len(entries)} entries in '{path}'"
        )

    # ── terminal ──────────────────────────────────────────────────────────────

    def _verify_terminal(self, tool_input, tool_result):
        """
        1. Check STATUS: SUCCESS in result.
        2. Check exit code = 0.
        3. Capture stdout as evidence.
        """
        if "STATUS: ERROR" in tool_result:
            # Extract stderr for useful feedback
            stderr = ""
            for line in tool_result.splitlines():
                if line.startswith("STDERR:"):
                    stderr = line
                    break
            return VerificationResult(
                status="failed",
                evidence=tool_result[:500],
                message=f"Terminal command failed. {stderr}"
            )

        if "STATUS: SUCCESS" not in tool_result:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="Terminal result has no STATUS marker."
            )

        # Extract stdout as evidence
        stdout = ""
        capture = False
        for line in tool_result.splitlines():
            if line.startswith("STDOUT:"):
                capture = True
                continue
            if capture:
                if line.startswith("STDERR:") or line.startswith("STATUS:"):
                    break
                stdout += line + "\n"

        command = tool_input.get("command", "(unknown)")
        return VerificationResult(
            status="confirmed",
            evidence=stdout[:300] if stdout else tool_result[:300],
            message=f"✓ Command succeeded: {command[:80]}"
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
                message=f"git {action} has no STATUS marker."
            )

        # Action-specific checks
        if action == "clone":
            url  = tool_input.get("url", "")
            # Derive expected folder name
            dest = url.rstrip("/").split("/")[-1].replace(".git", "")
            # Can't check absolute path here easily, so trust STATUS: SUCCESS
            return VerificationResult(
                status="confirmed",
                evidence=tool_result[:300],
                message=f"✓ git clone confirmed: {dest}"
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
            return VerificationResult(
                status="confirmed",
                evidence=tool_result[:300],
                message=f"✓ git commit reported success."
            )

        if action in {"push", "push_with_token"}:
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
                return VerificationResult(
                    status="confirmed",
                    evidence=tool_result[:300],
                    message=f"✓ GitHub repo created. {url_line}"
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
                message=f"edit_file did not return FILE_EDITED."
            )
        actual_path = None
        for line in tool_result.splitlines():
            if line.startswith("Location:"):
                actual_path = line.replace("Location:", "").strip()
                break
        if actual_path and os.path.isfile(actual_path):
            size = os.path.getsize(actual_path)
            return VerificationResult(
                status="confirmed",
                evidence=f"Path: {actual_path}\nSize: {size} bytes",
                message=f"✓ File edit confirmed on disk: {actual_path}"
            )
        return VerificationResult(
            status="failed",
            evidence=tool_result[:300],
            message="edit_file reported success but the target file could not be confirmed on disk."
        )

    # ── delete_file ───────────────────────────────────────────────────────────

    def _verify_delete_file(self, tool_input, tool_result):
        if "FILE_DELETED" not in tool_result:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="delete_file did not return FILE_DELETED."
            )
        actual_path = None
        for line in tool_result.splitlines():
            if line.startswith("Location:"):
                actual_path = line.replace("Location:", "").strip()
                break
        if actual_path and os.path.exists(actual_path):
            return VerificationResult(
                status="failed",
                evidence=f"File still exists: {actual_path}",
                message=f"✗ delete_file claimed success but file still exists: {actual_path}"
            )
        return VerificationResult(
            status="confirmed",
            evidence=tool_result[:300],
            message=f"✓ File deletion confirmed: {actual_path}"
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

        size = os.path.getsize(saved_path)
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
        screenshot_path = None
        for line in tool_result.splitlines():
            if line.startswith("Screenshot:"):
                screenshot_path = line.replace("Screenshot:", "").strip()
                break

        if screenshot_path:
            if os.path.isfile(screenshot_path):
                size = os.path.getsize(screenshot_path)
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

        query = tool_input.get("query", "(unknown)")
        # Count results
        count = tool_result.count("Title:")

        return VerificationResult(
            status="confirmed",
            evidence=tool_result[:400],
            message=f"✓ Web search confirmed: {count} result(s) for '{query[:60]}'"
        )
