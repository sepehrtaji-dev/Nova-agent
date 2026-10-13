import unittest

from agent.router import ToolRouter
from tools.registry import ToolRegistry


class DummyBrain:
    def generate(self, *_args, **_kwargs):
        return "{}"


class RegistryDrivenToolRoutingTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(
            "lookup",
            "Search for a resource using a query string.",
            lambda value: value,
            capability="web",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
        )
        self.router = ToolRouter(DummyBrain(), self.registry)

    def test_parses_unquoted_plain_text_for_any_registered_tool(self):
        decision = self.router._extract_function_call(
            "lookup(Pizza Shops In United States)"
        )

        self.assertEqual(decision["tool"], "lookup")
        self.assertEqual(
            decision["input"],
            '{"query": "Pizza Shops In United States"}',
        )

    def test_parses_python_like_keyword_arguments_without_tool_specific_rules(self):
        decision = self.router._extract_function_call(
            'lookup(query="pizza shops", region="US")'
        )

        self.assertEqual(decision["tool"], "lookup")
        self.assertEqual(
            decision["input"],
            '{"query": "pizza shops", "region": "US"}',
        )

    def test_validates_registered_tool_with_plain_string_input(self):
        decision = self.router._validate_tool_decision(
            {
                "action": "tool",
                "task_type": "computer",
                "tool": "lookup",
                "input": "Pizza Shops In United States",
            },
            "computer",
        )

        self.assertIsNotNone(decision)
        self.assertEqual(
            decision["input"],
            '{"query": "Pizza Shops In United States"}',
        )

    def test_rejects_unregistered_function_call(self):
        self.assertIsNone(
            self.router._extract_function_call("not_registered(query='test')")
        )


if __name__ == "__main__":
    unittest.main()
