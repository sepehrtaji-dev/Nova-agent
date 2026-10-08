import json
import tempfile
import unittest
from pathlib import Path

from agent.core import NovaCore
from agent.verifier import VerificationResult


class FakeBrain:
    def __init__(self):
        self.final_calls = 0

    def generate(self, prompt, system_prompt=None, json_mode=False):
        self.final_calls += 1
        return "Done: the file was created successfully."


class FakeExtractor:
    def extract(self, message):
        return {"memories": []}


class FakeMemory:
    def __init__(self):
        self.messages = []

    def add(self, role, content):
        self.messages.append((role, content))

    def get(self):
        return self.messages


class FakeLongMemory:
    def remember(self, category, key, value):
        return None


class FakeKnowledge:
    def get_context(self, message):
        return "No stored knowledge."

    def add(self, **kwargs):
        return None


class FakeTools:
    def __init__(self):
        self.calls = []
        self.tools = {
            "write_file": {"capability": "pc", "description": "Create or overwrite a file"},
            "read_file": {"capability": "pc", "description": "Read the contents of a file"},
            "desktop": {"capability": "pc", "description": "Control the desktop and GUI"},
            "web_search": {"capability": "web", "description": "Search the public web"},
            "git": {"capability": "git", "description": "Run git operations"},
        }

    def exists(self, name):
        return name == "write_file"

    def execute(self, name, input_data):
        self.calls.append((name, input_data))
        payload = json.loads(input_data)
        return (
            "FILE_CREATED\n"
            f"Location: {payload['path']}\n"
            "Bytes: 64"
        )


class FakeRouter:
    def __init__(self):
        self.generate_calls = 0

    def classify_task(self, message, conversation):
        return "computer"

    def decide(self, **kwargs):
        return {
            "action": "tool",
            "task_type": "computer",
            "tool": "write_file",
            "input": json.dumps({
                "path": "test_model.py",
                "location": "projects",
            }),
        }

    def generate_file_content(self, **kwargs):
        self.generate_calls += 1
        return "import torch\n\nmodel = torch.nn.Linear(4, 2)\n"


class FakePlanner:
    def __init__(self):
        self.replan_calls = 0
        self.plan = None

    def create_plan(self, goal, context):
        self.plan = {
            "goal": goal,
            "steps": [{
                "id": 1,
                "description": "Create test_model.py with a PyTorch neural network",
                "status": "pending",
                "result": None,
            }],
        }
        return self.plan

    def get_plan_summary(self, plan):
        step = plan["steps"][0]
        return f"Goal: {plan['goal']}\n1. [{step['status']}] {step['description']}"

    def get_next_step(self, plan):
        for step in plan["steps"]:
            if step["status"] != "completed":
                return step
        return None

    def update_step(self, plan, step_id, result, status="completed"):
        for step in plan["steps"]:
            if step["id"] == step_id:
                step["status"] = status
                step["result"] = result
        return plan

    def is_complete(self, plan):
        return bool(plan["steps"]) and all(
            step["status"] == "completed"
            for step in plan["steps"]
        )

    def replan(self, **kwargs):
        self.replan_calls += 1
        raise AssertionError("Successful verified actions must not trigger replan().")


class FakeVerifier:
    def verify(self, tool_name, tool_input, result):
        return VerificationResult(
            "confirmed",
            "real file marker observed",
            "file confirmed",
        )


