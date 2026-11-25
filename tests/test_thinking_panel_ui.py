"""Regression tests for the model Thinking panel UX.

These cover the two symptom families reported on
``feat/product-grade-agent-workspace``:

* the panel *freezing* — the pulsing indicator rebuilt its Qt stylesheet on
  every animation tick (a CSS reparse + repaint several times a second), and
  every streamed token forced a layout-invalidating scroll-to-bottom;
* the panel *not showing* — ``finish()`` collapsed (hid) the body the moment
  the reasoning stream ended, so the summary the user was reading vanished
  before the answer appeared, and a model that produced no reasoning left an
  empty, collapsed chip.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from unittest import mock

from App import NovaWindow, ThinkingPanel


class ThinkingPanelUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_panel(self):
        panel = ThinkingPanel()
        panel.show()
        self.app.processEvents()
        return panel

    def test_finish_keeps_the_reasoning_visible(self):
        """The summary must stay on screen after the thinking stream ends."""
        panel = self._make_panel()
        panel.set_phase("Thinking")
        panel.append_delta("Evaluating the greeting before replying.")
        panel.finish()

        self.assertTrue(panel._body.isVisible(), "reasoning body was hidden after finish")
        self.assertIn("Evaluating the greeting", panel._body.toPlainText())
        self.assertEqual(panel._toggle.text(), "Hide")
        panel.deleteLater()

    def test_finish_with_no_content_leaves_the_body_blank(self):
        """A model that emits no reasoning must not leave a 'no reasoning' chip.

        The panel body stays blank so the caller can retire the empty panel
        instead of showing a confusing 'This model did not provide...' card.
        """
        panel = self._make_panel()
        panel.finish()

        self.assertEqual(panel._body.toPlainText(), "")
        self.assertFalse(panel.has_content)
        panel.deleteLater()

    def test_pulse_does_not_rebuild_the_stylesheet_every_tick(self):
        """The animation must repaint cheaply, not reparse CSS per frame."""
        panel = self._make_panel()
        with mock.patch.object(panel._indicator, "setStyleSheet") as spy:
            for _ in range(12):
                panel._pulse()
        self.assertEqual(spy.call_count, 0, "pulse still reparses CSS on every tick")
        # The dot still animates: phase advances and triggers a cheap repaint.
        self.assertEqual(panel._pulse_phase, 12 % 4)
        panel.deleteLater()

    def test_append_delta_does_not_yank_a_user_who_scrolled_up(self):
        """Streaming must not force-scroll when the reader scrolled up."""
        panel = self._make_panel()
        # Stream enough to make the viewport scrollable.
        panel.append_delta("line\n" * 80)
        bar = panel._body.verticalScrollBar()
        # Reader scrolls up to re-read earlier reasoning.
        bar.setValue(0)
        panel.append_delta(" trailing delta that must not pull the view down")

        self.assertEqual(bar.value(), 0, "view was yanked back to the bottom")
        self.assertIn("trailing delta", panel._body.toPlainText())
        panel.deleteLater()

    def test_append_delta_auto_scrolls_when_already_at_the_bottom(self):
        """When the reader is following along, new tokens stay in view."""
        panel = self._make_panel()
        panel.append_delta("line\n" * 80)
        bar = panel._body.verticalScrollBar()
        bar.setValue(bar.maximum())
        panel.append_delta(" tail")

        self.assertGreaterEqual(bar.value(), bar.maximum() - bar.singleStep())
        panel.deleteLater()


class ThinkingPanelIntegrationTests(unittest.TestCase):
    """Drive the real ``NovaWindow._on_status`` event path end to end."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self):
        class FakeCore:
            def __init__(self):
                self.brain = type("Brain", (), {"model": "fake-local-model"})()
                self.short_memory = type("Mem", (), {"messages": [], "limit": 24, "add": lambda *a, **k: None})()
                self.execution_state = {}
                self.access = {"pc": True, "web": False}
                self.effort = "medium"
                self.cancel_event = None
                self.status_callback = None

            def set_access(self, **a):
                self.access = dict(a)

            def get_access(self):
                return dict(self.access)

            def set_effort(self, v):
                self.effort = v

            def set_thinking_enabled(self, _enabled):
                pass

        class FakeStore:
            def __init__(self):
                self.chats = [{"id": "chat-1", "title": "First"}]

            def list_chats(self):
                return list(self.chats)

            def create_chat(self):
                cid = f"chat-{len(self.chats) + 1}"
                self.chats.append({"id": cid, "title": f"Chat {len(self.chats) + 1}"})
                return cid

            def get_messages(self, _cid):
                return []

        from PySide6.QtGui import QPixmap
        settings = {
            "provider": "local",
            "effort": "medium",
            "remote_models": "[]",
            "assistant_font_size": "18",
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
        return window

    def test_thinking_events_leave_a_visible_summary_panel(self):
        window = self._make_window()
        try:
            window.busy = True
            window.thinking_enabled = True
            window._answer_started = False
            window.thinking_panel = None

            window._on_status("MODEL_THOUGHT_START")
            self.assertIsNotNone(window.thinking_panel)
            window._on_status("MODEL_THOUGHT_DELTA:Planning a concise reply.")
            window._on_status("MODEL_THOUGHT_END")

            panel = window.thinking_panel
            self.assertIsNotNone(panel, "panel was torn down before the answer streamed")
            # The window is never shown under the offscreen platform, so
            # isVisible() is false regardless of intent. Assert the body was
            # not collapsed/hidden by finish() instead.
            self.assertFalse(panel._body.isHidden(), "summary hidden after MODEL_THOUGHT_END")
            self.assertTrue(panel._expanded, "summary collapsed after MODEL_THOUGHT_END")
            self.assertIn("Planning a concise reply", panel._body.toPlainText())
        finally:
            window.close()


    def test_empty_thinking_panel_is_retired_when_the_answer_starts(self):
        """A turn with no reasoning must not leave a 'no reasoning' chip behind."""
        window = self._make_window()
        try:
            window.busy = True
            window.thinking_enabled = True
            window._answer_started = False
            window.thinking_panel = None

            # Think is on, the panel mounts, but the model produces no reasoning.
            window._on_status("MODEL_THOUGHT_START")
            window._on_status("MODEL_THOUGHT_END")
            panel = window.thinking_panel
            self.assertIsNotNone(panel)
            self.assertFalse(panel.has_content)

            # The first answer delta separates the panel from the reply; an
            # empty panel must be removed from the layout, not left as a chip.
            layout = window.chat_container_layout
            self.assertIn(panel, [layout.itemAt(i).widget() for i in range(layout.count())])
            window._separate_thinking_panel_from_reply()
            self.assertIsNone(window.thinking_panel)
            self.assertNotIn(panel, [layout.itemAt(i).widget() for i in range(layout.count())])
        finally:
            window.close()

    def test_thinking_panel_stays_live_during_answer_for_native_thinking(self):
        """Native thinking interleaved with the answer must keep filling the panel.

        Previously the panel was torn down on the first answer delta, so a
        reasoning model's mid-answer thinking phases were dropped and the UI
        froze until content tokens resumed.
        """
        window = self._make_window()
        try:
            window.busy = True
            window.thinking_enabled = True
            window._answer_started = False
            window.thinking_panel = None

            # Thinking starts, the answer begins, then more thinking arrives.
            window._on_status("MODEL_THOUGHT_START")
            window._on_status("MODEL_THOUGHT_DELTA:Considering the greeting.")
            window._on_status("MODEL_ANSWER_DELTA:Hello!")
            panel = window.thinking_panel
            self.assertIsNotNone(panel, "panel was torn down when the answer started")
            self.assertFalse(panel.is_finished(),
                             "panel finished early; later thinking would be dropped")

            # More thinking arrives mid-answer — it must still reach the panel.
            window._on_status("MODEL_THOUGHT_DELTA:Choosing a warm reply.")
            self.assertIn("Choosing a warm reply.", panel._body.toPlainText())
            window._on_status("MODEL_THOUGHT_END")
            self.assertTrue(panel.is_finished())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
