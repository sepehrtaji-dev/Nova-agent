"""Persistence and environment selection tests for personalized model settings."""
import json
import os
import unittest
from unittest import mock

from config.model_settings import apply_to_environment


class ModelProfileSettingsTests(unittest.TestCase):
    def test_selected_remote_profile_is_applied_without_losing_other_profiles(self):
        profiles = [
            {"id": "one", "provider": "openai", "base_url": "https://api.example/v1",
             "model": "model-one", "api_key": "secret-one"},
            {"id": "two", "provider": "anthropic", "base_url": "https://api.anthropic.com",
             "model": "claude-test", "api_key": "secret-two"},
        ]
        settings = {
            "provider": "remote",
            "remote_models": json.dumps(profiles),
            "active_remote_model_id": "two",
            "effort": "high",
            "model_instructions": "Be concise.",
            "profile_name": "Alex",
            "profile_age": "16",
            "profile_occupation": "Student",
        }
        with mock.patch.dict(os.environ, {}, clear=True):
            applied = apply_to_environment(settings)
            self.assertEqual(applied["NOVA_API_PROVIDER"], "anthropic")
            self.assertEqual(os.environ["NOVA_API_MODEL"], "claude-test")
            self.assertEqual(os.environ["NOVA_API_KEY"], "secret-two")
            self.assertEqual(os.environ["NOVA_MODEL_INSTRUCTIONS"], "Be concise.")
            self.assertIn("User name: Alex", os.environ["NOVA_USER_PROFILE"])
            self.assertIn("User age: 16", os.environ["NOVA_USER_PROFILE"])
            self.assertEqual(len(json.loads(settings["remote_models"])), 2)

    def test_switching_to_local_clears_remote_credentials(self):
        with mock.patch.dict(os.environ, {
            "NOVA_API_KEY": "stale-secret",
            "NOVA_API_MODEL": "old-model",
            "NOVA_API_BASE_URL": "https://old.example/v1",
            "NOVA_API_PROVIDER": "anthropic",
        }, clear=True):
            apply_to_environment({"provider": "local", "local_model": "qwen2.5:3b"})
            self.assertNotIn("NOVA_API_KEY", os.environ)
            self.assertNotIn("NOVA_API_PROVIDER", os.environ)
            self.assertEqual(os.environ["NOVA_MODEL"], "qwen2.5:3b")


if __name__ == "__main__":
    unittest.main()
