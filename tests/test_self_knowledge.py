import unittest
from types import SimpleNamespace

from agent.self_knowledge import SelfKnowledge


class SelfKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.core = SimpleNamespace(
            brain=SimpleNamespace(model="qwen2.5:3b"),
            access={"web": True, "git": False, "pc": True},
            tools=SimpleNamespace(tools={
                "web_search": {
                    "description": "Search the public web for current information.",
                    "capability": "web",
                },
                "git": {
                    "description": "Run supported Git operations.",
                    "capability": "git",
                },
                "read_file": {
                    "description": "Read a text file.",
                    "capability": "pc",
                },
            }),
        )
        self.knowledge = SelfKnowledge()

    def test_snapshot_uses_actual_configured_model_and_runtime_tools(self):
        state = self.knowledge.snapshot(self.core)
        self.assertEqual(state["configured_model"], "qwen2.5:3b")
        self.assertEqual(
            {tool["name"]: tool["enabled"] for tool in state["tools"]},
            {"git": False, "read_file": True, "web_search": True},
        )
        self.assertEqual(state["model_provider"], "Ollama")

    def test_model_answer_does_not_claim_model_is_loaded(self):
        answer = self.knowledge.answer("Which model are you using?", self.core)
        self.assertIn("qwen2.5:3b", answer)
        self.assertIn("not verified", answer)

    def test_tool_answer_distinguishes_enabled_and_disabled(self):
        answer = self.knowledge.answer("What tools do you have?", self.core)
        self.assertIn("web search", answer)
        self.assertIn("read file", answer)
        self.assertIn("permission-disabled tools: git", answer)

    def test_web_answer_reports_tool_state_not_guaranteed_connectivity(self):
        answer = self.knowledge.answer("Can you browse the web?", self.core)
        self.assertIn("registered and enabled", answer)
        self.assertIn("can still fail", answer)

        self.core.access["web"] = False
        answer = self.knowledge.answer("Can you browse the web?", self.core)
        self.assertIn("permission is disabled", answer)

    def test_limitations_answer_does_not_claim_human_consciousness(self):
        answer = self.knowledge.answer("Are you conscious?", self.core)
        self.assertIn("not a human", answer)
        self.assertIn("verify actions", answer)

    def test_context_lists_runtime_evidence_and_limitations(self):
        context = self.knowledge.context(self.core)
        self.assertIn("Configured Ollama model: qwen2.5:3b", context)
        self.assertIn("web_search [web; enabled]", context)
        self.assertIn("Terminal execution is not a complete", context)


if __name__ == "__main__":
    unittest.main()
