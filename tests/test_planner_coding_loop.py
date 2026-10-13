import json
import unittest

from agent.planner import Planner


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
