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

    def test_parameter_question_reports_probed_metadata_or_refuses(self):
        """The answer reflects real metadata, or says it cannot verify it.

        It must never fall back to a hardcoded size, and it must never invent
        one when the runtime gives nothing.
        """
        answer = self.knowledge.answer("How many parameters do you have?", self.core)
        self.assertIsNotNone(answer)
        self.assertIn("qwen2.5:3b", answer)
        # Either real metadata was found, or the answer refuses to guess.
        states = ("reports a size of", "cannot verify", "can't state")
        self.assertTrue(any(s in answer for s in states), answer)
        for invented in ("3 billion parameters", "7 billion", "default bundled"):
            self.assertNotIn(invented, answer)

    def test_parameter_answer_refuses_for_remote_models(self):
        """A remote model's size is not visible, so it must not be stated."""
        core = SimpleNamespace(
            brain=SimpleNamespace(model="nvidia/nemotron-3-ultra-550b-a55b:free"),
            access={"web": True, "git": False, "pc": False},
            tools=SimpleNamespace(tools={}),
        )
        with patch("model.provider.backend_kind", return_value="remote"), \
             patch("model.provider.describe_brain", return_value="remote model"):
            answer = self.knowledge.answer("How many parameters do you have?", core)
        self.assertIn("can't state", answer)
        self.assertIn("not visible", answer)

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
        self.assertIn("Configured model: qwen2.5:3b", context)
        self.assertIn("web_search [web; enabled]", context)
        self.assertIn("Terminal execution is not a complete", context)
        # The backend must be described rather than assumed to be Ollama.
        self.assertIn("Backend:", context)

    def test_backend_is_reported_honestly(self):
        """Regression: the provider was hardcoded to 'Ollama'.

        With a remote API configured, Nova must describe the real backend and
        disclose that content leaves the machine.
        """
        state = self.knowledge.snapshot(self.core)
        self.assertIn("backend_description", state)
        self.assertIn("backend_kind", state)
        limitations = " ".join(state["limitations"])
        self.assertIn("sent to that provider's servers", limitations)

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
            # Natural phrasings put words between "what" and "model"; an earlier
            # pattern required them adjacent, so these fell through to the model
            # and it invented an answer from conversation context.
            "what is the exact name your model?",
            "what is the exact name of your model?",
            "what's the exact model",
            "name of your model",
            "what model do you run",
        ):
            answer = self.knowledge.answer(question, self.core)
            self.assertIsNotNone(answer, question)
            self.assertIn("qwen2.5:3b", answer, question)

    def test_identity_module_holds_only_static_facts(self):
        """Regression: runtime claims were hardcoded as identity constants.

        NOVA_KIND said "runs on the developer's own machine" and
        NOVA_PARAMETER_COUNT said "3 billion", both of which became false under a
        remote provider -- and the model repeated them as fact. Static facts stay
        in identity.py; anything measurable must be probed.
        """
        import agent.identity as identity

        for removed in ("NOVA_KIND", "NOVA_PARAMETER_COUNT",
                        "NOVA_PARAMETER_SOURCE"):
            self.assertFalse(
                hasattr(identity, removed),
                f"{removed} asserts a runtime fact and must be probed instead",
            )

        text = " ".join(identity.identity_lines()) + identity.identity_sentence()
        for claim in ("runs on the developer's own machine", "3 billion",
                      "I run locally", "live Ollama metadata"):
            self.assertNotIn(claim, text, claim)

    def test_model_details_are_probed_not_asserted(self):
        """Runtime facts come from the probe, never from a constant.

        The value may be None (no runtime available) or real metadata; what
        matters is that it is never a hardcoded claim.
        """
        from agent import capability_probe

        details = capability_probe.probe_model_details(self.core)
        for key in ("model", "backend_kind", "backend_description", "location"):
            self.assertIn(key, details)
        self.assertEqual(details["model"], "qwen2.5:3b")
        # Whatever the probe found, it must not be an invented literal.
        self.assertNotIn(details["parameter_size"], ("3 billion", "7 billion"))

    def test_describe_model_never_invents_a_parameter_count(self):
        from agent import capability_probe

        sentence = capability_probe.describe_model(self.core)
        self.assertIn("qwen2.5:3b", sentence)
        for invented in ("3 billion", "7 billion", "parameters, and"):
            self.assertNotIn(invented, sentence)

    def test_location_question_is_answered_from_live_backend(self):
        """Nova must say where it actually runs, and disclose data leaving.

        This is the question the hardcoded claims got wrong: with a remote
        provider configured, 'runs on the developer's own machine' and 'I run
        locally' were both false.
        """
        for question in (
            "are you local or remote?",
            "are you local?",
            "do you run locally?",
            "where do you run?",
            "does anything leave my computer?",
            "is my data sent anywhere?",
        ):
            answer = self.knowledge.answer(question, self.core)
            self.assertIsNotNone(answer, question)
            self.assertIn("this computer", answer, question)

    def test_location_answer_discloses_remote_when_configured(self):
        core = SimpleNamespace(
            brain=SimpleNamespace(model="nvidia/nemotron-3-ultra-550b-a55b:free"),
            access={"web": True, "git": False, "pc": False},
            tools=SimpleNamespace(tools={}),
        )
        with patch("model.provider.backend_kind", return_value="remote"), \
             patch("model.provider.describe_brain", return_value="remote model"):
            answer = self.knowledge.answer("are you local or remote?", core)
        self.assertIn("remote model", answer)
        self.assertIn("sent to that provider", answer)
        self.assertIn("execute locally", answer)


if __name__ == "__main__":
    unittest.main()
