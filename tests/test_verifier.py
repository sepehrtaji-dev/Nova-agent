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
                    "path": "network.py",
                    "location": "projects",
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
