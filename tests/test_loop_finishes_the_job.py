"""The loop must finish what the user asked for, not stop after the search."""
import json
import unittest

from agent.tool_loop import ToolCallingLoop
from tools.registry import ToolRegistry

REQUEST = ("please search web about best local ai models and write me a readme file "
           "about research result")
SEARCH_RESULT = "[1] Title: Qwen3 is a strong local model\nURL: https://example.org/qwen\nSnippet: Great at tools."


class Result:
    def __init__(self, status="confirmed"):
        self.status, self.message, self.evidence = status, status, ""

    def confirmed(self):
        return self.status == "confirmed"


class Verifier:
    def verify(self, name, encoded, result):
        return Result("failed" if result.startswith("ERROR") else "confirmed")


class ScriptedBrain:
    context_window_tokens = 16384

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []  # (message list, tool names offered)

    def generate_tool_turn(self, *, messages, tools, system_prompt):
        self.seen.append((json.loads(json.dumps(messages)), [t["function"]["name"] for t in tools]))
        return self.turns.pop(0)


def call(name, **arguments):
    return {"function": {"name": name, "arguments": arguments}}


def make_registry(captured, write_ok=True):
    reg = ToolRegistry()
    reg.register("web_search", "Search the web.", lambda payload: SEARCH_RESULT,
                 capability="web", input_schema={"type": "object", "properties": {"query": {"type": "string"}}})

    def prepare_write(arguments, context):
        captured["tool_history"] = context.get("tool_history", "")
        return arguments

    def write(payload):
        data = json.loads(payload)
        captured["written"] = data
        return "FILE_CREATED" if write_ok else "ERROR disk full"

    reg.register("write_file", "Write a file.", write, capability="pc", prepare_input=prepare_write,
                 input_schema={"type": "object", "required": ["path", "content"],
                               "properties": {"path": {"type": "string"}, "content": {"type": "string"}}})
    reg.register("read_file", "Read a file.", lambda payload: "x", capability="pc",
                 input_schema={"type": "object", "properties": {}})
    return reg


def run_loop(brain, reg):
    statuses = []
    loop = ToolCallingLoop(brain, reg, Verifier(), {"web_search", "write_file", "read_file"},
                           status=statuses.append)
    return loop.run(REQUEST, system_prompt="s"), statuses


