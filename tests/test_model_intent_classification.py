import unittest

from agent.router import ToolRouter
from tools.registry import ToolRegistry


class FakeBrain:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if self.responses:
            return self.responses.pop(0)
        return ""


class IntentClassificationTests(unittest.TestCase):
    def make_router(self, responses):
        return ToolRouter(FakeBrain(responses), tools=object())

    def test_classifier_asks_model_even_for_keyword_like_message(self):
        router = self.make_router(['{"task_type":"conversation"}'])
        result = router.classify_task("How do I open an app?")
        self.assertEqual(result, "conversation")
        self.assertEqual(len(router.brain.prompts), 1)

    def test_classifier_uses_model_result_for_direct_action_request(self):
        router = self.make_router(['{"task_type":"computer"}'])
        result = router.classify_task("Please open Firefox.")
        self.assertEqual(result, "computer")
        self.assertEqual(len(router.brain.prompts), 1)

    def test_invalid_model_output_retries_once_then_fails_closed(self):
        router = self.make_router(["not-json", "still-not-json"])
        result = router.classify_task("Maybe open an app?")
        self.assertEqual(result, "conversation")
        self.assertEqual(len(router.brain.prompts), 2)

    def test_empty_message_does_not_call_model(self):
        router = self.make_router(['{"task_type":"computer"}'])
        self.assertEqual(router.classify_task("  "), "conversation")
        self.assertEqual(router.brain.prompts, [])

    def test_off_schema_synonyms_are_accepted(self):
        """The model answers with natural wording, not just the two literals.

        Regression: "conversational" and "informational" used to normalize to
        None, so the router fell through to conversation and never used a tool.
        """
        for value, expected in (
            ("conversational", "conversation"),
            ("informational", "conversation"),
            ("informative", "conversation"),
            ("no_action", "conversation"),
            ("chat", "conversation"),
        ):
            router = self.make_router(['{"task_type":"%s"}' % value])
            self.assertEqual(
                router.classify_task("what is the latest Python version?"),
                expected,
                f"{value!r} should normalize to {expected!r}",
            )

    def test_tool_name_as_task_type_is_an_action(self):
        """A classifier that names the tool clearly wants that tool to run."""
        for value in ("web_search", "search", "web", "browse"):
            router = self.make_router(['{"task_type":"%s"}' % value])
            self.assertEqual(
                router.classify_task("what is the latest Python version?"),
                "computer",
                f"{value!r} should be treated as a tool request",
            )

    def test_action_synonyms_are_accepted(self):
        for value in ("computer", "action", "execution", "tool_call", "agent"):
            router = self.make_router(['{"task_type":"%s"}' % value])
            self.assertEqual(router.classify_task("open firefox"), "computer")

    def test_unknown_value_still_fails_closed(self):
        """Unrecognized wording must not be guessed into an action."""
        router = self.make_router(
            ['{"task_type":"compute"}', '{"task_type":"compute"}']
        )
        self.assertEqual(
            router.classify_task("what is 15 percent of 240?"), "conversation"
        )

    def test_classifier_prompt_mentions_undated_current_info(self):
        """The prompt must tell the model that current questions need a tool."""
        router = self.make_router(['{"task_type":"computer"}'])
        router.classify_task("what is the latest Python version?")
        # Prompts are line-wrapped, so compare whitespace-normalized text.
        prompt = " ".join(router.brain.prompts[0].lower().split())
        self.assertIn("current", prompt)
        self.assertIn("training cutoff", prompt)

    def test_classifier_prompt_covers_bare_topic_and_arithmetic(self):
        """Guards the rules that fixed bare-topic and explanation routing."""
        router = self.make_router(['{"task_type":"computer"}'])
        router.classify_task("best minecraft shaders 2026")
        prompt = " ".join(router.brain.prompts[0].lower().split())
        self.assertIn("bare topic", prompt)
        self.assertIn("arithmetic", prompt)
        self.assertIn("worked examples", prompt)

    def test_web_search_name_is_a_tool_when_registered(self):
        """A registered tool name normalizes to computer even if unlisted."""
        registry = ToolRegistry()
        registry.register(
            name="web_search",
            description="Search the public web.",
            function=lambda payload: "stub",
            capability="web",
        )
        router = ToolRouter(FakeBrain(['{"task_type":"web_search"}']), tools=registry)
        self.assertEqual(router.classify_task("latest news?"), "computer")


if __name__ == "__main__":
    unittest.main()
