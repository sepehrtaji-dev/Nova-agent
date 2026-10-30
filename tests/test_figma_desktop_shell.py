"""Offscreen integration checks for the Figma desktop shell."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication, QFrame, QMainWindow, QPlainTextEdit, QPushButton, QWidget

from ui.figma_desktop import FigmaDesktopShell


class FakeOwner(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings = {"provider": "local"}
        self.current_model = "qwen2.5:3b"
        self.core = object()
        self.activity_messages = []
        self.input = QPlainTextEdit()
        self.status_label = None
        self.model_selector = QPushButton()

    def _build_composer(self):
        return QWidget()

    def _build_activity_panel(self):
        self.capability_buttons = {}
        return QFrame()

    def _installed_models(self):
        return [self.current_model, "qwen3:8b"]

    def _on_chat_range_changed(self, *_):
        pass

    def _on_chat_scrolled(self, *_):
        pass

    def _new_chat(self):
        pass

    def _open_model_settings(self):
        pass

    def _select_model(self, model):
        self.current_model = model

    def _add_activity(self, message):
        self.activity_messages.append(message)


class FigmaDesktopShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_three_pages_and_fixed_sidebar(self):
        owner = FakeOwner()
        shell = FigmaDesktopShell(owner)
        shell.build()
        owner.resize(1280, 832)
        owner.show()
        self.app.processEvents()

        self.assertEqual(shell.stack.count(), 3)
        self.assertEqual(shell.sidebar.width(), 280)
        shell.navigate("settings")
        self.assertEqual(shell.stack.currentIndex(), 1)
        shell.navigate("workspace")
        self.assertEqual(shell.stack.currentIndex(), 2)
        shell.navigate("chat")
        self.assertEqual(shell.stack.currentIndex(), 0)
        owner.close()

    def test_workspace_activity_counters_are_session_scoped(self):
        owner = FakeOwner()
        shell = FigmaDesktopShell(owner)
        shell.build()
        shell.record_activity("Read file planner.py")
        shell.record_activity("Wrote file report.md")
        shell.record_activity("Executed command: pytest")

        self.assertEqual(shell.workspace_stats["Files read"].text(), "1")
        self.assertEqual(shell.workspace_stats["Files changed"].text(), "1")
        self.assertEqual(shell.workspace_stats["Commands run"].text(), "1")
        owner.close()


if __name__ == "__main__":
    unittest.main()
