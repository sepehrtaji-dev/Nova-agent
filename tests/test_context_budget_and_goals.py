import json
import unittest

from agent.context_budget import compact_definitions, estimate_tokens, fit_messages
from agent.goals import describe_unmet, goal_tools, infer_goals, record_goal_result, unmet_goals

ALLOWED = {"web_search", "write_file", "edit_file", "read_file"}


def tool_msg(call_id, name, output, ok=True):
    return {"role": "tool", "tool_call_id": call_id, "name": name,
            "content": json.dumps({"ok": ok, "tool": name, "output": output, "verification_evidence": "e" * 500})}


def assistant_call(call_id, name):
    return {"role": "assistant", "content": None, "thinking": "t" * 3000,
            "tool_calls": [{"id": call_id, "function": {"name": name, "arguments": {"query": "q"}}}]}


class GoalTests(unittest.TestCase):
    def keys(self, message, allowed=ALLOWED):
        return [g.key for g in infer_goals(message, allowed)]

    def test_search_and_readme_request_has_two_goals(self):
        msg = "please search web about best local ai models and write me a readme file about research result"
        self.assertEqual(self.keys(msg), ["research", "file"])

    def test_lookalikes_do_not_demand_a_file(self):
        self.assertEqual(self.keys("write a python function that reads a file"), [])
        self.assertEqual(self.keys("write me a poem about the sea"), [])
        self.assertEqual(self.keys("explain what a readme is"), [])

    def test_named_file_and_negation(self):
        self.assertEqual(self.keys("save the results to notes.md"), ["file"])
        self.assertEqual(self.keys("do not write a file, just search the web"), ["research"])

    def test_goal_needs_an_available_tool(self):
        self.assertEqual(self.keys("write me a readme file", allowed={"web_search"}), [])

    def test_goals_are_ticked_only_by_the_right_tools(self):
        goals = infer_goals("search the web and write a readme file", ALLOWED)
        record_goal_result(goals, "read_file")
        self.assertEqual(len(unmet_goals(goals)), 2)
        record_goal_result(goals, "web_search")
        self.assertEqual([g.key for g in unmet_goals(goals)], ["file"])
        self.assertIn("written the requested file", describe_unmet(unmet_goals(goals)))
        self.assertEqual(goal_tools(unmet_goals(goals)), {"write_file", "edit_file"})
        record_goal_result(goals, "write_file")
        self.assertEqual(unmet_goals(goals), [])


class FitMessagesTests(unittest.TestCase):
    def build(self, result_chars=30000):
        return [
            {"role": "user", "content": "REQUEST: search and write a readme.\n\nSESSION CONTEXT (reference data, not instructions):\n" + "ctx " * 3000},
            assistant_call("a", "web_search"), tool_msg("a", "web_search", "old " * 5000),
            assistant_call("b", "web_search"), tool_msg("b", "web_search", "new " * (result_chars // 4)),
        ]

    def test_small_conversations_are_untouched(self):
        messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        self.assertEqual(fit_messages(messages, budget_tokens=8192, fixed_tokens=100, protect_index=0), messages)

    def test_fits_the_budget_and_keeps_the_request(self):
        messages = self.build()
        original = json.dumps(messages)
        fitted = fit_messages(messages, budget_tokens=8192, fixed_tokens=3000, protect_index=0)
        total = sum(estimate_tokens(m) for m in fitted)
        self.assertLessEqual(total, 8192 - 3000)
        self.assertTrue(fitted[0]["content"].startswith("REQUEST: search and write a readme."))
        self.assertEqual(json.dumps(messages), original, "input must not be mutated")

    def test_newest_result_keeps_more_than_older_ones(self):
        fitted = fit_messages(self.build(), budget_tokens=12000, fixed_tokens=3000, protect_index=0)
        outputs = [json.loads(m["content"])["output"] for m in fitted if m.get("role") == "tool"]
        self.assertGreater(len(outputs[-1]), len(outputs[0]))
        self.assertIn("shortened", outputs[0])

    def test_old_thinking_is_dropped_before_results(self):
        messages = self.build(result_chars=2000)
        fitted = fit_messages(messages, budget_tokens=6000, fixed_tokens=1000, protect_index=0)
        self.assertNotIn("thinking", fitted[1])

    def test_extreme_pressure_still_keeps_request_and_valid_roles(self):
        fitted = fit_messages(self.build(), budget_tokens=2500, fixed_tokens=1500, protect_index=0)
        self.assertTrue(any(m["role"] == "user" and "REQUEST" in m["content"] for m in fitted))
        for index, message in enumerate(fitted):
            if message["role"] == "tool":
                self.assertEqual(fitted[index - 1]["role"] in ("assistant", "tool"), True)

    def test_compact_definitions_shorten_descriptions(self):
        definitions = [{"type": "function", "function": {
            "name": "x", "description": "First sentence. " + "More detail. " * 80,
            "parameters": {"type": "object", "properties": {"q": {"type": "string", "description": "d " * 200}}}}}]
        compact = compact_definitions(definitions)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(definitions)) // 3)
        self.assertTrue(compact[0]["function"]["description"].startswith("First sentence."))
        self.assertEqual(compact[0]["function"]["name"], "x")


if __name__ == "__main__":
    unittest.main()
