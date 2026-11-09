"""Regression tests for NoviqX identity grounding in NovaCore."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.core import NovaCore


class NoviqXCoreIdentityTests(unittest.TestCase):
    def _core(self, git_enabled=True):
        core = NovaCore.__new__(NovaCore)
        core.brain = SimpleNamespace(model="test-model")
        core.tools = SimpleNamespace(tools={
            "noviqx_github_get_file": {
                "description": "Read remote GitHub files.",
                "capability": "git",
            },
            "noviqx_github_update_file": {
                "description": "Update remote GitHub files.",
                "capability": "git",
            },
        })
        core.access = {"web": True, "git": git_enabled, "pc": True}
        return core

    def _prompt(self, core):
        with patch("agent.capability_probe.describe_model", return_value="Model: test-model."), patch(
            "agent.capability_probe.probe_model_details",
            return_value={"model": "test-model", "parameter_size": None},
        ), patch("agent.core.backend_kind", return_value="local"):
            return core._identity_system_prompt()

    def test_system_prompt_teaches_noviqx_bot_identity_and_safe_usage(self):
        prompt = self._prompt(self._core())

        self.assertIn("NoviqX", prompt)
        self.assertIn("noviqx[bot]", prompt)
        self.assertIn("noviqx_github_get_file", prompt)
        self.assertIn("noviqx_github_update_file", prompt)
        self.assertIn("expected_sha", prompt)
        self.assertIn("separate service identity", prompt)
        self.assertIn("verifier confirms remote content and author identity", prompt)

    def test_system_prompt_does_not_claim_disabled_noviqx_is_usable(self):
        prompt = self._prompt(self._core(git_enabled=False))

        self.assertIn("NoviqX runtime status: permission_disabled", prompt)
        self.assertIn("Do not claim NoviqX operations are currently usable", prompt)


if __name__ == "__main__":
    unittest.main()
