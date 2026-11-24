import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget
from PySide6.QtGui import QPixmap
from PySide6.QtGui import QTextOption
from unittest import mock
import json

from App import AgentWorker, EffortSlider, MarkdownLabel, ModelSettingsDialog, NovaWindow, RemoteModelDiscoveryWorker, TaskPlanWidget


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

    def test_markdown_label_wraps_text_and_reflows_on_resize(self):
        label = MarkdownLabel("<p>A longer sentence that should wrap at normal word boundaries.</p>")
        self.assertEqual(
            label.document().defaultTextOption().wrapMode(),
            QTextOption.WrapAtWordBoundaryOrAnywhere,
        )
        label.resize(320, 100)
        label.update_height()
        wide_height = label.height()
        label.resize(160, 100)
        label.update_height()
        self.assertGreaterEqual(label.height(), wide_height)
        label.deleteLater()

    def test_effort_slider_animation_property_is_registered(self):
        slider = EffortSlider()
        slider.setRange(0, 5)
        slider.setValue(3)
        slider.show()
        self.app.processEvents()
        self.assertGreaterEqual(slider.visualValue, 0.0)
        slider.hide()
        slider.deleteLater()

    def test_agent_tabs_keep_independent_core_and_chat_sessions(self):
        class Memory:
            def __init__(self):
                self.messages = []
                self.limit = 24

        class Brain:
            model = "fake-local-model"

        class FakeCore:
            def __init__(self):
                self.brain = Brain()
                self.short_memory = Memory()
                self.execution_state = {}
                self.access = {"pc": True, "web": False}
                self.effort = "medium"

            def set_access(self, **access):
                self.access = dict(access)

            def get_access(self):
                return dict(self.access)

            def set_effort(self, value):
                self.effort = value

            def set_thinking_enabled(self, _enabled):
                pass

            def ask(self, _message):
                return "ok"

        class FakeStore:
            def __init__(self):
                self.chats = [{"id": "chat-1", "title": "First chat"}]

            def list_chats(self):
                return list(self.chats)

            def create_chat(self):
                chat_id = f"chat-{len(self.chats) + 1}"
                self.chats.append({"id": chat_id, "title": f"Chat {len(self.chats) + 1}"})
                return chat_id

            def get_messages(self, _chat_id):
                return []

        settings = {
            "provider": "local",
            "effort": "medium",
            "remote_models": "[]",
            "assistant_font_size": "16",
        }
        with (
            mock.patch("App.load_settings", return_value=settings),
            mock.patch("App.apply_to_environment"),
            mock.patch("App.NovaCore", FakeCore),
            mock.patch("App.ChatStore", FakeStore),
            mock.patch("App.load_nova_logo", return_value=QPixmap()),
            mock.patch.object(NovaWindow, "_start_model_discovery"),
        ):
            window = NovaWindow()
            first_core = window.core
            first_chat = window.current_chat_id
            self.assertEqual(window.agent_tabs.count(), 1)
            window._new_agent_tab()
            self.assertEqual(window.agent_tabs.count(), 2)
            self.assertIsNot(window.core, first_core)
            second_core = window.core
            second_chat = window.current_chat_id
            self.assertNotEqual(first_chat, second_chat)
            window.agent_tabs.setCurrentIndex(0)
            self.assertIs(window.core, first_core)
            self.assertEqual(window.current_chat_id, first_chat)
            window.agent_tabs.setCurrentIndex(1)
            self.assertIs(window.core, second_core)
            self.assertEqual(window.current_chat_id, second_chat)
            window._close_agent_tab(1)
            self.assertEqual(window.agent_tabs.count(), 1)
            window.close()

    def test_agent_worker_coalesces_stream_deltas_before_qt_delivery(self):
        worker = AgentWorker(object(), "test")
        received = []
        worker.status.connect(received.append)
        worker._last_delta_flush = __import__("time").monotonic()
        for token in ("one", " ", "two", " ", "three"):
            worker._queue_status("MODEL_ANSWER_DELTA:" + token)
        self.assertEqual(received, [])
        worker._flush_deltas()
        self.assertEqual(received, ["MODEL_ANSWER_DELTA:one two three"])

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
