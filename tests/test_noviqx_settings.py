"""Tests for the NoviqX settings layer.

These verify the persistence + permission + lookup behavior of the
credential store, without ever writing a real .pem. The .pem path is
stored; the .pem content is never touched by this module.
"""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integrations.noviqx import settings as noviqx_settings
from integrations.noviqx.settings import (
    is_configured,
    load_settings,
    masked_display,
    save_settings,
    should_show_wizard,
)


class NoviqXSettingsTests(unittest.TestCase):
    def setUp(self):
        # Each test gets an isolated NOVA_HOME so we never touch the user's real
        # ~/.nova directory.
        self._home = tempfile.mkdtemp(prefix="nova-noviqx-")
        self._env = patch.dict(os.environ, {"NOVA_HOME": self._home}, clear=False)
        self._env.start()
        # Clear NOVIQX_* env vars so they don't leak into the resolution chain.
        for var in ("NOVIQX_APP_ID", "NOVIQX_INSTALLATION_ID", "NOVIQX_PRIVATE_KEY_PATH"):
            os.environ.pop(var, None)

    def tearDown(self):
        self._env.stop()

    def _write_pem(self) -> Path:
        path = Path(self._home) / "noviqx-test.pem"
        # A throwaway, invalid-as-RSA marker file. We never authenticate with it.
        path.write_text("-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n")
        return path

    def test_empty_home_means_unconfigured(self):
        s = load_settings()
        self.assertFalse(s["setup_dismissed"])
        self.assertFalse(s["setup_completed"])
        self.assertFalse(is_configured(s))
        self.assertTrue(should_show_wizard(s))  # not dismissed + not configured

    def test_save_then_load_round_trip(self):
        pem = self._write_pem()
        ok, _ = save_settings({
            "app_id": "123456",
            "installation_id": "7890",
            "private_key_path": str(pem),
        })
        self.assertTrue(ok)
        reloaded = load_settings()
        self.assertEqual(reloaded["app_id"], "123456")
        self.assertEqual(reloaded["installation_id"], "7890")
        self.assertEqual(reloaded["private_key_path"], str(pem))

    def test_is_configured_requires_all_three_fields_and_existing_pem(self):
        pem = self._write_pem()
        # Missing app_id
        save_settings({"installation_id": "7890", "private_key_path": str(pem)})
        self.assertFalse(is_configured())
        # Now complete
        save_settings({"app_id": "123456"})
        self.assertTrue(is_configured())
        # Pointing at a non-existent path counts as unconfigured
        save_settings({"private_key_path": str(Path(self._home) / "missing.pem")})
        self.assertFalse(is_configured())

    def test_app_id_must_be_numeric(self):
        pem = self._write_pem()
        save_settings({"app_id": "not-numeric", "installation_id": "1", "private_key_path": str(pem)})
        self.assertFalse(is_configured())

    def test_dismissed_flag_suppresses_wizard(self):
        save_settings({"setup_dismissed": True})
        self.assertFalse(should_show_wizard())
        # Even if the user is fully configured, dismissed wins: they explicitly
        # opted out, so we don't nag them. (They can re-open via Settings menu.)

    def test_completed_flag_does_not_suppress_wizard_on_misconfig(self):
        # setup_completed is set after a successful wizard run, but if the .pem
        # later disappears, we want the wizard back. So is_configured is the
        # source of truth, not setup_completed.
        save_settings({"setup_completed": True, "app_id": "1", "installation_id": "2",
                       "private_key_path": str(Path(self._home) / "gone.pem")})
        self.assertTrue(should_show_wizard())

    def test_unknown_keys_are_dropped_on_save(self):
        # Critical: this layer must NEVER accidentally persist secret material
        # someone passes via the public API. Only known keys are written.
        ok, _ = save_settings({
            "app_id": "123456",
            "pem_content": "-----BEGIN PRIVATE KEY-----\nSHOULD NEVER BE STORED\n-----END PRIVATE KEY-----",
            "private_key_content": "should also be dropped",
        })
        self.assertTrue(ok)
        path = noviqx_settings.settings_path()
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn("SHOULD NEVER BE STORED", raw)
        self.assertNotIn("should also be dropped", raw)
        self.assertNotIn("pem_content", raw)

    def test_settings_file_permissions_are_owner_only(self):
        save_settings({"app_id": "1"})
        path = noviqx_settings.settings_path()
        mode = stat.S_IMODE(path.stat().st_mode)
        # Owner can read+write; group and others must have nothing.
        self.assertEqual(mode, stat.S_IRUSR | stat.S_IWUSR)

    def test_masked_display_does_not_leak_full_pem_path(self):
        pem = self._write_pem()
        save_settings({"app_id": "123456", "installation_id": "7890",
                       "private_key_path": str(pem)})
        display = masked_display()
        # The basename is fine to show (it's just "noviqx-test.pem"); the
        # absolute directory path must NOT appear in the display.
        self.assertIn("noviqx-test.pem", display["private_key_path"])
        self.assertNotIn(str(self._home), display["private_key_path"])
        self.assertEqual(display["app_id"], "123456")
        self.assertEqual(display["installation_id"], "7890")


class GitHubAppAuthFallbackTests(unittest.TestCase):
    """Verify the env-var → settings-file resolution chain on GitHubAppAuth."""

    def setUp(self):
        self._home = tempfile.mkdtemp(prefix="nova-noviqx-auth-")
        self._env = patch.dict(os.environ, {"NOVA_HOME": self._home}, clear=False)
        self._env.start()
        for var in ("NOVIQX_APP_ID", "NOVIQX_INSTALLATION_ID", "NOVIQX_PRIVATE_KEY_PATH"):
            os.environ.pop(var, None)

    def tearDown(self):
        self._env.stop()

    def test_settings_file_is_used_when_env_unset(self):
        from integrations.noviqx.auth import GitHubAppAuth
        save_settings({"app_id": "111", "installation_id": "222",
                       "private_key_path": "/tmp/whatever.pem"})
        auth = GitHubAppAuth()
        self.assertEqual(auth.app_id, "111")
        self.assertEqual(auth.installation_id, "222")
        self.assertEqual(str(auth.private_key_path), "/tmp/whatever.pem")

    def test_env_overrides_settings_file(self):
        from integrations.noviqx.auth import GitHubAppAuth
        save_settings({"app_id": "from-file"})
        with patch.dict(os.environ, {"NOVIQX_APP_ID": "from-env"}, clear=False):
            auth = GitHubAppAuth()
        self.assertEqual(auth.app_id, "from-env")

    def test_explicit_args_override_everything(self):
        from integrations.noviqx.auth import GitHubAppAuth
        save_settings({"app_id": "from-file"})
        with patch.dict(os.environ, {"NOVIQX_APP_ID": "from-env"}, clear=False):
            auth = GitHubAppAuth(app_id="from-ctor")
        self.assertEqual(auth.app_id, "from-ctor")


if __name__ == "__main__":
    unittest.main()
