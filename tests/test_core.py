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

    def test_capability_question_reports_real_read_access(self):
        core = NovaCore.__new__(NovaCore)
        core.access = {"web": True, "git": True, "pc": True}

        self.assertEqual(
            core._direct_capability_answer("can you read files? just say yes or no?"),
            "Yes.",
        )

    def test_capability_question_reports_os_control(self):
        core = NovaCore.__new__(NovaCore)
        core.access = {"web": True, "git": True, "pc": True}

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
        self.assertIn("screenshot path observed", content)

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

        self.assertIn("created successfully", response)
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
