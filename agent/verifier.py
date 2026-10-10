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
        return resolved_path if common == root else None


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
        if "STATUS: ERROR" in tool_result or "FILESYSTEM ERROR" in tool_result:
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

        match = re.search(r"Match count:\s*(-?\d+)", tool_result)
        count = int(match.group(1)) if match else 0
        # BUG 15: Handle negative values as errors
        if count < 0:
            return VerificationResult(
                status="failed",
                evidence=tool_result[:900],
                message=f"find_files returned negative count: {count}."
            )
        # BUG 9: Return unverifiable when count is 0
        if count == 0:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:900],
                message="find_files returned 0 matches."
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
        """Verify the requested directory exists and is actually a directory."""
        path = str(tool_input.get("path", ".")).strip() or "."
        location = str(tool_input.get("location", "projects")).strip().lower()

        if any(err in tool_result for err in ("Filesystem error:", "Permission denied:", "Path does not exist:", "Not a directory:")):
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message=f"list_files failed: {tool_result[:120]}",
            )

        actual_path = self._resolve_path_for_verification(tool_input)
        if actual_path is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:200],
                message="list_files could not resolve its requested location safely.",
            )

        if not os.path.isdir(actual_path):
            return VerificationResult(
                status="failed",
                evidence=f"os.path.isdir({actual_path!r}) = False",
                message=f"Directory could not be confirmed on disk: {actual_path}",
            )

        return VerificationResult(
            status="confirmed",
            evidence=f"Directory: {actual_path}",
            message=f"✓ Directory listing confirmed: {actual_path}",
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
        if not actual_path or not os.path.isfile(actual_path):
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
        # BUG 12: Use _resolve_path_for_verification instead of trusting tool-reported path
        actual_path = self._resolve_path_for_verification(tool_input)
        if actual_path is None:
            return VerificationResult(
                status="unverifiable",
                evidence=tool_result[:300],
                message="delete_file could not resolve its requested location safely.",
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

        # BUG 8: Validate that titles and URLs are non-empty
        titles = re.findall(r"Title:\s*(.*)", tool_result)
        urls = re.findall(r"URL:\s*(.*)", tool_result)
        if not any(t.strip() for t in titles) or not any(u.strip() for u in urls):
            return VerificationResult(
                status="failed",
                evidence=tool_result[:300],
                message="web_search result has empty Title or URL."
            )

        query = tool_input.get("query", "(unknown)")
        # BUG 16: Use regex to count actual result entries
        count = len(re.findall(r"^Title:", tool_result, flags=re.MULTILINE))

        return VerificationResult(
            status="confirmed",
            evidence=tool_result[:400],
            message=f"✓ Web search confirmed: {count} result(s) for '{query[:60]}'"
        )
