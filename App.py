import mimetypes
import math
import os
import re
import sys
import threading
from datetime import datetime

from config.runtime import load_capability_definitions, load_default_access
from config.model_settings import (
    apply_to_environment,
    load_settings,
    masked_key,
    save_settings,
    summarise as summarise_backend,
)

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QTimer, Signal, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QAction, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QTextBrowser,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
    QSplitter,
    QToolButton,
)

from agent.core import NovaCore
from utils.math_parser import format_response_math
from storage.chat_store import ChatStore

BG_MAIN = "#0d1117"
BG_PANEL = "#161b22"
BG_INPUT = "#21262d"
BORDER = "#30363d"
TEXT = "#c9d1d9"
TEXT_MUTED = "#8b949e"
ACCENT = "#58a6ff"

EFFORT_LEVELS = ("off", "low", "medium", "high", "max", "novacode")
EFFORT_LABELS = ("Off", "Low", "Medium", "High", "Max", "NovaCode")

DEFAULT_ACCESS = load_default_access()
CAPABILITY_DEFINITIONS = load_capability_definitions()


def format_bytes(size):
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def split_markdown_blocks(text):
    source = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = source.split("\n")
    blocks = []
    prose = []
    i = 0

    def flush_prose():
        if prose:
            blocks.append(("prose", "\n".join(prose), ""))
            prose.clear()

    while i < len(lines):
        match = re.match(r"^\s*(`{3}|~{3})([^\n]*)$", lines[i])
        if not match:
            prose.append(lines[i])
            i += 1
            continue
        flush_prose()
        fence = match.group(1)
        language = match.group(2).strip()
        i += 1
        code_lines = []
        while i < len(lines):
            if re.match(rf"^\s*{re.escape(fence)}\s*$", lines[i]):
                i += 1
                break
            code_lines.append(lines[i])
            i += 1
        blocks.append(("code", "\n".join(code_lines), language))

    flush_prose()
    return blocks


def render_markdown_text(text):
    from ui.markdown_renderer import render_markdown
    return render_markdown(format_response_math(str(text or "")))


