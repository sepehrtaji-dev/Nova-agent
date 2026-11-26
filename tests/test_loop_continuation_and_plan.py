import json
import unittest

from agent.tool_loop import ToolCallingLoop
from tools.registry import ToolRegistry
from tools.task_plan import TaskPlanTool, normalize_plan, open_steps


class Result:
    def __init__(self, status):
        self.status = status
        self.message = status
        self.evidence = ""

    def confirmed(self):
        return self.status == "confirmed"


class Verifier:
    def verify(self, name, encoded, result):
        return Result("failed" if "BOOM" in result else "confirmed")


class Brain:
    def __init__(self, turns):
        self.turns = list(turns)
        self.messages_seen = []

    def generate_tool_turn(self, *, messages, tools, system_prompt):
        self.messages_seen.append(json.loads(json.dumps(messages)))
        if not self.turns:
            raise AssertionError("Unexpected extra model turn")
        return self.turns.pop(0)


def call(name, **arguments):
    return {"function": {"name": name, "arguments": arguments}}


def registry(outputs):
    reg = ToolRegistry()
    reg.register(
        "work", "Do a unit of work.",
        lambda payload: outputs.pop(0),
        capability="pc",
        input_schema={"type": "object", "properties": {}},
    )
    plan_tool = TaskPlanTool()
    reg.register(
        "update_plan", "Update the task list.", plan_tool.update_plan,
        capability="pc",
        input_schema={"type": "object", "required": ["steps"], "properties": {"steps": {"type": "array"}}},
    )
    return reg


def make_loop(brain, reg, statuses, **kw):
    return ToolCallingLoop(
        brain, reg, Verifier(), {"work", "update_plan"},
        status=statuses.append, **kw,
    )


class ContinuationTests(unittest.TestCase):
    def test_failed_tool_is_not_accepted_as_a_final_answer(self):
        statuses = []
        brain = Brain([
            {"content": "", "tool_calls": [call("work")]},
            {"content": "All done!", "tool_calls": []},          # premature
            {"content": "", "tool_calls": [call("work")]},
            {"content": "Finished and verified.", "tool_calls": []},
        ])
        loop = make_loop(brain, registry(["BOOM broke", "OK worked"]), statuses)
        self.assertEqual(loop.run("go", system_prompt="s"), "Finished and verified.")
        nudge = brain.messages_seen[2][-1]
        self.assertEqual(nudge["role"], "user")
        self.assertIn("not finished", nudge["content"])
        self.assertIn("work:", nudge["content"])
        self.assertIn("MODEL_ANSWER_RESET", statuses)

    def test_open_checklist_items_keep_the_loop_working(self):
        statuses = []
        plan1 = [{"description": "Step A", "status": "pending"}, {"description": "Step B", "status": "pending"}]
        plan2 = [{"description": "Step A", "status": "completed"}, {"description": "Step B", "status": "completed"}]
        brain = Brain([
            {"content": "", "tool_calls": [call("update_plan", steps=plan1)]},
            {"content": "Done.", "tool_calls": []},               # plan still open
            {"content": "", "tool_calls": [call("update_plan", steps=plan2)]},
            {"content": "Really done.", "tool_calls": []},
        ])
        loop = make_loop(brain, registry([]), statuses)
        self.assertEqual(loop.run("go", system_prompt="s"), "Really done.")
        plans = [json.loads(s[len("TASK_PLAN:"):]) for s in statuses if s.startswith("TASK_PLAN:")]
        self.assertEqual(len(plans), 2)
        self.assertEqual([x["status"] for x in plans[0]["steps"]], ["pending", "pending"])
        self.assertEqual([x["status"] for x in plans[1]["steps"]], ["completed", "completed"])

    def test_continuations_are_bounded(self):
        statuses = []
        plan = [{"description": "Never finished", "status": "pending"}]
        turns = [{"content": "", "tool_calls": [call("update_plan", steps=plan)]}]
        turns += [{"content": "I am done.", "tool_calls": []}] * 5
        loop = make_loop(Brain(turns), registry([]), statuses, max_continuations=2)
        # Two nudges, then the answer is accepted rather than looping forever.
        self.assertEqual(loop.run("go", system_prompt="s"), "I am done.")

    def test_clean_run_is_not_nudged(self):
        statuses = []
        brain = Brain([
            {"content": "", "tool_calls": [call("work")]},
            {"content": "Done.", "tool_calls": []},
        ])
        loop = make_loop(brain, registry(["fine"]), statuses)
        self.assertEqual(loop.run("go", system_prompt="s"), "Done.")
        self.assertNotIn("MODEL_ANSWER_RESET", statuses)

    def test_dropped_calls_are_reported_to_the_model(self):
        statuses = []
        brain = Brain([
            {"content": "", "tool_calls": [call("work")] * 8},
            {"content": "Done.", "tool_calls": []},
        ])
        loop = make_loop(brain, registry(["ok"] * 8), statuses)
        loop.run("go", system_prompt="s")
        last_tool = [m for m in brain.messages_seen[1] if m["role"] == "tool"][-1]
        self.assertIn("not run", json.loads(last_tool["content"])["notice"])


class TaskPlanToolTests(unittest.TestCase):
    def test_normalizes_statuses_and_strings(self):
        steps = normalize_plan(["Plan it", {"description": "Ship", "status": "DONE"}, {"description": "x", "status": "in-progress"}])
        self.assertEqual([s["status"] for s in steps], ["pending", "completed", "in_progress"])

    def test_rejects_empty_and_blank_steps(self):
        with self.assertRaises(ValueError):
            normalize_plan([])
        with self.assertRaises(ValueError):
            normalize_plan([{"description": "  "}])

    def test_open_steps_includes_failed(self):
        steps = normalize_plan([{"description": "a", "status": "failed"}, {"description": "b", "status": "completed"}])
        self.assertEqual([s["description"] for s in open_steps(steps)], ["a"])

    def test_tool_reports_progress(self):
        out = json.loads(TaskPlanTool().update_plan(json.dumps({"steps": [
            {"description": "a", "status": "completed"}, {"description": "b", "status": "pending"}]})))
        self.assertTrue(out["ok"])
        self.assertEqual((out["completed"], out["total"], out["remaining"]), (1, 2, 1))

    def test_tool_returns_error_for_bad_input(self):
        self.assertFalse(json.loads(TaskPlanTool().update_plan("not json"))["ok"])
        self.assertFalse(json.loads(TaskPlanTool().update_plan(json.dumps({"steps": []})))["ok"])


class ManifestTests(unittest.TestCase):
    def test_update_plan_is_registered_from_the_manifest(self):
        from tools import load_tools
        tools = load_tools()
        self.assertTrue(tools.exists("update_plan"))


if __name__ == "__main__":
    unittest.main()
