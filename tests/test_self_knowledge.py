import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_parameter_question_uses_ollama_metadata_and_does_not_guess(self):
        from unittest.mock import patch

        metadata = {
            "status": "available",
            "configured_name": "qwen2.5:3b",
            "parameter_count": "3.00B (3,000,000,000)",
            "parameter_size": "3.1B",
            "architecture": "qwen2",
            "quantization": "Q4_K_M",
            "detail": "Ollama metadata available.",
        }
        with patch("agent.self_knowledge.inspect_model", return_value=metadata):
            answer = self.knowledge.answer("How many parameters do you have?", self.core)
        self.assertIn("3.00B", answer)
        self.assertIn("not a count of parameters in Nova's Python agent code", answer)

        unavailable = dict(metadata, status="unreachable", detail="Ollama is unreachable.")
        with patch("agent.self_knowledge.inspect_model", return_value=unavailable):
            answer = self.knowledge.answer("مدلت چند پارامتر داره", self.core)
        self.assertIn("will not guess", answer)

    def test_tool_answer_distinguishes_enabled_and_disabled(self):
        answer = self.knowledge.answer("What tools do you have?", self.core)
        self.assertIn("web_search", answer)
        self.assertIn("read_file", answer)
        self.assertIn("Permission-disabled tools: git", answer)
        # Capability claims must come from live probes, not configuration.
        self.assertIn("live probe results", answer)

    def test_web_answer_probes_reachability_not_registration(self):
        """Regression: the answer used to recite 'registered and enabled'.

        That is a configuration flag, not evidence the capability works. The
        answer must reflect an actual reachability probe.
        """
        with patch.object(self.knowledge, "_web_probe",
                          return_value={"reachable": True, "status": "reachable",
                                        "detail": "HTTP 200 from https://example.com/"}):
            answer = self.knowledge.answer("Can you search the web?", self.core)
        self.assertIn("HTTP 200", answer)
        self.assertNotIn("registered and enabled.", answer)

    def test_web_answer_reports_unreachable_network(self):
        with patch.object(self.knowledge, "_web_probe",
                          return_value={"reachable": False, "status": "unreachable",
                                        "detail": "timed out"}):
            answer = self.knowledge.answer("Can you search the web?", self.core)
        self.assertIn("could not reach the network", answer)
        self.assertIn("timed out", answer)
        self.assertIn("will not claim a search worked", answer)

    def test_web_answer_respects_disabled_permission(self):
        self.core.access["web"] = False
        answer = self.knowledge.answer("Can you browse the web?", self.core)
        self.assertIn("turned", answer)
        self.assertIn("off by permission", answer)

    def test_web_answer_handles_missing_tool(self):
        self.core.tools.tools.pop("web_search")
        answer = self.knowledge.answer("Can you search the web?", self.core)
        self.assertIn("not", answer.lower())
        self.assertIn("registered in this build", answer)

    def test_limitations_answer_does_not_claim_human_consciousness(self):
        answer = self.knowledge.answer("Are you conscious?", self.core)
        self.assertIn("not a human", answer)
        self.assertIn("verify actions", answer)

    def test_context_lists_runtime_evidence_and_limitations(self):
        context = self.knowledge.context(self.core)
        self.assertIn("Configured Ollama model: qwen2.5:3b", context)
        self.assertIn("web_search [web; enabled]", context)
        self.assertIn("Terminal execution is not a complete", context)

    def test_identity_questions_are_grounded_in_developer(self):
        """Regression: the base model claimed to be made by Anthropic.

        Identity is runtime configuration, so these must be answered from the
        snapshot rather than left to the model's own training data.
        """
        for question in (
            "who developed you?",
            "who made you?",
            "who created you?",
            "what company created you?",
            "are you made by anthropic?",
            "who built nova?",
            "what are you?",
        ):
            answer = self.knowledge.answer(question, self.core)
            self.assertIsNotNone(answer, f"not matched: {question}")
            self.assertIn("Taji-Soft", answer, question)
            self.assertIn("not a product of Anthropic", answer, question)

    def test_identity_answer_denies_other_vendors(self):
        answer = self.knowledge.answer("who made you?", self.core)
        for vendor in ("Anthropic", "OpenAI", "Google", "Meta"):
            self.assertIn(vendor, answer)

    def test_model_question_variants_are_matched(self):
        for question in (
            "what model are you?",
            "which model are you using?",
            "what llm is this?",
        ):
            answer = self.knowledge.answer(question, self.core)
            self.assertIsNotNone(answer, question)
            self.assertIn("qwen2.5:3b", answer)


if __name__ == "__main__":
    unittest.main()
