import unittest
from types import SimpleNamespace

from agent.diagnostics import RuntimeDiagnostics


class RuntimeDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.core = SimpleNamespace(
            brain=SimpleNamespace(model="qwen2.5:3b"),
            tools=SimpleNamespace(tools={
                "web_search": {
                    "description": "Search the public web.",
                    "capability": "web",
                },
                "read_file": {
                    "description": "Read a file.",
                    "capability": "pc",
                },
                "git": {
                    "description": "Run Git actions.",
                    "capability": "git",
                },
            }),
            access={"web": True, "git": False, "pc": True},
            execution_state={
                "verified_tools": [
                    {
                        "tool": "read_file",
                        "verification": {
                            "status": "confirmed",
                            "evidence": "File content was observed.",
                            "message": "Read confirmed.",
                        },
                    },
                    {
                        "tool": "web_search",
                        "verification": {
                            "status": "failed",
                            "evidence": "Search request failed.",
                            "message": "Network request failed.",
                        },
                    },
                ],
            },
        )
        self.diagnostics = RuntimeDiagnostics()

    def test_capability_map_distinguishes_verified_failed_untested_and_disabled(self):
        capabilities = {
            item["name"]: item
            for item in self.diagnostics.capability_map(self.core)
        }
        self.assertEqual(capabilities["read_file"]["status"], "verified")
        self.assertEqual(capabilities["web_search"]["status"], "failed")
        self.assertEqual(capabilities["git"]["status"], "disabled")

    def test_model_probe_reports_listed_model_without_claiming_generation(self):
        report = self.diagnostics.snapshot(
            self.core,
            probe_model=True,
            list_models=lambda: {"models": [{"name": "qwen2.5:3b"}]},
        )
        self.assertEqual(report["model"]["status"], "available")
        self.assertIn("generation was not tested", report["model"]["detail"])

    def test_model_probe_reports_missing_model(self):
        report = self.diagnostics.snapshot(
            self.core,
            probe_model=True,
            list_models=lambda: {"models": [{"name": "llama3:8b"}]},
        )
        self.assertEqual(report["model"]["status"], "missing")

    def test_model_probe_handles_ollama_unreachable(self):
        def fail():
            raise ConnectionError("localhost unavailable")

        report = self.diagnostics.snapshot(self.core, probe_model=True, list_models=fail)
        self.assertEqual(report["model"]["status"], "unreachable")
        self.assertIn("ConnectionError", report["model"]["detail"])

    def test_diagnostic_answer_only_triggers_for_explicit_request(self):
        self.assertIsNone(self.diagnostics.answer("hello Nova", self.core, list_models=lambda: {}))
        answer = self.diagnostics.answer(
            "run a self-diagnostic",
            self.core,
            list_models=lambda: {"models": [{"name": "qwen2.5:3b"}]},
        )
        self.assertIn("Nova self-diagnostic report", answer)
        self.assertIn("web_search", answer)
        self.assertIn("generation was not tested", answer)

    def test_persian_diagnostic_request_is_supported(self):
        answer = self.diagnostics.answer(
            "خودت رو بررسی کن",
            self.core,
            list_models=lambda: {"models": [{"name": "qwen2.5:3b"}]},
        )
        self.assertIn("Nova self-diagnostic report", answer)

    def test_context_explains_capability_statuses(self):
        context = self.diagnostics.context(self.core)
        self.assertIn("read_file [pc; verified]", context)
        self.assertIn("web_search [web; failed]", context)
        self.assertIn("verified = latest recorded verifier result confirmed", context)


if __name__ == "__main__":
    unittest.main()
