"""Regression: an empty tool registry must not mute the assistant.

Nova used to answer every message — even a plain greeting — with the canned
line "No tools are enabled for this session, so I cannot perform that
action" whenever the tool manifest failed to load (for example inside a
packaged build) or when every capability group was disabled. Conversation
must still work without tools; only tool-dependent requests need the
explanation, and that explanation must say how to fix the situation.
"""
import unittest

from agent.core import NovaCore


class EmptyRegistry:
    def __init__(self):
        self.tools = {}
        self.default_access = {}


class StubBrain:
    supports_tool_calls = True

    def __init__(self):
        self.generate_calls = []

    def generate(self, prompt, system_prompt=None, **kwargs):
        self.generate_calls.append(prompt)
        if "report.txt" in prompt or "read the file" in prompt:
            return (
                "I can't read files in this session because no tools are "
                "available right now."
            )
        return "سلام! من نووا هستم. خوشحالم که اینجایی — امروز چکار می‌کنیم؟"


class StubMemory:
    def __init__(self):
        self.entries = []

    def add(self, role, content):
        self.entries.append((role, content))

    def get(self):
        return list(self.entries)

    def format_for_prompt(self, max_chars=12000):
        return "No previous conversation."


class StubKnowledge:
    def get_context(self, message):
        return ""


class StubExtractor:
    def should_extract(self, message):
        return False


class StubLongMemory:
    def remember(self, category, key, value):
        return None


def _build_core():
    core = NovaCore.__new__(NovaCore)
    core.tools = EmptyRegistry()
    core.access = {}
    core.status_callback = None
    core.thinking_enabled = False
    core.short_memory = StubMemory()
    core.knowledge = StubKnowledge()
    core.extractor = StubExtractor()
    core.long_memory = StubLongMemory()
    core.brain = StubBrain()
    return core


class NoToolsConversationTests(unittest.TestCase):
    def test_greeting_gets_a_real_answer_without_tools(self):
        core = _build_core()
        answer = core.ask("سلام")

        self.assertNotIn("No tools are enabled", answer)
        self.assertTrue(core.brain.generate_calls)
        self.assertIn("سلام", answer)

    def test_disabled_capabilities_still_answer_conversationally(self):
        core = _build_core()
        core.tools = type(
            "Registry",
            (),
            {"tools": {"read_file": {"capability": "pc"}}, "default_access": {}},
        )()
        core.access = {"web": False, "git": False, "pc": False}

        answer = core.ask("who are you?")

        self.assertNotIn("No tools are enabled", answer)
        self.assertTrue(core.brain.generate_calls)

    def test_tool_request_reports_the_cause_instead_of_a_canned_line(self):
        core = _build_core()

        answer = core.ask("please read the file report.txt for me")

        self.assertNotIn("so I cannot perform that action", answer)
        self.assertTrue(core.brain.generate_calls)

    def test_model_failure_falls_back_to_an_actionable_explanation(self):
        core = _build_core()

        class BrokenBrain(StubBrain):
            def generate(self, prompt, system_prompt=None, **kwargs):
                raise RuntimeError("provider unreachable")

        core.brain = BrokenBrain()
        answer = core.ask("hello there")

        self.assertNotIn("so I cannot perform that action", answer)
        self.assertIn("no tools", answer.lower())
        self.assertIn("manifest", answer.lower())

    def test_reason_names_the_manifest_when_the_registry_is_empty(self):
        core = _build_core()

        reason = core._no_tools_reason()

        self.assertIn("manifest", reason.lower())
        self.assertIn("NOVA_TOOL_MANIFEST", reason)

    def test_reason_names_the_toggles_when_capabilities_are_disabled(self):
        core = _build_core()
        core.tools = type(
            "Registry",
            (),
            {"tools": {"read_file": {"capability": "pc"}}, "default_access": {}},
        )()
        core.access = {"web": False, "git": False, "pc": False}

        reason = core._no_tools_reason()

        self.assertIn("/web", reason)
        self.assertIn("/git", reason)
        self.assertIn("/pc", reason)


if __name__ == "__main__":
    unittest.main()
