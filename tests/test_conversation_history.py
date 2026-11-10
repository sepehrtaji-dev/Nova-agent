"""Conversation history must reach the model as REAL chat turns.

Regression test for the reported failure: user asks about Sigma, then asks
"does this have applications in AI?" — Nova must hand the model the prior
exchange as alternating user/assistant messages so pronouns like "this"
resolve to the previous topic.

The old behavior flattened the transcript into a "SESSION CONTEXT" data
block inside the single user message, which small local models cannot use
reliably for coreference.
"""
import unittest
from unittest.mock import MagicMock

from agent.core import NovaCore
from agent.tool_loop import ToolCallingLoop
from memory.short_term import ShortTermMemory


class RecordingBrain:
    supports_tool_calls = True

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def generate_tool_turn(self, messages, tools, system_prompt=None, options=None):
        self.calls.append({
            "system_prompt": system_prompt,
            "messages": [dict(m) for m in messages],
        })
        return {"content": self.answers.pop(0), "tool_calls": []}


def make_core(brain):
    core = NovaCore.__new__(NovaCore)
    from tools import load_tools
    core.tools = load_tools()
    core.brain = brain
    core.thinking_enabled = False
    core.max_steps = 12
    core.access = {"web": True, "git": True, "pc": True}
    core.short_memory = ShortTermMemory(limit=40)
    core.status_callback = None
    core.knowledge = MagicMock()
    core.knowledge.get_context.return_value = ""
    core._long_memory_context = lambda message: ""
    core._episodic_context = lambda message: ""
    core.episodic_memory = MagicMock()
    core.self_knowledge = None
    core.verifier = MagicMock()
    core.router = MagicMock()
    return core


class NativeHistoryTests(unittest.TestCase):
    def test_second_turn_receives_first_exchange_as_real_messages(self):
        brain = RecordingBrain([
            "Sigma (σ) is the Greek letter used for summation in mathematics.",
            "Yes — summation is used throughout machine learning, e.g. loss sums.",
        ])
        core = make_core(brain)

        core.ask("What is the Greek letter Sigma and how is it used in mathematics?")
        core.ask("Does this have applications in artificial intelligence?")

        self.assertEqual(len(brain.calls), 2)
        turn2 = brain.calls[1]["messages"]

        # The prior exchange must appear as REAL alternating messages...
        self.assertEqual(turn2[0]["role"], "user")
        self.assertIn("Sigma", turn2[0]["content"])
        self.assertEqual(turn2[1]["role"], "assistant")
        self.assertIn("summation", turn2[1]["content"])
        # ...and the current question is the LAST user message.
        self.assertEqual(turn2[-1]["role"], "user")
        self.assertIn("artificial intelligence", turn2[-1]["content"])

    def test_current_question_is_not_duplicated_in_history(self):
        brain = RecordingBrain(["a1", "a2", "a3"])
        core = make_core(brain)
        core.ask("question one")
        core.ask("question two")
        turn2 = brain.calls[1]["messages"]
        # The current question may appear only as the final live turn (whose
        # content carries the SESSION CONTEXT suffix) — never as a history turn.
        history_hits = sum(
            m["role"] == "user" and m["content"] == "question two"
            for m in turn2
        )
        self.assertEqual(history_hits, 0)
        self.assertTrue(turn2[-1]["content"].startswith("question two"))

    def test_history_excludes_tool_role_entries(self):
        brain = RecordingBrain(["a1", "a2"])
        core = make_core(brain)
        core.short_memory.add("user", "hello")
        core.short_memory.add("assistant", "hi there")
        core.short_memory.add("tool", "read_file -> ...")  # must be skipped
        core.ask("next question")
        # Inspect what the MODEL actually received on this turn.
        seen = brain.calls[0]["messages"]
        roles = [m["role"] for m in seen]
        self.assertNotIn("tool", roles)
        # prior user + prior assistant + the live current question
        self.assertEqual(roles, ["user", "assistant", "user"])
        self.assertEqual(seen[0]["content"], "hello")
        self.assertEqual(seen[1]["content"], "hi there")
        self.assertTrue(seen[2]["content"].startswith("next question"))

    def test_history_is_bounded_by_char_budget(self):
        brain = RecordingBrain(["a1", "a2"])
        core = make_core(brain)
        for i in range(20):
            core.short_memory.add("user", "x" * 500)
            core.short_memory.add("assistant", "y" * 500)
        core.ask("final question")
        history = core._native_history(max_messages=12, max_chars=6000)
        self.assertLessEqual(len(history), 12)
        total = sum(len(m["content"]) for m in history)
        self.assertLessEqual(total, 7000)  # budget + small overhead

    def test_tool_loop_prepend_skips_malformed_entries(self):
        loop = ToolCallingLoop(
            brain=RecordingBrain(["ok"]),
            tools=MagicMock(),
            verifier=None,
            allowed_tools=["t"],
        )
        loop._definitions = lambda: [{"type": "function", "function": {
            "name": "t", "description": "d", "parameters": {"type": "object", "properties": {}}
        }}]
        loop._generate_turn = lambda messages, definitions, system_prompt: {
            "content": "done", "tool_calls": []
        }
        result = loop.run(
            "current question",
            system_prompt="sys",
            context="CTX",
            history=[
                {"role": "user", "content": "prior question"},
                {"role": "assistant", "content": "prior answer"},
                {"role": "tool", "content": "tool output"},   # skipped
                "not-a-dict",                                  # skipped
                {"role": "user", "content": ""},               # skipped (empty)
            ],
        )
        self.assertEqual(result, "done")


if __name__ == "__main__":
    unittest.main()
