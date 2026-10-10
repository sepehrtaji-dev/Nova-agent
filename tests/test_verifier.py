import os
import tempfile
import unittest

from agent.verifier import Verifier


class TestVerifier(unittest.TestCase):

    def setUp(self):
        self.verifier = Verifier(tools=None)

    def test_write_file_accepts_dict_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "network.py")
            result = (
                "FILE_CREATED\n"
                f"Location: {path}\n"
                "Bytes: 42"
            )

            verification = self.verifier.verify(
                "write_file",
                {
                    "path": "network.py",
                    "location": "projects",
                },
                result,
            )

            self.assertEqual(verification.status, "failed")

            with open(path, "w", encoding="utf-8") as handle:
                handle.write("print('ok')")

            verification = self.verifier.verify(
                "write_file",
                {
                    "path": path,
                    "location": "system",
                },
                result,
            )

            self.assertTrue(verification.confirmed())

    def test_edit_file_cannot_confirm_missing_target(self):
        result = (
            "FILE_EDITED\n"
            "Location: /tmp/does-not-exist/nova.py\n"
            "Replacements: 1"
        )

        verification = self.verifier.verify(
            "edit_file",
            {"path": "nova.py", "location": "projects"},
            result,
        )

        self.assertEqual(verification.status, "failed")

    def test_generate_image_requires_real_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "generated.png")
            result = (
                "IMAGE GENERATED\n"
                f"Saved to: {path}\n"
                "STATUS: SUCCESS"
            )

            verification = self.verifier.verify(
                "generate_image",
                {"prompt": "test"},
                result,
            )
            self.assertEqual(verification.status, "failed")

            with open(path, "wb") as handle:
                handle.write(b"PNG")

            verification = self.verifier.verify(
                "generate_image",
                {"prompt": "test"},
                result,
            )
            self.assertTrue(verification.confirmed())

    def test_terminal_requires_zero_exit_code(self):
        result = "Exit code: 1\nSTDERR:\nboom\nSTATUS: SUCCESS"
        verification = self.verifier.verify(
            "terminal",
            {"command": "false"},
            result,
        )
        self.assertEqual(verification.status, "failed")

    def test_terminal_without_exit_code_is_unverifiable(self):
        result = "STATUS: SUCCESS\nSTDOUT:\nok"
        verification = self.verifier.verify(
            "terminal",
            {"command": "echo ok"},
            result,
        )
        self.assertEqual(verification.status, "unverifiable")

    def test_delete_requires_reported_path(self):
        # With path resolution from tool_input, a missing file is confirmed deleted
        verification = self.verifier.verify(
            "delete_file",
            {"path": "x.txt", "location": "projects"},
            "FILE_DELETED",
        )
        self.assertEqual(verification.status, "confirmed")

    def test_edit_file_checks_replacement_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "note.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("new value")

            result = f"FILE_EDITED\nLocation: {path}\nReplacements: 1"
            verification = self.verifier.verify(
                "edit_file",
                {"old": "old value", "new": "new value"},
                result,
            )
            self.assertTrue(verification.confirmed())

    def test_edit_file_allows_old_text_inside_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "note.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("concatenate")

            result = f"FILE_EDITED\\nLocation: {path}\\nReplacements: 1\\nBytes: 11"
            verification = self.verifier.verify(
                "edit_file",
                {"old": "cat", "new": "concatenate"},
                result,
            )
            self.assertTrue(verification.confirmed())

    def test_edit_file_requires_replacement_count_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "note.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("new value")
            result = f"FILE_EDITED\\nLocation: {path}\\nBytes: 9"
            verification = self.verifier.verify(
                "edit_file",
                {"old": "old value", "new": "new value"},
                result,
            )
            self.assertEqual(verification.status, "failed")

    def test_write_file_verifies_exact_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "note.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("actual")

            result = f"FILE_CREATED\nLocation: {path}\nBytes: 6"
            verification = self.verifier.verify(
                "write_file",
                {"path": "note.txt", "location": "projects", "content": "expected"},
                result,
            )
            self.assertEqual(verification.status, "failed")

    def test_unknown_tool_is_not_success(self):
        verification = self.verifier.verify(
            "unknown_tool",
            {},
            "STATUS: SUCCESS",
        )

        self.assertEqual(verification.status, "unverifiable")
        self.assertFalse(verification.confirmed())


if __name__ == "__main__":
    unittest.main()
