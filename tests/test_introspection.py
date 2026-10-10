import unittest
from types import SimpleNamespace

from agent.introspection import inspect_model, runtime_profile


class RuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        self.core = SimpleNamespace(
            brain=SimpleNamespace(model="qwen2.5:3b"),
            tools=SimpleNamespace(tools={
                "web_search": {"description": "Search web", "capability": "web"},
                "git": {"description": "Git", "capability": "git"},
            }),
            access={"web": True, "git": False, "pc": True},
            execution_state={},
            planner=object(),
            verifier=object(),
            self_knowledge=object(),
        )

    def test_profile_reports_live_components_tools_and_budgets(self):
        profile = runtime_profile(self.core)
        self.assertEqual(profile["configured_model"], "qwen2.5:3b")
        self.assertEqual(profile["registered_tools"], 2)
        self.assertEqual(profile["enabled_tools"], 1)
        self.assertTrue(profile["components"][2]["present"])
        self.assertTrue(profile["components"][3]["present"])
        self.assertEqual(profile["context_budget"], 8192)
        self.assertEqual(profile["output_budget"], 2048)

    def test_model_metadata_uses_returned_parameter_count_not_model_tag(self):
        report = inspect_model(
            self.core,
            show_model=lambda name: {
                "model_info": {
                    "general.architecture": "qwen2",
                    "general.parameter_count": 3_000_000_000,
                    "qwen2.context_length": 32768,
                },
                "details": {
                    "parameter_size": "3.1B",
                    "quantization_level": "Q4_K_M",
                },
                "capabilities": ["completion"],
            },
        )
        self.assertEqual(report["status"], "available")
        self.assertIn("3.00B", report["parameter_count"])
        self.assertEqual(report["architecture"], "qwen2")
        self.assertEqual(report["quantization"], "Q4_K_M")
        self.assertEqual(report["model_context_length"], "32768")
        self.assertEqual(report["capabilities"], ["completion"])

    def test_missing_metadata_remains_unknown(self):
        report = inspect_model(self.core, show_model=lambda name: {"model_info": {}, "details": {}})
        self.assertEqual(report["parameter_count"], "Unknown")
        self.assertEqual(report["architecture"], "Unknown")
        self.assertEqual(report["status"], "available")

    def test_model_probe_failure_does_not_leak_exception_message(self):
        def fail(name):
            raise ConnectionError("sensitive local details")
        report = inspect_model(self.core, show_model=fail)
        self.assertEqual(report["status"], "unreachable")
        self.assertNotIn("sensitive local details", report["detail"])


if __name__ == "__main__":
    unittest.main()