class FinishTheJobTests(unittest.TestCase):
    def test_search_then_announcement_is_not_accepted_and_the_file_gets_written(self):
        captured = {}
        brain = ScriptedBrain([
            {"content": "", "tool_calls": [call("web_search", query="best local ai models")]},
            # The failure from the field: it searched, then only talked about the next step.
            {"content": "Great, now I will write the README with the findings.", "tool_calls": []},
            {"content": "", "tool_calls": [call("write_file", path="README.md", content="# Local AI models\n\nQwen3 is strong.")]},
            {"content": "I searched the web and wrote README.md.", "tool_calls": []},
        ])
        answer, statuses = run_loop(brain, make_registry(captured))
        self.assertEqual(answer, "I searched the web and wrote README.md.")
        self.assertEqual(captured["written"]["path"], "README.md")
        self.assertIn("MODEL_ANSWER_RESET", statuses)
        nudge = brain.seen[2][0][-1]
        self.assertEqual(nudge["role"], "user")
        self.assertIn("written the requested file", nudge["content"])
        self.assertIn("write_file", nudge["content"])

    def test_tool_result_carries_a_reminder_of_the_original_request(self):
        brain = ScriptedBrain([
            {"content": "", "tool_calls": [call("web_search", query="best local ai models")]},
            {"content": "", "tool_calls": [call("write_file", path="README.md", content="# x")]},
            {"content": "Done.", "tool_calls": []},
        ])
        run_loop(brain, make_registry({}))
        search_result = [m for m in brain.seen[1][0] if m["role"] == "tool"][0]
        reminder = json.loads(search_result["content"])["reminder"]
        self.assertIn("write me a readme file", reminder)
        self.assertIn("written the requested file", reminder)
        # Once everything is done there is nothing to remind about.
        write_result = [m for m in brain.seen[2][0] if m["role"] == "tool"][-1]
        self.assertNotIn("reminder", json.loads(write_result["content"]))

    def test_a_model_that_keeps_talking_gets_only_the_missing_tool(self):
        brain = ScriptedBrain([
            {"content": "", "tool_calls": [call("web_search", query="best local ai models")]},
            {"content": "I will write it next.", "tool_calls": []},       # nudge 1: all tools
            {"content": "Let me write the file now.", "tool_calls": []},   # nudge 2: narrowed
            {"content": "", "tool_calls": [call("write_file", path="README.md", content="# done")]},
            {"content": "Finished.", "tool_calls": []},
        ])
        answer, _ = run_loop(brain, make_registry({}))
        self.assertEqual(answer, "Finished.")
        offered_per_turn = [tools for _, tools in brain.seen]
        self.assertIn("read_file", offered_per_turn[2])   # after the first nudge: everything
        self.assertEqual(offered_per_turn[3], ["write_file"])  # after the second: only the writer

    def test_unfinished_work_is_reported_honestly(self):
        talk = {"content": "I will write the README soon.", "tool_calls": []}
        brain = ScriptedBrain([
            {"content": "", "tool_calls": [call("web_search", query="best local ai models")]},
            dict(talk), dict(talk), dict(talk), dict(talk), dict(talk),
        ])
        answer, _ = run_loop(brain, make_registry({}))
        self.assertIn("I will write the README soon.", answer)
        self.assertIn("this is not complete", answer)
        self.assertIn("written the requested file", answer)

    def test_a_failed_write_does_not_count_as_done(self):
        brain = ScriptedBrain([
            {"content": "", "tool_calls": [call("web_search", query="best local ai models")]},
            {"content": "", "tool_calls": [call("write_file", path="README.md", content="# x")]},
            {"content": "All done.", "tool_calls": []},      # the write failed: must not be accepted
            {"content": "", "tool_calls": [call("write_file", path="docs/README.md", content="# x")]},
            # Nudged a few more times, then the answer is accepted with an honest note.
        ] + [{"content": "Gave up.", "tool_calls": []}] * 6)
        answer, _ = run_loop(brain, make_registry({}, write_ok=False))
        self.assertIn("not complete", answer)

    def test_write_file_receives_the_research_not_the_session_context(self):
        captured = {}
        brain = ScriptedBrain([
            {"content": "", "tool_calls": [call("web_search", query="best local ai models")]},
            {"content": "", "tool_calls": [call("write_file", path="README.md", content="# x")]},
            {"content": "Done.", "tool_calls": []},
        ])
        statuses = []
        loop = ToolCallingLoop(brain, make_registry(captured), Verifier(),
                               {"web_search", "write_file", "read_file"}, status=statuses.append)
        loop.run(REQUEST, system_prompt="s", context="REGISTRY " * 2000)
        ledger = captured["tool_history"]
        self.assertIn("Qwen3 is a strong local model", ledger)
        self.assertIn("[web_search]", ledger)
        self.assertNotIn("REGISTRY", ledger)

    def test_prompt_is_fitted_so_the_request_survives_a_huge_search_result(self):
        reg = ToolRegistry()
        reg.register("web_search", "Search.", lambda payload: "snippet " * 6000, capability="web",
                     input_schema={"type": "object", "properties": {}})
        reg.register("write_file", "Write.", lambda payload: "FILE_CREATED", capability="pc",
                     input_schema={"type": "object", "properties": {}})
        brain = ScriptedBrain([
            {"content": "", "tool_calls": [call("web_search", query="x")]},
            {"content": "", "tool_calls": [call("write_file", path="README.md", content="# x")]},
            {"content": "Done.", "tool_calls": []},
        ])
        brain.context_window_tokens = 8192
        loop = ToolCallingLoop(brain, reg, Verifier(), {"web_search", "write_file"})
        loop.run(REQUEST, system_prompt="s" * 3000, context="CTX " * 4000)
        sent, _ = brain.seen[1]
        self.assertIn("write me a readme file", sent[0]["content"])
        size = sum(len(json.dumps(m)) for m in sent)
        self.assertLess(size // 3, 8192, "request plus results must fit the context window")


if __name__ == "__main__":
    unittest.main()
