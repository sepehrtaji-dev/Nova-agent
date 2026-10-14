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

    def test_posix_paths_blocked_on_windows(self):
        """Regression: POSIX blocklist entries never matched on Windows.

        os.path.abspath("/etc/shadow") becomes "C:\\etc\\shadow" on Windows, so
        comparing the absolute path against the literal "/etc/shadow" entry
        always failed and these protected files were reachable.
        """
        for probe in (
            "/etc/shadow",
            "/etc/passwd",
            "/etc/sudoers",
            "/etc/hosts",
            "/proc/self/environ",
            "/sys/kernel",
            "/dev/sda",
            "/boot/grub",
            "/root/secret",
            "/var/log/syslog",
        ):
            with self.assertRaises(PermissionError, msg=probe):
                self.tool._check_system_path(probe)

    def test_path_traversal_and_separator_variants_are_blocked(self):
        for probe in (
            "//etc//shadow",
            "/etc/./shadow",
            "C:/etc/shadow",
            "c:/ETC/SHADOW",
        ):
            with self.assertRaises(PermissionError, msg=probe):
                self.tool._check_system_path(probe)

    def test_legitimate_paths_are_not_over_blocked(self):
        """A tightened filter must not start rejecting normal project files."""
        for probe in (
            "C:/projects/nova/main.py",
            "C:/Users/x/Documents/notes.txt",
            "C:/data/procedures.csv",
            "C:/work/bashrc_notes.md",
            "C:/Users/x/Documents/ssh_keys_guide.txt",
            "C:/reports/etcetera_summary.md",
            "C:/Users/x/.sshconfig_backup.txt",
        ):
            try:
                self.tool._check_system_path(probe)
            except PermissionError as exc:
                self.fail(f"over-blocked legitimate path {probe!r}: {exc}")

    def test_protected_element_matches_on_segment_boundary(self):
        """"'.ssh' blocks .ssh/id_rsa but not a file merely containing it."""
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PermissionError):
                self.tool._check_system_path(os.path.join(root, ".ssh", "id_rsa"))
            # These contain the substring but are ordinary files.
            self.tool._check_system_path(os.path.join(root, "notes.ssh.txt"))
            self.tool._check_system_path(os.path.join(root, ".sshconfig_backup"))


if __name__ == "__main__":
    unittest.main()
