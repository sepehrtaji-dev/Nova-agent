import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.self_knowledge import SelfKnowledge


def make_core(model="qwen2.5:3b", access=None, tools=None):
    return SimpleNamespace(
        brain=SimpleNamespace(model=model),
        access=access or {"web": True, "git": False, "pc": True},
        tools=SimpleNamespace(tools=tools or {
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


class GroundingTests(unittest.TestCase):
    """The model writes the answer; grounding supplies the facts it needs."""

    def setUp(self):
        self.core = make_core()
        self.knowledge = SelfKnowledge()

    def test_grounding_is_facts_not_a_prepared_answer(self):
        """Grounding must read as evidence, never as a finished reply.

        Nova used to return canned strings for "who are you" and friends. That
        is what this replaces: the model must phrase the answer itself, so the
        grounding is a labelled set of facts rather than a sentence to parrot.
        """
        text = self.knowledge.grounding(self.core)
        self.assertIn("FACTS ABOUT YOU", text)
        self.assertIn("developed by", text)
        self.assertIn("Answer in your own words", text)
        # It must not open as an answer to "who are you?".
        self.assertFalse(text.startswith("I'm Nova"))

    def test_grounding_carries_identity_facts(self):
        text = self.knowledge.grounding(self.core)
        from agent.identity import NOVA_DEVELOPER, NOVA_NAME, NOVA_VERSION

        self.assertIn(NOVA_NAME, text)
        self.assertIn(NOVA_VERSION, text)
        self.assertIn(NOVA_DEVELOPER, text)

    def test_grounding_names_the_model_actually_serving(self):
        text = self.knowledge.grounding(self.core)
        self.assertIn("qwen2.5:3b", text)

    def test_grounding_lists_only_enabled_tools(self):
        text = self.knowledge.grounding(self.core)
        self.assertIn("web_search", text)
        self.assertIn("read_file", text)
        # git is registered but its capability is off.
        self.assertNotIn("Tools currently enabled for you: git", text)

    def test_grounding_states_when_no_tools_are_enabled(self):
        core = make_core(access={"web": False, "git": False, "pc": False})
        text = self.knowledge.grounding(core)
        self.assertIn("No tools are enabled", text)

    def test_grounding_forbids_foreign_vendor_authorship(self):
        text = self.knowledge.grounding(self.core)
        self.assertIn("not a product of Anthropic", text)

    def test_grounding_refuses_to_state_unknown_parameter_count(self):
        """A remote model's size is invisible, so the fact must say so."""
        core = make_core(model="nvidia/nemotron-3-ultra-550b-a55b:free")
        with patch("model.provider.backend_kind", return_value="remote"), \
             patch("model.provider.describe_brain", return_value="remote model"):
            text = self.knowledge.grounding(core)
        self.assertIn("not visible to you", text)
        self.assertNotIn("3 billion", text)

    def test_grounding_reports_remote_location_and_disclosure(self):
        core = make_core(model="openai/gpt-4o-mini")
        with patch("model.provider.backend_kind", return_value="remote"), \
             patch("model.provider.describe_brain",
                   return_value="remote model via provider (prompts are sent)"):
            text = self.knowledge.grounding(core)
        self.assertIn("provider's servers", text)
        self.assertIn("openai/gpt-4o-mini", text)


class VendorGuardTests(unittest.TestCase):
    """The only deterministic check left: never claim a foreign creator."""

    def setUp(self):
        self.knowledge = SelfKnowledge()
        self.core = make_core()

    def test_claim_of_foreign_authorship_is_corrected(self):
        for text in (
            "I was designed by Anthropic to be helpful.",
            "I am a language model created by OpenAI.",
            "This assistant was developed by Google.",
            "I'm Claude, made by Anthropic.",
        ):
            corrected = self.knowledge.review("who made you?", text, self.core)
            self.assertNotEqual(corrected, text, text)
            self.assertIn("developed by", corrected, text)
            self.assertNotIn("I was designed by Anthropic", corrected)

    def test_correction_names_the_real_developer(self):
        from agent.identity import NOVA_DEVELOPER

        corrected = self.knowledge.review(
            "who made you?", "I was created by Anthropic.", self.core)
        self.assertIn(NOVA_DEVELOPER, corrected)

    def test_correct_answer_is_left_untouched(self):
        """The guard must not rewrite answers that are already right."""
        for text in (
            "I'm Nova 1.3, developed by Taji-Soft team.",
            "No, I was not made by Anthropic. I am Nova.",
            "I'm not a product of OpenAI; I'm Nova, built by Taji-Soft.",
            "I can search the web and run code.",
            "Anthropic makes Claude, which is unrelated to me.",
            "Google's Gemini is a different product entirely.",
            # Regression: "Ollama" contains "llama"; a substring match rewrote
            # this correct answer.
            "I run on qwen2.5:3b via Ollama, and I was built by Taji-Soft.",
            "I'm Nova; my weights come from a Qwen model, trained by Alibaba.",
            "My creator is Taji-Soft, not any of the large AI labs.",
            "The underlying weights were trained elsewhere; the agent is Nova.",
        ):
            self.assertEqual(
                self.knowledge.review("who are you?", text, self.core), text, text)

    def test_ollama_is_not_mistaken_for_llama(self):
        """Word-boundary regression: 'Ollama' must never trip the vendor guard."""
        text = "I run locally on qwen2.5:3b through Ollama."
        self.assertIsNone(
            self.knowledge._mentions_foreign_vendor_claim(text))

    def test_fabricated_authorship_is_not_missed(self):
        for text in (
            "I was designed by Anthropic.",
            "I am a language model created by OpenAI.",
            "I'm Claude, made by Anthropic.",
            "This assistant was developed by Google DeepMind.",
            "I was built by Meta AI.",
            "I am ChatGPT, developed by OpenAI.",
        ):
            self.assertIsNotNone(
                self.knowledge._mentions_foreign_vendor_claim(text), text)

    def test_guard_ignores_empty_or_non_string(self):
        for value in ("", "   ", None, 42):
            self.assertEqual(
                self.knowledge.review("hi", value, self.core), value)


class NeedsGroundingTests(unittest.TestCase):
    def setUp(self):
        self.knowledge = SelfKnowledge()

    def test_self_description_questions_are_recognised(self):
        for question in (
            "who are you?",
            "what are you?",
            "who developed you?",
            "what can you do?",
            "what model are you?",
            "introduce yourself",
            "tell me about yourself",
            "are you local or remote?",
            "what tools do you have?",
            "what is your name?",
        ):
            self.assertTrue(self.knowledge.needs_grounding(question), question)

    def test_ordinary_questions_are_not_flagged(self):
        for question in (
            "what is 15 percent of 240?",
            "write a python function",
            "what's the weather in Tokyo?",
            "explain recursion",
        ):
            self.assertFalse(self.knowledge.needs_grounding(question), question)

    def test_empty_input_is_not_flagged(self):
        for value in ("", "   ", None):
            self.assertFalse(self.knowledge.needs_grounding(value))


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.knowledge = SelfKnowledge()
        self.core = make_core()

    def test_context_lists_runtime_evidence(self):
        context = self.knowledge.context(self.core)
        self.assertIn("qwen2.5:3b", context)
        self.assertIn("web_search [web; enabled]", context)
        self.assertIn("Backend:", context)

    def test_snapshot_reports_backend_honestly(self):
        state = self.knowledge.snapshot(self.core)
        self.assertIn("backend_description", state)
        self.assertIn("backend_kind", state)
        limitations = " ".join(state["limitations"])
        self.assertIn("sent to that provider's servers", limitations)

    def test_snapshot_has_no_hardcoded_runtime_claims(self):
        state = self.knowledge.snapshot(self.core)
        self.assertNotIn("kind", state)
        self.assertNotIn("default_parameters", state)


class StaticIdentityTests(unittest.TestCase):
    def test_identity_module_holds_only_static_facts(self):
        """Runtime claims must never be hardcoded as identity constants."""
        import agent.identity as identity

        for removed in ("NOVA_KIND", "NOVA_PARAMETER_COUNT",
                        "NOVA_PARAMETER_SOURCE"):
            self.assertFalse(hasattr(identity, removed), removed)

        text = " ".join(identity.identity_lines()) + identity.identity_sentence()
        for claim in ("runs on the developer's own machine", "3 billion",
                      "I run locally", "live Ollama metadata"):
            self.assertNotIn(claim, text, claim)

    def test_no_canned_answer_dispatcher_remains(self):
        """The prepared-answer entry point must be gone."""
        self.assertFalse(hasattr(SelfKnowledge, "answer"))
        for method in ("grounding", "review", "needs_grounding", "context"):
            self.assertTrue(hasattr(SelfKnowledge, method), method)


if __name__ == "__main__":
    unittest.main()
