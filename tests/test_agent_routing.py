import json
import unittest

from agent.router import ToolRouter
from agent.planner import Planner


class FakeBrain:
    def __init__(self, response=None):
        self.response = response
        self.calls = 0

    @staticmethod
    def _planner_fixture(prompt):
        import re

        match = re.search(r"USER GOAL:\s*(.*?)\n\nCONTEXT:", prompt, re.DOTALL)
        goal = match.group(1).strip() if match else ""
        low = goal.lower()

        def step(tool, description, data):
            return {"tool": tool, "input": data, "description": description}

        if "what files did you create" in low:
            steps = [step("find_files", "find_files: files created in last 24 hours", {"path": ".", "location": "projects", "recursive": True, "created_within_hours": 24})]
        elif "search the web about assembly" in low:
            steps = [
                step("web_search", "web_search: search about assembly", {"query": "assembly"}),
                step("write_file", "write_file: create Python hello world file", {"path": "hello_world.py", "location": "projects"}),
            ]
        elif "use firefox to search about cs2 game" in low:
            steps = [
                step("desktop", "desktop: open firefox", {"action": "open_app", "app": "firefox"}),
                step("desktop", "desktop: press ctrl+l", {"action": "key", "key": "ctrl+l"}),
                step("desktop", 'desktop: type "cs2 game"', {"action": "type", "text": "cs2 game"}),
                step("desktop", "desktop: press enter", {"action": "key", "key": "enter"}),
            ]
        elif "open notepad" in low:
            steps = [
                step("desktop", "desktop: open notepad", {"action": "open_app", "app": "notepad"}),
                step("desktop", 'desktop: type "HELLO_NOVA_TEST"', {"action": "type", "text": "HELLO_NOVA_TEST"}),
            ]
        elif "please run my firefox" in low:
            steps = [step("desktop", "desktop: open firefox", {"action": "open_app", "app": "firefox"})]
        elif "write a c++ script" in low or "c++" in low:
            steps = [step("write_file", "write_file: create hello.cpp", {"path": "hello.cpp", "location": "projects"})]
        elif "read hello.cpp" in low:
            steps = [step("read_file", "read_file: read hello.cpp", {"path": "hello.cpp", "location": "projects"})]
        elif "create a python file called test_model.py" in low:
            steps = [step("write_file", "write_file: create test_model.py", {"path": "test_model.py", "location": "projects"})]
        else:
            steps = []

        return json.dumps({"goal": goal, "steps": steps})

    def generate(self, prompt, **kwargs):
        self.calls += 1
        if self.response is not None:
            return self.response
        if "You are Nova's task planner." in prompt:
            return self._planner_fixture(prompt)
        return '{"task_type":"conversation"}'


