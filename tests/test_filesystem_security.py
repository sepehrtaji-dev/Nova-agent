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
