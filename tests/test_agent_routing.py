import json
import unittest

from agent.router import ToolRouter


class FakeBrain:
    def __init__(self, response='{"task_type":"conversation"}'):
        self.response = response
        self.calls = 0

    def generate(self, *args, **kwargs):
        self.calls += 1
        return self.response


class FakeTools:
    def __init__(self):
        self.tools = {
            "write_file": {"description": "write", "function": lambda x: None},
            "read_file": {"description": "read", "function": lambda x: None},
            "list_files": {"description": "list", "function": lambda x: None},
            "create_directory": {"description": "mkdir", "function": lambda x: None},
            "terminal": {"description": "terminal", "function": lambda x: None},
            "web_search": {"description": "web", "function": lambda x: None},
            "generate_image": {"description": "image", "function": lambda x: None},
            "git": {"description": "git", "function": lambda x: None},
        }

    def exists(self, name):
        return name in self.tools

    def get_descriptions(self):
        return "\n".join(
            f"- {name}: {data['description']}"
            for name, data in self.tools.items()
        )


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.brain = FakeBrain()
        self.tools = FakeTools()
        self.router = ToolRouter(self.brain, self.tools)

    def test_explicit_file_request_is_computer_without_llm_classification(self):
        result = self.router.classify_task(
            "create a Python file called test_model.py in the projects folder"
        )
        self.assertEqual(result, "computer")
        self.assertEqual(self.brain.calls, 0)

    def test_plan_selects_write_file_deterministically(self):
        plan = (
            "Goal: create a model\n"
            "1. [pending] Create the Python file test_model.py in projects"
        )
        decision = self.router.decide(
            message="create a Python file called test_model.py in the projects folder",
            task_type="computer",
            plan=plan,
            allowed_tools=["write_file"],
        )
        self.assertEqual(decision["action"], "tool")
        self.assertEqual(decision["tool"], "write_file")
        payload = json.loads(decision["input"])
        self.assertEqual(payload["path"], "test_model.py")
        self.assertEqual(payload["location"], "projects")

    def test_second_write_step_is_not_blocked_by_previous_success(self):
        plan = (
            "Goal: create two files\n"
            "1. [completed] Create first.py\n"
            "2. [pending] Create the Python file second.py"
        )
        decision = self.router.decide(
            message="create first.py and second.py",
            task_type="computer",
            tool_history=(
                "Tool: write_file\n"
                "Verification: CONFIRMED\n"
                "Tool success: True"
            ),
            plan=plan,
            allowed_tools=["write_file"],
        )
        self.assertEqual(decision["tool"], "write_file")
        payload = json.loads(decision["input"])
        self.assertEqual(payload["path"], "second.py")

    def test_open_python_file_is_not_forced_to_desktop(self):
        self.assertFalse(self.router._has_desktop_intent("open test_model.py"))
        self.assertTrue(self.router._has_explicit_computer_intent("open test_model.py"))

    def test_explicit_search_is_computer(self):
        self.assertTrue(self.router._has_explicit_computer_intent("search the web for Python 3.14 release notes"))

    def test_plan_preserves_filename_case(self):
        plan = (
            "Goal: create file\n"
            "1. [pending] Create the Python file MyModel.py in projects"
        )
        decision = self.router.decide(
            message="create a Python file called MyModel.py in the projects folder",
            task_type="computer",
            plan=plan,
            allowed_tools=["write_file"],
        )
        payload = json.loads(decision["input"])
        self.assertEqual(payload["path"], "MyModel.py")

    def test_failed_git_history_is_not_success(self):
        history = (
            "Tool: git\n"
            "Result: STATUS: ERROR\n"
            "Verification: FAILED"
        )
        self.assertFalse(self.router._has_successful_tool(history))


if __name__ == "__main__":
    unittest.main()
