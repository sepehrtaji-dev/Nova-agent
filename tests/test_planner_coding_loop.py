import json
import unittest

from agent.planner import Planner
from tools.registry import ToolRegistry


class FakeTools:
    def exists(self, name):
        return name in {"read_file", "edit_file", "terminal"}

    def get_descriptions(self):
        return (
            "- read_file: Read a text file from an allowed location.\n"
            "- edit_file: Replace text in an existing file.\n"
            "- terminal: Run a command in the project workspace."
        )


class FakeBrain:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def generate(self, prompt, json_mode=False):
        self.prompts.append(prompt)
        return self.response


class PlannerCodingLoopTests(unittest.TestCase):
    def setUp(self):
        self.tools = FakeTools()
        self.planner = Planner(brain=None, tools=self.tools)

    def test_replan_can_put_repair_before_failed_validation_retry(self):
        old_plan = {
            "goal": "Fix a regression",
            "steps": [
                {
                    "id": 1,
                    "description": "Inspect the affected module",
                    "status": "completed",
                    "result": "Module inspected",
                    "tool": "read_file",
                    "input": {"path": "module.py"},
                },
                {
                    "id": 2,
                    "description": "Run project validation",
                    "status": "pending",
                    "result": None,
                    "tool": "terminal",
                    "input": {"command": "python -m unittest"},
                },
            ],
        }

        steps = [
            {
                "description": "Inspect the affected module",
                "status": "completed",
                "tool": "read_file",
                "input": {"path": "module.py"},
            },
            {
                "description": "Correct the cause shown by the failure",
                "status": "pending",
                "tool": "edit_file",
                "input": {
                    "path": "module.py",
                    "old": "old expression",
                    "new": "corrected expression",
                },
            },
            {
                "description": "Run project validation",
                "status": "pending",
                "tool": "terminal",
                "input": {"command": "python -m unittest"},
            },
        ]

        normalized = self.planner._normalize_replanned_steps(
            steps, old_plan
        )

        self.assertEqual(
            [step["description"] for step in normalized],
            [
                "Inspect the affected module",
                "Correct the cause shown by the failure",
                "Run project validation",
            ],
        )
        self.assertEqual(normalized[0]["status"], "completed")
        self.assertEqual(normalized[0]["result"], "Module inspected")

    def test_model_cannot_mark_new_step_completed_without_evidence(self):
        old_plan = {
            "goal": "Make a change",
            "steps": [
                {
                    "id": 1,
                    "description": "Inspect source",
                    "status": "completed",
                    "result": "Read source",
                    "tool": "read_file",
                    "input": {"path": "module.py"},
                }
            ],
        }

        normalized = self.planner._normalize_replanned_steps(
            [
                {
                    "description": "Inspect source",
                    "status": "completed",
                    "tool": "read_file",
                    "input": {"path": "module.py"},
                },
                {
                    "description": "Run the relevant checks",
                    "status": "completed",
                    "tool": "terminal",
                    "input": {"command": "python -m unittest"},
                },
            ],
            old_plan,
        )

        self.assertEqual(normalized[0]["status"], "completed")
        self.assertEqual(normalized[1]["status"], "pending")

    def test_plan_rejects_inputs_that_violate_registered_tool_schema(self):
        registry = ToolRegistry()
        registry.register(
            "read_file",
            "Read a file",
            lambda payload: payload,
            capability="pc",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        )
        brain = FakeBrain(json.dumps({
            "goal": "Read a file",
            "steps": [{
                "description": "Read the requested file",
                "tool": "read_file",
                "input": {"unexpected": "value"},
            }],
        }))
        planner = Planner(brain=brain, tools=registry)

        plan = planner.create_plan(
            "Read the requested file",
            allowed_tools=["read_file"],
        )

        self.assertEqual(plan["steps"], [])

    def test_plan_never_offers_or_accepts_disabled_tools(self):
        registry = ToolRegistry()
        registry.register(
            "read_file",
            "Read a file",
            lambda payload: payload,
            capability="pc",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
            },
        )
        registry.register(
            "terminal",
            "Run a command",
            lambda payload: payload,
            capability="pc",
            input_schema={
                "type": "object",
                "required": ["command"],
                "properties": {"command": {"type": "string"}},
            },
        )
        brain = FakeBrain(json.dumps({
            "goal": "Read a file",
            "steps": [{
                "description": "Read the requested file",
                "tool": "read_file",
                "input": {"path": "secret.txt"},
            }],
        }))
        planner = Planner(brain=brain, tools=registry)

        plan = planner.create_plan(
            "Read the requested file",
            allowed_tools=["terminal"],
        )

        self.assertEqual(plan["steps"], [])
        self.assertIn("- terminal:", brain.prompts[0])
        self.assertNotIn("- read_file:", brain.prompts[0])

    def test_verified_success_replans_and_can_add_evidence_driven_steps(self):
        class SequenceBrain:
            def __init__(self):
                self.prompts = []
            def generate(self, prompt, json_mode=False):
                self.prompts.append(prompt)
                return json.dumps({
                    "goal": "Inspect and improve the module",
                    "steps": [
                        {
                            "description": "Read the target module",
                            "tool": "read_file",
                            "input": {"path": "module.py"},
                        },
                        {
                            "description": "Run the test suite discovered in the project",
                            "tool": "terminal",
                            "input": {"command": "python -m unittest"},
                        },
                    ],
                })

        brain = SequenceBrain()
        planner = Planner(brain=brain, tools=self.tools)
        old_plan = {
            "goal": "Inspect and improve the module",
            "steps": [{
                "id": 1,
                "description": "Read the target module",
                "status": "pending",
                "result": None,
                "tool": "read_file",
                "input": {"path": "module.py"},
            }],
        }

        updated = planner.replan(
            plan=old_plan,
            goal="Inspect and improve the module",
            tool_name="read_file",
            tool_input={"path": "module.py"},
            result="module source contents",
            success=True,
            allowed_tools=["read_file", "terminal"],
        )

        self.assertEqual(updated["steps"][0]["status"], "completed")
        self.assertEqual(updated["steps"][0]["result"], "module source contents")
        self.assertEqual(updated["steps"][1]["status"], "pending")
        self.assertEqual(updated["steps"][1]["tool"], "terminal")

    def test_failed_replan_fallback_retires_stale_step(self):
        class InvalidBrain:
            def generate(self, prompt, json_mode=False):
                return "not valid JSON"

        planner = Planner(brain=InvalidBrain(), tools=self.tools)
        old_plan = {
            "goal": "Inspect a module",
            "steps": [{
                "id": 1,
                "description": "Read module.py",
                "status": "pending",
                "result": None,
                "tool": "read_file",
                "input": {"path": "module.py"},
            }],
        }

        updated = planner.replan(
            plan=old_plan,
            goal="Inspect a module",
            tool_name="read_file",
            tool_input={"path": "module.py"},
            result="File not found",
            success=False,
        )

        self.assertEqual(updated["steps"][0]["status"], "failed")
        self.assertEqual(updated["steps"][0]["result"], "File not found")
        self.assertIsNone(planner.get_next_step(updated))
        self.assertIn("replan_error", updated)

    def test_failed_step_is_skipped_when_selecting_next_pending_step(self):
        plan = {
            "goal": "Recover from a failed read",
            "steps": [
                {"id": 1, "description": "Read missing file", "status": "failed"},
                {"id": 2, "description": "List project files", "status": "pending"},
            ],
        }
        self.assertEqual(
            self.planner.get_next_step(plan)["description"],
            "List project files",
        )

    def test_invalid_json_uses_a_distinct_format_repair_prompt(self):
        class SequenceBrain:
            def __init__(self):
                self.responses = [
                    "this is not JSON",
                    json.dumps({
                        "goal": "Read module",
                        "steps": [{
                            "description": "Read module.py",
                            "tool": "read_file",
                            "input": {"path": "module.py"},
                        }],
                    }),
                ]
                self.prompts = []
            def generate(self, prompt, json_mode=False):
                self.prompts.append(prompt)
                return self.responses.pop(0)

        brain = SequenceBrain()
        planner = Planner(brain=brain, tools=self.tools)
        plan = planner.create_plan("Read module")

        self.assertEqual(len(plan["steps"]), 1)
        self.assertEqual(len(brain.prompts), 2)
        self.assertIn("previous response was not valid planner JSON", brain.prompts[1])

    def test_schema_rejection_triggers_argument_repair(self):
        registry = ToolRegistry()
        registry.register(
            "read_file",
            "Read a file",
            lambda payload: payload,
            capability="pc",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        )

        class SequenceBrain:
            def __init__(self):
                self.responses = [
                    json.dumps({
                        "goal": "Read module",
                        "steps": [{
                            "description": "Read module.py",
                            "tool": "read_file",
                            "input": {"wrong": "module.py"},
                        }],
                    }),
                    json.dumps({
                        "goal": "Read module",
                        "steps": [{
                            "description": "Read module.py",
                            "tool": "read_file",
                            "input": {"path": "module.py"},
                        }],
                    }),
                ]
                self.prompts = []
            def generate(self, prompt, json_mode=False):
                self.prompts.append(prompt)
                return self.responses.pop(0)

        brain = SequenceBrain()
        planner = Planner(brain=brain, tools=registry)
        plan = planner.create_plan("Read module", allowed_tools=["read_file"])

        self.assertEqual(len(plan["steps"]), 1)
        self.assertEqual(plan["steps"][0]["input"], {"path": "module.py"})
        self.assertEqual(len(brain.prompts), 2)
        self.assertIn("VALIDATION FEEDBACK", brain.prompts[1])

    def test_plan_prompt_uses_project_evidence_not_a_fixed_workflow(self):
        brain = FakeBrain(json.dumps({
            "goal": "Improve a module",
            "steps": [
                {
                    "description": "Inspect the relevant source",
                    "tool": "read_file",
                    "input": {"path": "module.py"},
                }
            ],
        }))
        planner = Planner(brain=brain, tools=self.tools)

        plan = planner.create_plan("Improve a module", context="Existing project")

        self.assertEqual(len(plan["steps"]), 1)
        prompt = brain.prompts[0]
        self.assertIn("Choose validation steps from the project's observed files", prompt)
        self.assertIn("Do not assume a language, framework, test runner", prompt)
        self.assertNotIn("For GitHub repo creation the steps must be in order", prompt)

    def test_step_without_description_is_kept_not_dropped(self):
        """Regression: valid {tool, input} steps were discarded.

        The planner often emits a tool call with no narration. Requiring
        `description` silently dropped every such step, leaving an empty plan,
        so the tool never ran and the raw call text was returned to the user.
        """
        brain = FakeBrain(json.dumps({
            "goal": "Search the web",
            "steps": [
                {"tool": "read_file", "input": {"path": "module.py"}},
            ],
        }))
        planner = Planner(brain=brain, tools=self.tools)

        plan = planner.create_plan("Search the web", context="")

        self.assertEqual(len(plan["steps"]), 1)
        step = plan["steps"][0]
        self.assertEqual(step["tool"], "read_file")
        self.assertEqual(step["input"], {"path": "module.py"})
        self.assertTrue(step["description"].strip())

    def test_step_with_empty_description_is_kept(self):
        brain = FakeBrain(json.dumps({
            "goal": "Search",
            "steps": [
                {"description": "   ", "tool": "read_file",
                 "input": {"path": "x.py"}},
            ],
        }))
        planner = Planner(brain=brain, tools=self.tools)
        plan = planner.create_plan("Search", context="")
        self.assertEqual(len(plan["steps"]), 1)

    def test_step_with_unknown_tool_is_still_dropped(self):
        """Relaxing the description rule must not admit phantom tools."""
        brain = FakeBrain(json.dumps({
            "goal": "Do something",
            "steps": [
                {"tool": "not_a_real_tool", "input": {"x": 1}},
            ],
        }))
        planner = Planner(brain=brain, tools=self.tools)
        plan = planner.create_plan("Do something", context="")
        self.assertEqual(plan["steps"], [])

    def test_step_without_tool_is_still_dropped(self):
        brain = FakeBrain(json.dumps({
            "goal": "Do something",
            "steps": [
                {"description": "Just thinking out loud", "input": {"x": 1}},
            ],
        }))
        planner = Planner(brain=brain, tools=self.tools)
        plan = planner.create_plan("Do something", context="")
        self.assertEqual(plan["steps"], [])

    def test_step_with_non_object_input_is_still_dropped(self):
        brain = FakeBrain(json.dumps({
            "goal": "Do something",
            "steps": [
                {"tool": "read_file", "input": "module.py"},
            ],
        }))
        planner = Planner(brain=brain, tools=self.tools)
        plan = planner.create_plan("Do something", context="")
        self.assertEqual(plan["steps"], [])


if __name__ == "__main__":
    unittest.main()
