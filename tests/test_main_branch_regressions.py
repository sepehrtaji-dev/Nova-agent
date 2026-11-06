import os
import tempfile
import unittest
from unittest import mock

from agent.core import _parse_max_steps
from agent.planner import Planner
from tools.filesystem import FileSystemTool
from tools.registry import ToolRegistry


class MaxStepConfigurationTests(unittest.TestCase):
    def test_invalid_value_uses_default(self):
        self.assertEqual(_parse_max_steps("not-a-number"), 12)

    def test_non_positive_values_are_clamped_to_one(self):
        self.assertEqual(_parse_max_steps("0"), 1)
        self.assertEqual(_parse_max_steps("-8"), 1)

    def test_large_values_are_bounded(self):
        self.assertEqual(_parse_max_steps("100000"), 100)


class AtomicFilesystemWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tool = FileSystemTool()
        self.tool.projects_path = self.temp_dir.name

    def test_failed_atomic_replace_preserves_existing_file(self):
        path = os.path.join(self.temp_dir.name, "note.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("original contents")

        with mock.patch("tools.filesystem.os.replace", side_effect=OSError("disk error")):
            result = self.tool.write_file({
                "path": "note.txt",
                "location": "projects",
                "content": "replacement contents",
            })

        self.assertIn("Filesystem error", result)
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "original contents")
        self.assertFalse(any(name.endswith(".tmp") for name in os.listdir(self.temp_dir.name)))

    def test_write_file_atomically_replaces_contents(self):
        result = self.tool.write_file({
            "path": "note.txt",
            "location": "projects",
            "content": "new contents",
        })
        self.assertIn("FILE_CREATED", result)
        with open(os.path.join(self.temp_dir.name, "note.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "new contents")

    def test_failed_edit_replace_preserves_existing_file(self):
        path = os.path.join(self.temp_dir.name, "note.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("before")

        with mock.patch("tools.filesystem.os.replace", side_effect=OSError("disk error")):
            result = self.tool.edit_file({
                "path": "note.txt",
                "location": "projects",
                "old": "before",
                "new": "after",
            })

        self.assertIn("Filesystem error", result)
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "before")


class FindFilesTraversalTests(unittest.TestCase):
    def test_walk_permission_error_is_reported_as_partial(self):
        tool = FileSystemTool()
        with tempfile.TemporaryDirectory() as directory:
            tool.projects_path = directory

            def walk_with_error(path, onerror=None):
                if onerror:
                    onerror(PermissionError(13, "permission denied", path))
                yield path, [], []

            with mock.patch("tools.filesystem.os.walk", side_effect=walk_with_error):
                result = tool.find_files({
                    "path": ".",
                    "location": "projects",
                    "pattern": "*.py",
                    "recursive": True,
                })

        self.assertIn("STATUS: PARTIAL", result)
        self.assertIn("permission denied", result.lower())


class PlannerWriteDestinationTests(unittest.TestCase):
    def test_failed_write_in_other_location_is_not_superseded(self):
        planner = Planner(brain=None, tools=None)
        failed = {
            "id": 1,
            "description": "Write project note",
            "status": "failed",
            "result": "Permission denied",
            "tool": "write_file",
            "input": {"path": "note.txt", "location": "projects", "content": "old"},
        }
        retry = {
            "id": 2,
            "description": "Write desktop note",
            "status": "pending",
            "result": None,
            "tool": "write_file",
            "input": {"path": "note.txt", "location": "desktop", "content": "new"},
        }
        plan = {"goal": "Write a note", "steps": [failed, retry]}

        planner.replan(
            plan=plan,
            goal="Write a note",
            tool_name="write_file",
            tool_input=retry["input"],
            result="FILE_CREATED",
            success=True,
        )

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(retry["status"], "completed")

    def test_same_write_destination_can_be_superseded(self):
        planner = Planner(brain=None, tools=None)
        failed = {
            "id": 1,
            "description": "First write",
            "status": "failed",
            "result": "Filesystem error",
            "tool": "write_file",
            "input": {"path": "folder/../note.txt", "location": "projects", "content": "old"},
        }
        retry = {
            "id": 2,
            "description": "Retry write",
            "status": "pending",
            "result": None,
            "tool": "write_file",
            "input": {"path": "note.txt", "location": "projects", "content": "new"},
        }
        plan = {"goal": "Write a note", "steps": [failed, retry]}

        planner.replan(
            plan=plan,
            goal="Write a note",
            tool_name="write_file",
            tool_input=retry["input"],
            result="FILE_CREATED",
            success=True,
        )

        self.assertEqual(failed["status"], "superseded")
        self.assertEqual(retry["status"], "completed")


class GeneratedToolInputTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(
            "write_file",
            "Write generated content",
            lambda payload: payload,
            capability="pc",
            prepare_input=lambda payload, context: {**payload, "content": "generated"},
            input_schema={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "content": {
                        "type": "string",
                        "minLength": 1,
                        "x-generated": True,
                    },
                },
            },
        )

    def test_planner_accepts_omitted_generated_field(self):
        planner = Planner(brain=None, tools=self.registry)
        valid, reason = planner._validate_step_tool(
            "write_file",
            {"path": "report.md"},
        )
        self.assertTrue(valid, reason)

    def test_runtime_validation_still_requires_generated_field(self):
        valid, reason = self.registry.validate_input(
            "write_file",
            {"path": "report.md"},
        )
        self.assertFalse(valid)
        self.assertIn("content", reason)

    def test_runtime_validation_accepts_prepared_input(self):
        prepared = self.registry.tools["write_file"]["prepare_input"](
            {"path": "report.md"},
            {},
        )
        valid, reason = self.registry.validate_input("write_file", prepared)
        self.assertTrue(valid, reason)


if __name__ == "__main__":
    unittest.main()
