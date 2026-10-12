import unittest

from agent.router import ToolRouter


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


if __name__ == "__main__":
    unittest.main()
