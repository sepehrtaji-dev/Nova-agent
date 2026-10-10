import os
import tempfile
import unittest

from tools.filesystem import FileSystemTool


class FileSystemSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tool = FileSystemTool()

    def test_protected_system_path_is_rejected(self):
        with self.assertRaises(PermissionError):
            self.tool._check_system_path("/etc/shadow")

    def test_protected_path_element_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as root:
            protected = os.path.join(root, ".SSH", "id_rsa")
            with self.assertRaises(PermissionError):
                self.tool._check_system_path(protected)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_broken_symlink_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            outside = os.path.join(os.path.dirname(root), "nova-missing-target")
            link = os.path.join(root, "escape.txt")
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            self.tool.projects_path = root
            with self.assertRaises(ValueError):
                self.tool._resolve_path("escape.txt", "projects")

    def test_edit_file_rejects_empty_old_string(self):
        with tempfile.TemporaryDirectory() as root:
            self.tool.projects_path = root
            path = os.path.join(root, "note.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("keep me")
            result = self.tool.edit_file({
                "path": "note.txt",
                "location": "projects",
                "old": "",
                "new": "bad",
            })
            self.assertIn("non-empty 'old'", result)
            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "keep me")

    @unittest.skipUnless(hasattr(os, "symlink") and os.name == "posix", "POSIX symlink test")
    def test_symlink_to_protected_system_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            link = os.path.join(root, "innocent-name.txt")
            try:
                os.symlink("/etc/shadow", link)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            with self.assertRaises(PermissionError):
                self.tool._check_system_path(link)


if __name__ == "__main__":
    unittest.main()