def make_avatar(letter="N", size=32):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(BG_INPUT))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.setPen(QColor(TEXT))
    painter.setFont(QFont("Segoe UI", max(10, size // 2), QFont.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, letter)
    painter.end()
    return pixmap


def make_icon(kind, color=TEXT_MUTED, size=20, width=1.8):
    scale = 2
    s = size * scale
    c = s / 2
    pixmap = QPixmap(s, s)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), width * scale)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def line(x1, y1, x2, y2):
        painter.drawLine(QPointF(x1 * s, y1 * s), QPointF(x2 * s, y2 * s))

    if kind == "plus":
        line(0.5, 0.25, 0.5, 0.75)
        line(0.25, 0.5, 0.75, 0.5)
    elif kind == "arrow_up":
        line(0.5, 0.78, 0.5, 0.24)
        line(0.5, 0.24, 0.27, 0.47)
        line(0.5, 0.24, 0.73, 0.47)
    elif kind == "chevron_down":
        line(0.3, 0.4, 0.5, 0.62)
        line(0.5, 0.62, 0.7, 0.4)
    elif kind == "globe":
        r = s * 0.36
        painter.drawEllipse(QPointF(c, c), r, r)
        painter.drawEllipse(QPointF(c, c), r * 0.45, r)
        line(0.5 - 0.36, 0.5, 0.5 + 0.36, 0.5)
    elif kind == "settings":
        r = s * 0.2
        painter.drawEllipse(QPointF(c, c), r, r)
        painter.drawEllipse(QPointF(c, c), r * 2, r * 2)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


class CodeBlock(QFrame):
    def __init__(self, code, language="", parent=None):
        super().__init__(parent)
        self.setObjectName("codeBlock")
        self.setStyleSheet(f"QFrame#codeBlock {{ background: {BG_MAIN}; border: 1px solid {BORDER}; border-radius: 6px; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        if language:
            label = QLabel(language)
            label.setStyleSheet(f"background: {BG_INPUT}; color: {TEXT_MUTED}; border: none; border-bottom: 1px solid {BORDER}; border-top-left-radius: 6px; border-top-right-radius: 6px; padding: 6px 12px; font-size: 11px; font-weight: 600;")
            outer.addWidget(label)

        editor = QPlainTextEdit()
        editor.setStyleSheet(f"QPlainTextEdit {{ background: transparent; color: {TEXT}; border: none; padding: 12px; selection-background-color: {BG_INPUT}; }}")
        editor.setReadOnly(True)
        editor.setPlainText(code)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        font = QFont("Cascadia Mono")
        if font.family() != "Cascadia Mono":
            font = QFont("Consolas")
        font.setPointSize(10)
        editor.setFont(font)

        line_count = max(1, code.count("\n") + 1)
        line_height = max(18, font.pointSize() + 9)
        editor.setFixedHeight(min(480, max(54, line_count * line_height + 22)))
        outer.addWidget(editor)


class MarkdownLabel(QTextBrowser):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; color: #c9d1d9; }")
        self.document().setDocumentMargin(0)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        
        body_style = f"""
        body {{ font-family: 'Segoe UI', sans-serif; font-size: 14px; color: {TEXT}; line-height: 1.5; }}
        h1, h2, h3 {{ color: {TEXT}; margin: 12px 0 6px 0; }}
        h1 {{ font-size: 20px; }} h2 {{ font-size: 18px; }} h3 {{ font-size: 16px; }}
        strong {{ color: #ffffff; }}
        code {{ background: {BG_INPUT}; color: {TEXT}; padding: 2px 5px; border-radius: 4px; font-family: monospace; }}
        a {{ color: #58a6ff; text-decoration: none; }}
        p {{ margin: 6px 0 12px 0; }}
        ul, ol {{ margin: 6px 0 12px 0; padding-left: 20px; }}
        blockquote {{ color: {TEXT_MUTED}; border-left: 3px solid {BORDER}; margin-left: 6px; padding-left: 12px; }}
        table {{ border-collapse: collapse; margin: 10px 0 16px 0; }}
        th, td {{ border: 1px solid {BORDER}; padding: 8px 12px; }}
        th {{ background: {BG_INPUT}; font-weight: 600; }}
        pre {{ background: {BG_INPUT}; padding: 12px; border-radius: 6px; }}
        hr {{ border: none; border-top: 1px solid {BORDER}; margin: 16px 0; }}
        """
        self.document().setDefaultStyleSheet(body_style)
        self.setHtml(text)
        
        self.document().contentsChanged.connect(self.update_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def update_height(self):
        width = max(1, self.viewport().width())
        self.document().setTextWidth(width)
        height = int(self.document().size().height() + 10)
        self.setFixedHeight(max(24, height))

    def wheelEvent(self, event):
        # This browser is sized to its full document height and has no
        # internal scrollbar. Let the enclosing chat QScrollArea handle
        # mouse-wheel input instead of swallowing it here.
        event.ignore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_height()


def add_markdown_content(layout, text):
    for kind, value, language in split_markdown_blocks(text):
        if kind == "code":
            layout.addWidget(CodeBlock(value, language))
            continue
        if not value.strip():
            continue
        
        html = render_markdown_text(value)
        label = MarkdownLabel(html)
        layout.addWidget(label)


class AgentWorker(QObject):
    status = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, core, message):
        super().__init__()
        self.core = core
        self.message = message

    def run(self):
        try:
            self.core.status_callback = self.status.emit
            result = self.core.ask(self.message)
            self.finished.emit(str(result))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class ComposerEdit(QPlainTextEdit):
    submitted = Signal()
    MAX_HEIGHT = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(f"QPlainTextEdit {{ background: transparent; border: none; padding: 4px; font-size: 14px; color: {TEXT}; selection-background-color: {BG_INPUT}; }}")
        self.textChanged.connect(self.fit_height)

    def fit_height(self):
        lines = max(1, int(round(self.document().size().height())))
        margins = int(self.document().documentMargin() * 2)
        wanted = lines * self.fontMetrics().lineSpacing() + margins + 8
        self.setFixedHeight(max(44, min(self.MAX_HEIGHT, wanted)))
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if wanted > self.MAX_HEIGHT else Qt.ScrollBarAlwaysOff
        )

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_height()


class ThinkingPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("thinkingPanel")
        # Using QFrame#thinkingPanel prevents the border from applying to internal labels
        self.setStyleSheet(f"QFrame#thinkingPanel {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}")
        self._started = datetime.now()
        self._finished = False
        self._has_content = False
        self._expanded = True

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self._indicator = QLabel("●")
        self._indicator.setStyleSheet(f"color: {ACCENT}; font-size: 8px; border: none; background: transparent;")
        header.addWidget(self._indicator)

        self._title = QLabel("Thinking")
        self._title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: 600; border: none; background: transparent;")
        header.addWidget(self._title)

        self._clock = QLabel("0s")
        self._clock.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; border: none; background: transparent;")
        header.addWidget(self._clock)
        header.addStretch(1)

        self._toggle = QPushButton("Hide")
        self._toggle.setStyleSheet(f"QPushButton {{ color: {TEXT_MUTED}; background: transparent; border: none; font-size: 11px; }} QPushButton:hover {{ color: {TEXT}; }}")
        self._toggle.setFlat(True)
        self._toggle.setCursor(Qt.PointingHandCursor)
        self._toggle.clicked.connect(self._toggle_body)
        header.addWidget(self._toggle)

        root.addLayout(header)

        self._body = QPlainTextEdit()
        self._body.setStyleSheet(f"QPlainTextEdit {{ background: transparent; color: {TEXT_MUTED}; border: none; font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 12px; }}")
        self._body.setReadOnly(True)
        self._body.setFrameShape(QFrame.NoFrame)
        self._body.setPlaceholderText("Waiting for the model to reason...")
        self._body.setMaximumHeight(200)
        self._body.setMinimumHeight(60)
        root.addWidget(self._body)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        if self._finished:
            return
        seconds = int((datetime.now() - self._started).total_seconds())
        self._clock.setText(f"{seconds}s")

    def _toggle_body(self):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._toggle.setText("Hide" if self._expanded else "Show")

    def append_delta(self, delta):
        if not delta:
            return
        cursor = self._body.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._body.setTextCursor(cursor)
        self._body.insertPlainText(delta)
        bar = self._body.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._has_content = True

    def finish(self):
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        self._tick()
        self._indicator.setText("○")
        self._indicator.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8px; border: none; background: transparent;")
        if not self._has_content:
            self._body.setPlainText("The selected model did not return reasoning for this turn.")
        self._expanded = False
        self._body.setVisible(False)
        self._toggle.setText("Show")


class MessageWidget(QFrame):
    def __init__(self, role, text, attachments=None, parent=None):
        super().__init__(parent)
        self.setObjectName("messageWidget")
        self.setStyleSheet("QFrame#messageWidget { background: transparent; border: none; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 24)
        layout.setSpacing(16)

        avatar = QLabel()
        avatar.setFixedSize(32, 32)
        avatar.setPixmap(make_avatar("Y" if role == "user" else "N", 32))
        avatar.setAlignment(Qt.AlignTop)
        avatar.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(avatar, 0, Qt.AlignTop)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(6)

        name = QLabel("You" if role == "user" else "Nova")
        name.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 600; border: none; background: transparent;")
        content.addWidget(name)

        add_markdown_content(content, text if text else ("Attached files" if attachments else " "))

        if role == "user" and attachments:
            badges = QHBoxLayout()
            badges.setContentsMargins(0, 4, 0, 0)
            badges.setSpacing(8)
            for path in attachments:
                filename = os.path.basename(path)
                try:
                    size_label = format_bytes(os.path.getsize(path))
                except OSError:
                    size_label = "Unavailable"
                badge = QLabel(f"{filename}  ·  {size_label}")
                badge.setStyleSheet(f"color: {TEXT}; background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px; font-size: 11px;")
                badge.setToolTip(path)
                badges.addWidget(badge)
            badges.addStretch(1)
            content.addLayout(badges)

        layout.addLayout(content, 1)


class EffortSlider(QSlider):
    """Horizontal effort slider with a subtle animated halo at maximum effort."""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._phase = 0.0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(35)
        self._pulse_timer.timeout.connect(self._advance_pulse)
        self.valueChanged.connect(self._sync_pulse)
        self._sync_pulse(self.value())

    def _sync_pulse(self, value):
        if value == self.maximum():
            if not self._pulse_timer.isActive():
                self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def _advance_pulse(self):
        self._phase = (self._phase + 0.075) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.value() != self.maximum():
            return

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(
            QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self
        )
        center = handle.center()
        pulse = (math.sin(self._phase) + 1.0) / 2.0
        radius = 13.0 + pulse * 4.0

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QRadialGradient(center, radius)
        gradient.setColorAt(0.0, QColor(168, 85, 247, int(42 + pulse * 34)))
        gradient.setColorAt(0.48, QColor(88, 166, 255, int(24 + pulse * 22)))
        gradient.setColorAt(1.0, QColor(88, 166, 255, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(center, radius, radius)

        # Two tiny orbiting sparks make the max state feel active without
        # changing the slider's geometry or interfering with mouse input.
        for offset, color in ((0.0, QColor(190, 130, 255)), (math.pi, QColor(110, 205, 255))):
            angle = self._phase + offset
            x = center.x() + math.cos(angle) * 11.0
            y = center.y() + math.sin(angle) * 7.0
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, y), 1.5, 1.5)
        painter.end()


class EffortSelector(QWidget):
    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QWidget { background: transparent; border: none; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel("Effort")
        label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; border: none; background: transparent;")
        layout.addWidget(label)

        self._slider = EffortSlider()
        self._slider.setStyleSheet(f"""
            QSlider {{ border: none; background: transparent; }}
            QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: {TEXT_MUTED}; width: 12px; margin: -4px 0; border-radius: 6px; }}
            QSlider::handle:horizontal:hover {{ background: {TEXT}; }}
            QSlider::sub-page:horizontal {{ background: {TEXT_MUTED}; border-radius: 2px; }}
        """)
        self._slider.setRange(0, len(EFFORT_LEVELS) - 1)
        self._slider.setValue(2)
        self._slider.setFixedWidth(100)
        self._slider.valueChanged.connect(self._changed)
        layout.addWidget(self._slider)

        self._value = QLabel(EFFORT_LABELS[2])
        self._value.setMinimumWidth(68)
        self._value.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._value)
        self._set_aura(2)

    def _set_aura(self, index):
        colors = ("#8b949e", "#79c0ff", "#58a6ff", "#a78bfa", "#c084fc", "#f0abfc")
        color = colors[index]
        self._value.setText(EFFORT_LABELS[index])
        self._value.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 700; "
            "border: none; background: transparent;"
        )
        self._slider.setStyleSheet(f"""
            QSlider {{ border: none; background: transparent; }}
            QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: {color}; width: 12px; margin: -4px 0; border-radius: 6px; }}
            QSlider::handle:horizontal:hover {{ background: #ffffff; }}
            QSlider::sub-page:horizontal {{ background: {color}; border-radius: 2px; }}
        """)

    def _changed(self, index):
        self._set_aura(index)
        self.changed.emit(EFFORT_LEVELS[index])

    def value(self):
        return EFFORT_LEVELS[self._slider.value()]

    def set_value(self, name):
        if name in EFFORT_LEVELS:
            index = EFFORT_LEVELS.index(name)
            self._slider.blockSignals(True)
            self._slider.setValue(index)
            self._slider.blockSignals(False)
            self._set_aura(index)

class ModelSettingsDialog(QDialog):
    def __init__(self, settings, installed_models, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Model settings")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet(f"QDialog {{ background-color: {BG_MAIN}; color: {TEXT}; }}")

        self._settings = dict(settings)
        self._installed = list(installed_models or [])
        self._existing_key = str(settings.get("api_key", "") or "")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        heading = QLabel("Choose how Nova reasons")
        heading.setStyleSheet("font-size: 16px; font-weight: 700; border: none; background: transparent;")
        layout.addWidget(heading)

        note = QLabel("Local keeps everything on this computer. Remote sends your messages, file contents, and tool results to the provider you configure.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {TEXT_MUTED}; border: none; background: transparent;")
        layout.addWidget(note)

        self.local_radio = QRadioButton("Local model (Ollama)")
        layout.addWidget(self.local_radio)

        self.local_model = QLineEdit(str(settings.get("local_model", "") or ""))
        self.local_model.setPlaceholderText("e.g. qwen2.5:3b (blank = auto-detect)")
        layout.addWidget(self.local_model)

        if self._installed:
            hint = QLabel("Installed: " + ", ".join(self._installed[:6]))
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; border: none; background: transparent;")
            layout.addWidget(hint)

        self.remote_radio = QRadioButton("Remote API (OpenAI-compatible)")
        layout.addWidget(self.remote_radio)

        self.api_base = QLineEdit(str(settings.get("api_base_url", "") or ""))
        self.api_base.setPlaceholderText("https://api.openai.com/v1")
        layout.addWidget(self._labelled("Base URL", self.api_base))

        self.api_model = QLineEdit(str(settings.get("api_model", "") or ""))
        self.api_model.setPlaceholderText("e.g. gpt-4o-mini, or a gateway model id")
        layout.addWidget(self._labelled("Model", self.api_model))

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        if self._existing_key:
            self.api_key.setPlaceholderText(f"stored: {masked_key(self._existing_key)} — leave blank to keep")
        else:
            self.api_key.setPlaceholderText("API key")
        layout.addWidget(self._labelled("API key", self.api_key))

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; border: none; background: transparent;")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if str(settings.get("provider", "local")).lower() == "remote":
            self.remote_radio.setChecked(True)
        else:
            self.local_radio.setChecked(True)

        for widget in (self.local_radio, self.remote_radio):
            widget.toggled.connect(self._refresh)
        for widget in (self.api_base, self.api_model, self.api_key):
            widget.textChanged.connect(self._refresh)
        self._refresh()

    @staticmethod
    def _labelled(text, widget):
        box = QWidget()
        inner = QVBoxLayout(box)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(4)
        label = QLabel(text)
        label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; border: none; background: transparent;")
        inner.addWidget(label)
        inner.addWidget(widget)
        return box

    def _refresh(self):
        remote = self.remote_radio.isChecked()
        for widget in (self.api_base, self.api_model, self.api_key):
            widget.setEnabled(remote)
        self.local_model.setEnabled(not remote)
        self.status.setText(summarise_backend(self.values()))

    def values(self):
        typed_key = self.api_key.text().strip()
        return {
            "provider": "remote" if self.remote_radio.isChecked() else "local",
            "local_model": self.local_model.text().strip(),
            "api_base_url": self.api_base.text().strip(),
            "api_model": self.api_model.text().strip(),
            "api_key": typed_key or self._existing_key,
        }

    def _on_save(self):
        values = self.values()
        if values["provider"] == "remote":
            if not values["api_model"]:
                self.status.setText("A model name is required for remote mode.")
                return
            if not values["api_key"]:
                self.status.setText("An API key is required for remote mode.")
                return
        self.accept()


class NovaWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self._settings = load_settings()
        self._backend_error = ""
        self._effort = str(self._settings.get("effort") or "medium")
        if self._effort not in EFFORT_LEVELS:
            self._effort = "medium"
        apply_to_environment(self._settings)

        self.core = self._create_core()
        self.core.set_access(**DEFAULT_ACCESS)
        self._apply_effort(self._effort)
        
        self.chat_store = ChatStore()
        saved_chats = self.chat_store.list_chats()
        self.current_chat_id = saved_chats[0]["id"] if saved_chats else self.chat_store.create_chat()
        self._restore_core_memory(self.current_chat_id)
        
        self.thread = None
        self.worker = None
        self.busy = False
        self.thinking_panel = None
        self.attachments = []

        self.setWindowTitle("Nova")
        self.setMinimumSize(900, 600)
        self.resize(1100, 760)
        
        self._build_ui()
        self._apply_theme()
        self._refresh_chat_history()
        self._render_current_chat()

    def _create_core(self):
        try:
            return NovaCore()
        except RuntimeError as exc:
            self._backend_error = str(exc)
            os.environ["NOVA_PROVIDER"] = "local"
            for name in ("NOVA_API_KEY", "NOVA_API_MODEL", "NOVA_API_BASE_URL"):
                os.environ.pop(name, None)
            self._settings["provider"] = "local"
            return NovaCore()

    def _rebuild_core(self):
        access = self.core.get_access() if getattr(self, "core", None) else dict(DEFAULT_ACCESS)
        try:
            new_core = NovaCore()
        except RuntimeError as exc:
            return False
        new_core.set_access(**{**DEFAULT_ACCESS, **access})
        self.core = new_core
        self._apply_effort(self._effort)
        return True

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        main_layout.addWidget(splitter)

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 20, 16, 16)
        sidebar_layout.setSpacing(16)

        title = QLabel("Nova")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT}; border: none; background: transparent;")
        sidebar_layout.addWidget(title)

        new_chat_btn = QPushButton("+ New Chat")
        new_chat_btn.setStyleSheet(f"QPushButton {{ background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 10px; color: {TEXT}; font-weight: 600; text-align: left; }} QPushButton:hover {{ background: {BORDER}; }}")
        new_chat_btn.setCursor(Qt.PointingHandCursor)
        new_chat_btn.clicked.connect(self._new_chat)
        sidebar_layout.addWidget(new_chat_btn)

        label_chats = QLabel("CHATS")
        label_chats.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; font-weight: 700; margin-top: 8px; border: none; background: transparent;")
        sidebar_layout.addWidget(label_chats)

        self.chat_list = QListWidget()
        self.chat_list.setStyleSheet(f"QListWidget {{ background: transparent; border: none; outline: none; }} QListWidget::item {{ color: {TEXT_MUTED}; padding: 8px; border-radius: 6px; margin-bottom: 2px; }} QListWidget::item:hover {{ background: {BG_INPUT}; color: {TEXT}; }} QListWidget::item:selected {{ background: {BG_PANEL}; color: {TEXT}; border: 1px solid {BORDER}; }}")
        self.chat_list.itemClicked.connect(self._on_chat_selected)
        sidebar_layout.addWidget(self.chat_list, 1)

        settings_btn = QPushButton("⚙  Settings")
        settings_btn.setStyleSheet(f"QPushButton {{ background: transparent; border: none; text-align: left; padding: 8px; color: {TEXT_MUTED}; font-size: 13px; }} QPushButton:hover {{ color: {TEXT}; }}")
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.clicked.connect(self._open_model_settings)
        sidebar_layout.addWidget(settings_btn)

        splitter.addWidget(sidebar)

        # Main Content
        main_content = QWidget()
        main_layout = QVBoxLayout(main_content)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(64)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 0, 24, 0)
        
        self.model_selector = QPushButton("Loading...")
        self.model_selector.setStyleSheet(f"QPushButton {{ background: transparent; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 12px; color: {TEXT}; font-size: 13px; }} QPushButton:hover {{ background: {BG_INPUT}; }}")
        self.model_selector.clicked.connect(self._show_model_menu)
        header_layout.addWidget(self.model_selector)

        self.effort_selector = EffortSelector()
        self.effort_selector.set_value(self._effort)
        self.effort_selector.changed.connect(self._on_effort_changed)
        header_layout.addWidget(self.effort_selector)

        header_layout.addStretch()

        self.status_indicator = QLabel("●")
        self.status_indicator.setStyleSheet("color: #3fb950; font-size: 9px; border: none; background: transparent;")
        header_layout.addWidget(self.status_indicator)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; border: none; background: transparent;")
        self.status_label.setMinimumWidth(72)
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_layout.addWidget(self.status_label)

        self._status_phase = 0
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(420)
        self._status_timer.timeout.connect(self._animate_status)

        main_layout.addWidget(header)

        # Chat Area
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.chat_container = QWidget()
        self.chat_container.setStyleSheet(f"background: {BG_MAIN};")
        self.chat_container_layout = QVBoxLayout(self.chat_container)
        self.chat_container_layout.setContentsMargins(40, 24, 40, 24)
        self.chat_container_layout.setSpacing(0)
        self.chat_container_layout.addStretch()
        
        self.chat_scroll.setWidget(self.chat_container)
        main_layout.addWidget(self.chat_scroll, 1)

        # Composer
        composer_area = QFrame()
        composer_area.setObjectName("composerArea")
        composer_area.setStyleSheet(f"QFrame#composerArea {{ background: {BG_MAIN}; border-top: 1px solid {BORDER}; }}")
        composer_layout = QVBoxLayout(composer_area)
        composer_layout.setContentsMargins(40, 16, 40, 24)

        self.composer_box = QFrame()
        self.composer_box.setObjectName("composerBox")
        self.composer_box.setStyleSheet(f"QFrame#composerBox {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}")
        box_layout = QVBoxLayout(self.composer_box)
        box_layout.setContentsMargins(12, 12, 12, 12)
        box_layout.setSpacing(8)

        self.input = ComposerEdit()
        self.input.setPlaceholderText("Send a message...")
        self.input.submitted.connect(self._send)
        box_layout.addWidget(self.input)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)

        add_btn = QPushButton()
        add_btn.setStyleSheet(f"QPushButton {{ background: transparent; border: none; }} QPushButton:hover {{ background: {BG_INPUT}; border-radius: 6px; }}")
        add_btn.setIcon(make_icon("plus", TEXT_MUTED, 18))
        add_btn.setFixedSize(28, 28)
        add_btn.clicked.connect(self._choose_attachments)
        controls.addWidget(add_btn)

        controls.addStretch()

        self.send_button = QPushButton()
        self.send_button.setStyleSheet(f"QPushButton {{ background: {ACCENT}; border: none; border-radius: 6px; }} QPushButton:hover {{ background: #79c0ff; }} QPushButton:disabled {{ background: {BORDER}; }}")
        self.send_button.setIcon(make_icon("arrow_up", BG_MAIN, 16, 2.5))
        self.send_button.setFixedSize(28, 28)
        self.send_button.clicked.connect(self._send)
        controls.addWidget(self.send_button)

        box_layout.addLayout(controls)
        composer_layout.addWidget(self.composer_box)
        main_layout.addWidget(composer_area)

        splitter.addWidget(main_content)
        splitter.setSizes([260, 840])

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background: {BG_MAIN}; }}
            QSplitter::handle {{ background: {BORDER}; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 40px; }}
            QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QMenu {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px; }}
            QMenu::item {{ padding: 8px 24px 8px 12px; border-radius: 4px; color: {TEXT}; font-size: 13px; }}
            QMenu::item:selected {{ background: {BG_INPUT}; }}
        """)

    def _refresh_model_labels(self):
        brain = getattr(self.core, "brain", None)
        model = str(getattr(brain, "model", "") or "model")
        remote = self._settings.get("provider") == "remote"
        provider = "API" if remote else "LOCAL"
        self.model_selector.setText(f"◈  {model}  ·  {provider}")
        provider_name = "Remote API" if remote else "Local Ollama"
        self.model_selector.setToolTip(
            f"Provider: {provider_name}\\nModel: {model}\\n"
            f"Effort: {self._effort.title()}\\n\\n{summarise_backend(self._settings)}"
        )

    def _apply_effort(self, name):
        if name not in EFFORT_LEVELS:
            return
        os.environ["NOVA_EFFORT"] = name
        setter = getattr(self.core, "set_effort", None)
        if callable(setter):
            try:
                setter(name)
            except Exception:
                pass
        for attr in ("effort", "thinking_effort", "reasoning_effort"):
            try:
                setattr(self.core, attr, name)
            except Exception:
                pass

    def _on_effort_changed(self, name):
        self._effort = name
        self._settings["effort"] = name
        self._apply_effort(name)
        save_settings(self._settings)
        self._refresh_model_labels()

    def _animate_status(self):
        if not self.busy:
            self._status_timer.stop()
            return
        self._status_phase = (self._status_phase + 1) % 4
        colors = ("#58a6ff", "#79c0ff", "#a78bfa", "#79c0ff")
        color = colors[self._status_phase]
        self.status_indicator.setStyleSheet(
            f"color: {color}; font-size: 9px; border: none; background: transparent;"
        )

    def _restore_core_memory(self, chat_id):
        messages = self.chat_store.get_messages(chat_id)
        self.core.short_memory.messages = [
            {"role": item["role"], "content": item.get("context") or item["content"]}
            for item in messages
            if item.get("role") in {"user", "assistant"}
        ][-self.core.short_memory.limit:]
        return messages

    def _refresh_chat_history(self):
        self.chat_list.blockSignals(True)
        self.chat_list.clear()
        for chat in self.chat_store.list_chats():
            item = QListWidgetItem(chat["title"])
            item.setData(Qt.UserRole, chat["id"])
            self.chat_list.addItem(item)
            if chat["id"] == self.current_chat_id:
                self.chat_list.setCurrentItem(item)
        self.chat_list.blockSignals(False)
        self._refresh_model_labels()

    def _on_chat_selected(self, item):
        if self.busy:
            return
        chat_id = item.data(Qt.UserRole)
        if not chat_id or chat_id == self.current_chat_id:
            return
        
        access = self.core.get_access()
        apply_to_environment(self._settings)
        self.core = self._create_core()
        self.core.set_access(**access)
        self._apply_effort(self._effort)
        self.current_chat_id = str(chat_id)
        self._refresh_model_labels()
        self._render_current_chat()

    def _new_chat(self):
        if self.busy:
            return
        access = self.core.get_access()
        apply_to_environment(self._settings)
        self.core = self._create_core()
        self.core.set_access(**access)
        self._apply_effort(self._effort)
        self.current_chat_id = self.chat_store.create_chat()
        self.core.short_memory.messages = []
        self._refresh_model_labels()
        self._refresh_chat_history()
        self._render_current_chat()

    def _render_current_chat(self):
        messages = self._restore_core_memory(self.current_chat_id)
        while self.chat_container_layout.count():
            item = self.chat_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        for item in messages:
            widget = MessageWidget(
                item["role"], 
                item["content"], 
                attachments=item.get("attachments") or []
            )
            self.chat_container_layout.addWidget(widget)
            
        self.chat_container_layout.addStretch()
        self._scroll_chat_to_bottom()

    def _add_message(self, role, text, attachments=None):
        stretch = self.chat_container_layout.takeAt(self.chat_container_layout.count() - 1)
        widget = MessageWidget(role, text, attachments=attachments)
        self.chat_container_layout.addWidget(widget)
        if stretch:
            self.chat_container_layout.addItem(stretch)
        self._scroll_chat_to_bottom()

    def _insert_thinking_panel(self):
        stretch = self.chat_container_layout.takeAt(self.chat_container_layout.count() - 1)
        panel = ThinkingPanel()
        self.chat_container_layout.addWidget(panel)
        if stretch:
            self.chat_container_layout.addItem(stretch)
        self._scroll_chat_to_bottom()
        return panel

    def _scroll_chat_to_bottom(self):
        QTimer.singleShot(50, lambda: self.chat_scroll.verticalScrollBar().setValue(self.chat_scroll.verticalScrollBar().maximum()))

    def _show_model_menu(self):
        if self.busy:
            return
        menu = QMenu(self)
        remote = self._settings.get("provider") == "remote"
        
        installed = []
        try:
            import ollama
            data = ollama.list()
            items = data.get("models", []) if isinstance(data, dict) else getattr(data, "models", [])
            for item in items or []:
                name = item.get("model") if isinstance(item, dict) else getattr(item, "model", None)
                if name: installed.append(str(name))
        except Exception:
            pass
            
        current = str(getattr(getattr(self.core, "brain", None), "model", "")).strip()
        if current and current not in installed:
            installed.insert(0, current)

        for name in sorted(set(installed), key=str.lower):
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(not remote and name == current)
            action.triggered.connect(lambda _, n=name: self._select_model(n))

        menu.addSeparator()
        menu.addAction("API and model settings...").triggered.connect(self._open_model_settings)
        menu.exec(self.model_selector.mapToGlobal(QPoint(0, self.model_selector.height())))

    def _select_model(self, name):
        if self.busy or not name:
            return
        if self._settings.get("provider") == "remote":
            self._settings["provider"] = "local"
        self._settings["local_model"] = name
        apply_to_environment(self._settings)
        save_settings(self._settings)
        if self._rebuild_core():
            self._refresh_model_labels()

    def _open_model_settings(self):
        if self.busy:
            return
        dialog = ModelSettingsDialog(self._settings, [], self)
        if dialog.exec() == QDialog.Accepted:
            values = dialog.values()
            save_settings(values)
            self._settings.update(values)
            apply_to_environment(values)
            if self._rebuild_core():
                self._refresh_model_labels()

    def _choose_attachments(self):
        if self.busy:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Attach files", "", "All files (*)")
        for path in paths:
            path = os.path.abspath(path)
            if path not in self.attachments:
                self.attachments.append(path)

    def _attachment_context(self, paths):
        parts = []
        for path in paths:
            name = os.path.basename(path)
            try:
                size = os.path.getsize(path)
                size_text = format_bytes(size)
            except OSError:
                parts.append(f"[Attached File: {name} (unavailable) | path: {path}]")
                continue
            parts.append(f"[Attached File: {name} ({size_text}) | path: {path}]")
        return "\n\n".join(parts)

    def _send(self):
        if self.busy:
            return
        user_text = self.input.toPlainText().strip()
        attachments = list(self.attachments)
        if not user_text and not attachments:
            return

        attachment_context = self._attachment_context(attachments) if attachments else ""
        message = f"{user_text}\n\n{attachment_context}" if attachment_context else user_text

        self.input.clear()
        self.attachments.clear()
        self._add_message("user", user_text, attachments=attachments)
        self.chat_store.add_message(self.current_chat_id, "user", user_text, attachments=attachments, context=message)
        self._refresh_chat_history()

        self.busy = True
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.status_label.setText("Thinking")
        self._status_timer.start()
        self._animate_status()

        self._apply_effort(self._effort)
        self.thinking_panel = None
        if self._effort != "off":
            self.thinking_panel = self._insert_thinking_panel()

        self.worker = AgentWorker(self.core, message)
        self.worker.status.connect(self._on_status)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.thread = threading.Thread(target=self.worker.run, daemon=True)
        self.thread.start()

    def _on_status(self, message):
        message = str(message)
        if message.startswith("MODEL_THOUGHT_DELTA:"):
            if self.thinking_panel:
                self.thinking_panel.append_delta(message[20:])
            return
        if message == "MODEL_THOUGHT_END":
            if self.thinking_panel:
                self.thinking_panel.finish()
            return
        if message.startswith("THINKING_UPDATE:"):
            return

        self.status_label.setText(message[:28])
        self.status_label.setToolTip(message)

    def _on_finished(self, response):
        if self.thinking_panel:
            self.thinking_panel.finish()
            self.thinking_panel = None
        self._add_message("nova", str(response))
        self.chat_store.add_message(self.current_chat_id, "assistant", str(response))
        self._refresh_chat_history()
        self._finish_request()

    def _on_failed(self, error):
        if self.thinking_panel:
            self.thinking_panel.finish()
            self.thinking_panel = None
        text = f"I hit an internal error.\n\nError: {error}"
        self._add_message("nova", text)
        self.chat_store.add_message(self.current_chat_id, "assistant", text)
        self._refresh_chat_history()
        self._finish_request()

    def _finish_request(self):
        self.busy = False
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self._status_timer.stop()
        self.status_indicator.setStyleSheet("color: #3fb950; font-size: 9px; border: none; background: transparent;")
        self.status_label.setText("Ready")
        self.status_label.setToolTip("Nova is ready")
        self.input.setFocus()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    window = NovaWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()