class FakeTools:
    def __init__(self):
        self.tools = {
            "write_file": {"description": "Create or overwrite a file on disk", "function": lambda x: None},
            "read_file": {"description": "Read the contents of a text file from the projects folder or desktop", "function": lambda x: None},
            "find_files": {"description": "Find files recursively with optional filename/time filters", "function": lambda x: None},
            "list_files": {"description": "List files and directories in the projects folder or desktop", "function": lambda x: None},
            "create_directory": {"description": "Create a directory", "function": lambda x: None},
            "terminal": {"description": "Execute terminal shell commands", "function": lambda x: None},
            "web_search": {"description": "Search the public web for current information", "function": lambda x: None},
            "generate_image": {"description": "Generate an image", "function": lambda x: None},
                        "git": {"description": "Run git operations on a local repository", "function": lambda x: None},
            "desktop": {"description": "Control the desktop and GUI: screenshots, mouse, keyboard, apps, and windows", "function": lambda x: None},
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

    def test_structured_plan_input_is_executed_without_llm_redirection(self):
        planner_brain = FakeBrain(
            '{"goal":"read a file","steps":[{"tool":"read_file","input":{"path":"notes.txt","location":"projects"},"description":"read notes.txt"}]}'
        )
        planner = Planner(planner_brain, self.tools)
        plan = planner.create_plan("inspect notes.txt")
        summary = planner.get_plan_summary(plan)

        router_brain = FakeBrain('{"action":"tool","task_type":"computer","tool":"write_file","input":{"path":"wrong.txt","location":"projects"}}')
        router = ToolRouter(router_brain, self.tools)

        decision = router.decide(
            message="inspect notes.txt",
            task_type="computer",
            plan=summary,
            allowed_tools=["read_file", "write_file"],
        )

        self.assertEqual(decision["tool"], "read_file")
        self.assertEqual(
            json.loads(decision["input"]),
            {"path": "notes.txt", "location": "projects"},
        )
        self.assertEqual(router_brain.calls, 0)

    def test_recent_file_query_routes_to_find_files(self):
        planner = Planner(self.brain, self.tools)
        plan = planner.create_plan(
            "What files did you create in the last 24 hours?"
        )
        self.assertEqual(len(plan["steps"]), 1)
        self.assertTrue(plan["steps"][0]["description"].startswith("find_files:"))

    def test_compound_search_and_file_request_preserves_both_steps(self):
        planner = Planner(self.brain, self.tools)
        plan = planner.create_plan(
            "search the web about assembly and write a Python hello world file"
        )
        self.assertEqual(len(plan["steps"]), 2)
        self.assertTrue(plan["steps"][0]["description"].startswith("web_search:"))
        self.assertTrue(plan["steps"][1]["description"].startswith("write_file:"))

    def test_compound_desktop_request_uses_tool_aware_planner(self):
        brain = FakeBrain(
            '{"goal":"desktop task","steps":[{"description":"desktop: open notepad"},{"description":"desktop: type HELLO_NOVA_TEST"}]}'
        )
        self.tools.get_descriptions = lambda: "- desktop: Control the desktop and GUI"
        planner = Planner(brain, self.tools)

        plan = planner.create_plan(
            'open notepad and type "HELLO_NOVA_TEST" in it'
        )

        self.assertEqual(len(plan["steps"]), 2)
        self.assertEqual(brain.calls, 1)
        self.assertIn("desktop:", plan["steps"][0]["description"])
    def test_compound_notepad_request_gets_ordered_desktop_steps(self):
        planner = Planner(self.brain, self.tools)
        plan = planner.create_plan(
            'open notepad and write "HELLO_NOVA_TEST" in it'
        )

        self.assertEqual(len(plan["steps"]), 2)
        self.assertIn("desktop: open notepad", plan["steps"][0]["description"])
        self.assertIn('desktop: write "HELLO_NOVA_TEST" in it', plan["steps"][1]["description"])
        self.assertEqual(self.brain.calls, 1)

    def test_pending_desktop_step_is_routed_to_desktop_tool(self):
        plan = (
            'Goal: notepad task\n'
            '1. [completed] desktop: open notepad\n'
            '2. [pending] desktop: write "HELLO_NOVA_TEST" in it'
        )
        decision = self.router.decide(
            message='open notepad and write "HELLO_NOVA_TEST" in it',
            task_type="computer",
            tool_history="Tool: desktop\nVerification: CONFIRMED\nTool success: True",
            plan=plan,
            allowed_tools=["desktop"],
        )
        self.assertEqual(decision["tool"], "desktop")
        payload = json.loads(decision["input"])
        self.assertEqual(payload["action"], "type")
        self.assertEqual(payload["text"], "HELLO_NOVA_TEST")
    def test_in_app_search_uses_registered_desktop_capability(self):
        planner = Planner(self.brain, self.tools)
        plan = planner.create_plan(
            'use firefox to search about cs2 game'
        )
        self.assertEqual(len(plan["steps"]), 4)
        self.assertTrue(all("desktop:" in step["description"] for step in plan["steps"]))
        self.assertIn("open firefox", plan["steps"][0]["description"])
        self.assertIn("press ctrl+l", plan["steps"][1]["description"])
        self.assertIn('type "cs2 game"', plan["steps"][2]["description"])
        self.assertIn("press enter", plan["steps"][3]["description"])
    def test_single_file_creation_gets_one_deterministic_write_step(self):
        planner = Planner(self.brain)
        plan = planner.create_plan(
            "create a Python file called test_model.py in the projects folder"
        )

        self.assertEqual(len(plan["steps"]), 1)
        self.assertEqual(plan["steps"][0]["id"], 1)
        self.assertEqual(plan["steps"][0]["status"], "pending")
        self.assertIn("write_file", plan["steps"][0]["description"])
        self.assertIn("test_model.py", plan["steps"][0]["description"])
        self.assertEqual(self.brain.calls, 1)

    def test_cplusplus_script_request_is_computer(self):
        self.brain.response = '{"task_type":"computer"}'
        result = self.router.classify_task(
            "write a c++ script printing hello"
        )
        self.assertEqual(result, "computer")
        self.assertEqual(self.brain.calls, 1)

    def test_cplusplus_script_gets_cpp_filename(self):
        planner = Planner(self.brain)
        plan = planner.create_plan(
            "write a c++ script printing hello"
        )
        self.assertEqual(len(plan["steps"]), 1)
        self.assertIn("hello.cpp", plan["steps"][0]["description"])

        decision = self.router.decide(
            message="write a c++ script printing hello",
            task_type="computer",
            plan=planner.get_plan_summary(plan),
            allowed_tools=["write_file"],
        )
        payload = json.loads(decision["input"])
        self.assertEqual(payload["path"], "hello.cpp")
        self.assertEqual(payload["location"], "projects")
    def test_explicit_file_request_uses_llm_classification(self):
        self.brain.response = '{"task_type":"computer"}'
        result = self.router.classify_task(
            "create a Python file called test_model.py in the projects folder"
        )
        self.assertEqual(result, "computer")
        self.assertEqual(self.brain.calls, 1)

    def test_explicit_file_read_gets_deterministic_read_step(self):
        planner = Planner(self.brain)
        plan = planner.create_plan(
            "read hello.cpp in projects folder"
        )

        self.assertEqual(len(plan["steps"]), 1)
        self.assertIn("read_file", plan["steps"][0]["description"])
        self.assertIn("hello.cpp", plan["steps"][0]["description"])

        decision = self.router.decide(
            message="read hello.cpp in projects folder",
            task_type="computer",
            plan=planner.get_plan_summary(plan),
            allowed_tools=["read_file"],
        )
        payload = json.loads(decision["input"])
        self.assertEqual(payload["path"], "hello.cpp")
        self.assertEqual(payload["location"], "projects")

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

    def test_mouse_and_keyboard_control_is_explicit_computer_intent(self):
        self.assertTrue(
            self.router._has_explicit_computer_intent(
                "can you move the mouse to 500, 400?"
            )
        )
        self.assertTrue(
            self.router._has_explicit_computer_intent(
                "can you press ctrl+shift+t?"
            )
        )

    def test_model_cannot_override_a_planned_tool(self):
        plan = (
            "Goal: open Notepad\\n"
            "1. [pending] desktop: open notepad"
        )
        decision = self.router.decide(
            message="open notepad",
            task_type="computer",
            plan=plan,
            allowed_tools=["desktop", "edit_file"],
        )
        self.assertEqual(decision["tool"], "desktop")
    def test_click_gets_real_coordinates_deterministically(self):
        decision = self.router._force_desktop_decision(
            "click at 500, 400"
        )
        self.assertEqual(decision["tool"], "desktop")
        payload = json.loads(decision["input"])
        self.assertEqual(payload["action"], "click")
        self.assertEqual(payload["x"], 500)
        self.assertEqual(payload["y"], 400)
        self.assertEqual(payload["button"], "left")
        self.assertEqual(payload["clicks"], 1)

    def test_keyboard_shortcut_is_deterministic(self):
        decision = self.router._force_desktop_decision(
            "press ctrl+shift+t"
        )
        self.assertEqual(decision["tool"], "desktop")
        payload = json.loads(decision["input"])
        self.assertEqual(payload["action"], "key")
        self.assertEqual(payload["key"], "ctrl+shift+t")

    def test_mouse_move_is_deterministic(self):
        decision = self.router.decide(
            message="move the mouse to 300, 250",
            task_type="computer",
            plan="Goal: move the mouse\n1. [pending] desktop: move the mouse to 300, 250",
            allowed_tools=["desktop"],
        )
        self.assertEqual(decision["tool"], "desktop")
        payload = json.loads(decision["input"])
        self.assertEqual(payload["action"], "move")
        self.assertEqual(payload["x"], 300)
        self.assertEqual(payload["y"], 250)

    def test_natural_type_request_is_deterministic(self):
        decision = self.router.decide(
            message='type "hello from nova"',
            task_type="computer",
            plan='Goal: type text\n1. [pending] desktop: type "hello from nova"',
            allowed_tools=["desktop"],
        )
        self.assertEqual(decision["tool"], "desktop")
        payload = json.loads(decision["input"])
        self.assertEqual(payload["action"], "type")
        self.assertEqual(payload["text"], "hello from nova")
        self.assertEqual(self.brain.calls, 0)

    def test_type_here_request_is_deterministic(self):
        decision = self.router.decide(
            message="type hello here",
            task_type="computer",
            plan="Goal: type hello here\n1. [pending] desktop: type hello here",
            allowed_tools=["desktop"],
        )
        self.assertEqual(decision["tool"], "desktop")
        payload = json.loads(decision["input"])
        self.assertEqual(payload["action"], "type")
        self.assertEqual(payload["text"], "hello")
        self.assertEqual(self.brain.calls, 0)

    def test_unplanned_mouse_control_uses_model_decision(self):
        self.brain.response = '{"action":"tool","task_type":"computer","tool":"desktop","input":{"action":"click","x":500,"y":400}}'
        decision = self.router.decide(
            message="click at 500, 400",
            task_type="computer",
            plan="No plan.",
            allowed_tools=["desktop"],
        )
        self.assertEqual(decision["tool"], "desktop")
        self.assertEqual(json.loads(decision["input"]), {"action": "click", "x": 500, "y": 400})
        self.assertEqual(self.brain.calls, 1)

    def test_explicit_search_is_computer(self):
        self.assertTrue(self.router._has_explicit_computer_intent("search the web for Python 3.14 release notes"))

    def test_address_bar_typing_is_computer(self):
        message = "type cs2 game in the address bar"
        self.assertTrue(self.router._has_explicit_computer_intent(message))
        self.brain.response = '{"task_type":"computer"}'
        self.assertEqual(self.router.classify_task(message), "computer")
        self.assertEqual(self.brain.calls, 1)

    def test_search_box_typing_is_computer(self):
        message = "type hello in the search box"
        self.assertTrue(self.router._has_explicit_computer_intent(message))
        self.brain.response = '{"task_type":"computer"}'
        self.assertEqual(self.router.classify_task(message), "computer")
        self.assertEqual(self.brain.calls, 1)

    def test_direct_app_open_is_computer(self):
        message = "please open firefox"
        self.assertTrue(self.router._has_explicit_computer_intent(message))
        self.brain.response = '{"task_type":"computer"}'
        self.assertEqual(self.router.classify_task(message), "computer")
        self.assertEqual(self.brain.calls, 1)

    def test_app_launch_synonyms_are_computer_intent(self):
        self.brain.response = '{"task_type":"computer"}'
        for message in (
            "please open firefox",
            "please launch firefox",
            "please run my firefox",
            "please start firefox",
        ):
            self.assertTrue(
                self.router._has_explicit_computer_intent(message),
                message,
            )
            self.assertEqual(
                self.router.classify_task(message),
                "computer",
                message,
            )
        self.assertEqual(self.brain.calls, 4)

    def test_run_app_pending_plan_routes_to_open_app(self):
        plan = (
            "Goal: run an app\n"
            "1. [pending] desktop: run firefox"
        )
        decision = self.router.decide(
            message="please run firefox",
            task_type="computer",
            plan=plan,
            allowed_tools=["desktop"],
        )
        self.assertEqual(decision["tool"], "desktop")
        payload = json.loads(decision["input"])
        self.assertEqual(payload["action"], "open_app")
        self.assertEqual(payload["app"], "firefox")


    def test_generic_app_launch_does_not_depend_on_app_name(self):
        planner = Planner(self.brain, self.tools)
        for message in (
            "please run my firefox",
            "please launch calculator",
            "please start the browser",
        ):
            plan = planner.create_plan(message)
            self.assertEqual(len(plan["steps"]), 1, message)
            self.assertTrue(
                plan["steps"][0]["description"].startswith("desktop:"),
                message,
            )


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

    def test_repair_pass_cannot_switch_away_from_pending_plan_tool(self):
        class RepairBrain(FakeBrain):
            def generate(self, prompt, **kwargs):
                self.calls += 1
                if "Choose the next tool" in prompt:
                    return "not-json"
                return '{"action":"tool","task_type":"computer","tool":"terminal","input":{"command":"echo wrong"}}'

        brain = RepairBrain()
        router = ToolRouter(brain, self.tools)
        decision = router.decide(
            message="do the planned task",
            task_type="computer",
            plan="Goal: inspect a requested resource\n1. [pending] read_file: inspect the requested resource",
            allowed_tools=["read_file", "terminal"],
        )
        self.assertEqual(decision["action"], "retry")
        self.assertNotIn("tool", decision)

    def test_raw_success_marker_is_not_success_without_verification(self):
        history = "Tool: desktop\nResult: STATUS: SUCCESS\nOpened: imaginary"
        self.assertFalse(self.router._has_successful_tool(history))

    def test_terminal_location_matches_runtime_contract(self):
        self.assertTrue(
            self.router._validate_basic_tool_input(
                "terminal",
                {"command": "echo ok", "location": "projects"},
            )
        )
        self.assertTrue(
            self.router._validate_basic_tool_input(
                "terminal",
                {"command": "echo ok", "location": "desktop"},
            )
        )
        self.assertFalse(
            self.router._validate_basic_tool_input(
                "terminal",
                {"command": "echo ok", "location": "system"},
            )
        )

    def test_failed_git_history_is_not_success(self):
        history = (
            "Tool: git\n"
            "Result: STATUS: ERROR\n"
            "Verification: FAILED"
        )
        self.assertFalse(self.router._has_successful_tool(history))


if __name__ == "__main__":
    unittest.main()
