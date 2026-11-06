import json
import unittest
from pathlib import Path

from agent.verifier import Verifier
from tools.filesystem import FileSystemTool


class NativeToolManifestTests(unittest.TestCase):
    def test_precise_edit_and_file_discovery_tools_are_registered(self):
        manifest_path = Path(__file__).resolve().parents[1] / "config" / "tools.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        definitions = {
            item["name"]: item
            for item in manifest["tools"]
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }

        expected = {
            "edit_file": ("edit_file", "_verify_edit_file"),
            "find_files": ("find_files", "_verify_find_files"),
        }
        for name, (method_name, verifier_name) in expected.items():
            with self.subTest(tool=name):
                definition = definitions[name]
                self.assertTrue(definition["enabled"])
                self.assertEqual(definition["module"], "tools.filesystem")
                self.assertEqual(definition["class"], "FileSystemTool")
                self.assertEqual(definition["method"], method_name)
                self.assertEqual(definition["verifier_method"], verifier_name)
                self.assertIsInstance(definition["input_schema"], dict)
                self.assertTrue(callable(getattr(FileSystemTool, method_name, None)))
                self.assertTrue(callable(getattr(Verifier, verifier_name, None)))


if __name__ == "__main__":
    unittest.main()