class CoreTests(unittest.TestCase):
    def test_identity_question_reports_nova_and_taji_soft(self):
        core = NovaCore.__new__(NovaCore)
        core.access = {"web": True, "git": True, "pc": True}

        self.assertEqual(
            core._direct_identity_answer("who are you?"),
            "I'm Nova, a local AI assistant developed by the Taji-Soft team.",
        )
        self.assertEqual(
            core._direct_identity_answer("who are you, and who are you developed by?"),
            "I'm Nova, a local AI assistant. I'm developed by the Taji-Soft team.",
        )

    def test_identity_question_does_not_attribute_nova_to_anthropic(self):
        core = NovaCore.__new__(NovaCore)
        core.access = {"web": True, "git": True, "pc": True}

        self.assertEqual(
            core._direct_identity_answer("who are you developed by?"),
            "I'm Nova, a local AI assistant. I'm developed by the Taji-Soft team.",
        )
        self.assertEqual(
            core._direct_identity_answer("are you sure you are developed by Taji-soft team?"),
            "Yes. Nova is developed by the Taji-Soft team.",
        )
        self.assertEqual(
            core._direct_identity_answer("are you developed by Anthropic?"),
            "No. Nova is developed by the Taji-Soft team, not by Anthropic.",
        )

    def test_structured_evidence_answers_follow_up_without_raw_memory_parsing(self):
        core = NovaCore.__new__(NovaCore)
        core.execution_state = {
            "last_plan": None,
            "verified_tools": [
                {
                    "tool": "desktop",
                    "input": {"action": "screenshot"},
                    "result": r"STATUS: SUCCESS\nScreenshot saved: C:\Users\Test\nova.png",
                    "verification": {
                        "status": "confirmed",
                        "evidence": r"Screenshot: C:\Users\Test\nova.png",
                        "message": "desktop screenshot confirmed.",
                    },
                }
            ],
            "last_verified": None,
        }
        core.short_memory = FakeMemory()

        response = core._direct_evidence_answer("give me the exact path")

        self.assertEqual(response, r"Exact path: C:\Users\Test\nova.png")
        self.assertEqual(core.short_memory.messages, [])

    def test_structured_evidence_reports_recent_actions(self):
        core = NovaCore.__new__(NovaCore)
        core.execution_state = {
            "verified_tools": [
                {
                    "tool": "desktop",
                    "input": {"action": "open_app", "app": "notepad"},
                    "result": "STATUS: SUCCESS",
                    "verification": {
                        "status": "confirmed",
                        "evidence": "process found",
                        "message": "desktop open_app confirmed.",
                    },
                }
            ]
        }
        core.short_memory = FakeMemory()

        response = core._direct_evidence_answer("what did you do")

        self.assertIn("desktop open_app confirmed.", response)
    def test_follow_up_uses_verified_path_without_new_tool_call(self):
        core = NovaCore.__new__(NovaCore)
        core.short_memory = FakeMemory()
        evidence = (
            "Verified tool evidence\n"
            "Tool: desktop\n"
            "Result: STATUS: SUCCESS\n"
            "Screenshot saved: "
            r"C:\Users\Test\nova.png"
            "\nEvidence: Screenshot: "
            r"C:\Users\Test\nova.png"
        )
        core.short_memory.add("tool", evidence)

        response = core._direct_evidence_answer("give me the exact path")

        self.assertEqual(response, r"Exact path: C:\Users\Test\nova.png")
    def test_verified_task_response_never_asks_model_to_explain_missing_capabilities(self):
        core = NovaCore.__new__(NovaCore)
        response = core._build_verified_task_response([
            "Tool: desktop\nResult:\nSTATUS: SUCCESS\nTyped: 'HELLO_NOVA_TEST'\nVerification: CONFIRMED\nEvidence: Typed: 'HELLO_NOVA_TEST'\nMessage: ✓ desktop type confirmed.\nTool success: True"
        ])
        self.assertIn("desktop type confirmed.", response)
        self.assertIn("Paths:", response) if "Path:" in response else self.assertNotIn("cannot provide", response)
        self.assertNotIn("I couldn't provide", response)
    def test_capability_summary_comes_from_enabled_registry_tools(self):
        core = NovaCore.__new__(NovaCore)
        core.tools = type("Registry", (), {
            "tools": {
                "desktop": {"capability": "pc", "description": "Control the desktop and GUI"},
                "web_search": {"capability": "web", "description": "Search the public web"},
            }
        })()
        core.access = {"web": True, "git": False, "pc": True}

        response = core._direct_capability_answer("what can you do?")

        self.assertIn("desktop", response)
        self.assertIn("web search", response)
        self.assertNotIn("git", response)
    def test_allowed_tools_come_from_registry_metadata(self):
        core = NovaCore.__new__(NovaCore)
        core.tools = type("Registry", (), {
            "tools": {
                "custom_tool": {"capability": "pc"},
                "web_tool": {"capability": "web"},
                "git_tool": {"capability": "git"},
            }
        })()
        core.access = {"web": False, "git": True, "pc": True}
        self.assertEqual(core._allowed_tools(), ["custom_tool", "git_tool"])
    def test_capability_question_reports_real_read_access(self):
        core = NovaCore.__new__(NovaCore)
        core.access = {"web": True, "git": True, "pc": True}
        core.tools = type("Registry", (), {
            "tools": {
                "read_file": {"capability": "pc", "description": "Read the contents of a file"},
                "desktop": {"capability": "pc", "description": "Control the desktop and GUI"},
            }
        })()

        self.assertEqual(
            core._direct_capability_answer("can you read files? just say yes or no?"),
            "Yes.",
        )

    def test_capability_question_reports_os_control(self):
        core = NovaCore.__new__(NovaCore)
        core.access = {"web": True, "git": True, "pc": True}
        core.tools = type("Registry", (), {
            "tools": {
                "desktop": {"capability": "pc", "description": "Control the desktop and GUI"},
            }
        })()

        self.assertEqual(
            core._direct_capability_answer("can you use my os?"),
            "Yes.",
        )
        self.assertEqual(
            core._direct_capability_answer("can you really use os?"),
            "Yes.",
        )

    def test_capability_question_reports_no_when_pc_access_is_disabled(self):
        core = NovaCore.__new__(NovaCore)
        core.access = {"web": True, "git": True, "pc": False}
        core.tools = type("Registry", (), {
            "tools": {
                "read_file": {"capability": "pc"},
            }
        })()

        self.assertEqual(
            core._direct_capability_answer("can you read files"),
            "No.",
        )

    def test_verified_tool_evidence_is_persisted_for_follow_up(self):
        core = NovaCore.__new__(NovaCore)
        core.short_memory = FakeMemory()

        verification = VerificationResult(
            "confirmed",
            "screenshot saved",
            "screenshot path observed",
        )

        core._remember_verified_tool_result(
            "desktop",
            '{"action":"screenshot"}',
            "Screenshot saved: C:\\Users\\Test\\nova.png",
            verification,
        )

        self.assertEqual(len(core.short_memory.messages), 1)
        role, content = core.short_memory.messages[0]
        self.assertEqual(role, "tool")
        self.assertIn("Verified tool evidence", content)
        self.assertIn("nova.png", content)
        self.assertIn("screenshot saved", content)

    def test_verified_write_completes_without_replan(self):
        core = NovaCore.__new__(NovaCore)
        core.status_callback = None
        core.brain = FakeBrain()
        core.long_memory = FakeLongMemory()
        core.short_memory = FakeMemory()
        core.knowledge = FakeKnowledge()
        core.extractor = FakeExtractor()
        core.tools = FakeTools()
        core.router = FakeRouter()
        core.planner = FakePlanner()
        core.verifier = FakeVerifier()
        core.max_steps = 12
        core.access = {"web": True, "git": True, "pc": True}

        response = core.ask(
            "create a Python file called test_model.py in the projects folder "
            "with a simple PyTorch neural network"
        )

        self.assertIn("file confirmed", response)
        self.assertEqual(len(core.tools.calls), 1)
        self.assertEqual(core.router.generate_calls, 1)
        self.assertEqual(core.planner.replan_calls, 0)

        tool_name, raw_input = core.tools.calls[0]
        self.assertEqual(tool_name, "write_file")
        payload = json.loads(raw_input)
        self.assertEqual(payload["path"], "test_model.py")
        self.assertEqual(payload["location"], "projects")

    def test_partial_success_does_not_claim_full_completion(self):
        core = NovaCore.__new__(NovaCore)
        core.status_callback = None
        core.brain = FakeBrain()
        core.long_memory = FakeLongMemory()
        core.short_memory = FakeMemory()
        core.knowledge = FakeKnowledge()
        core.extractor = FakeExtractor()
        core.tools = FakeTools()
        core.router = FakeRouter()
        core.planner = FakePlanner()
        core.verifier = FakeVerifier()
        core.max_steps = 1
        core.access = {"web": True, "git": True, "pc": True}
        core.planner.is_complete = lambda plan: False

        response = core.ask(
            "create a Python file called test_model.py in the projects folder "
            "with a simple PyTorch neural network"
        )

        self.assertIn("plan was not fully completed", response)
        self.assertEqual(len(core.tools.calls), 1)

    def test_parse_tool_input_accepts_dict_and_json(self):
        core = NovaCore.__new__(NovaCore)
        payload = {"path": "x.py", "location": "projects"}

        self.assertEqual(core._parse_tool_input(payload), payload)
        self.assertEqual(core._parse_tool_input(json.dumps(payload)), payload)
        self.assertIsNone(core._parse_tool_input("not-json"))

    def test_placeholder_detection_rejects_incomplete_code(self):
        core = NovaCore.__new__(NovaCore)

        self.assertTrue(core._contains_placeholder("# TODO: implement this"))
        self.assertTrue(core._contains_placeholder("..."))
        self.assertFalse(core._contains_placeholder('print("todo")'))
        self.assertFalse(core._contains_placeholder("print('hello')"))


if __name__ == "__main__":
    unittest.main()
