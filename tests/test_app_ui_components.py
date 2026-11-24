import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget
from unittest import mock
import json

from App import ModelSettingsDialog, RemoteModelDiscoveryWorker, TaskPlanWidget


class AppUIComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_model_settings_dialog_has_navigable_categories(self):
        dialog = ModelSettingsDialog(
            {"provider": "local", "remote_models": "[]", "effort": "medium"},
            [],
        )
        tabs = dialog.findChild(QTabWidget, "settingsTabs")
        self.assertIsNotNone(tabs)
        self.assertEqual(
            [tabs.tabText(index) for index in range(tabs.count())],
            ["Models", "Instructions", "Profile", "Appearance"],
        )
        dialog.close()
        dialog.deleteLater()

    def test_remote_model_catalog_is_loaded_without_exposing_api_key(self):
        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({"data": [{"id": "model-z"}, {"id": "model-a"}]}).encode()

        worker = RemoteModelDiscoveryWorker([{
            "id": "profile-1",
            "provider": "openai",
            "base_url": "https://provider.example/v1",
            "api_key": "secret-token",
        }])
        catalogs = []
        worker.catalogs_ready.connect(catalogs.append)
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            worker.run()
        self.assertEqual(catalogs, [{"profile-1": ["model-a", "model-z"]}])
        self.assertNotIn("secret-token", str(urlopen.call_args))

    def test_task_plan_panel_marks_only_completed_steps(self):
        panel = TaskPlanWidget()
        panel.set_plan({
            "steps": [
                {"description": "Read the source", "status": "completed"},
                {"description": "Review the tests", "status": "running"},
                {"description": "Update the implementation", "status": "pending"},
            ]
        })
        self.assertEqual(panel._progress.text(), "1 / 3 completed")
        self.assertEqual(panel._steps.count(), 3)
        panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
