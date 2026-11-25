import json
import math
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime

from config.runtime import load_capability_definitions, load_default_access
from config.model_settings import (
    apply_to_environment,
    load_settings,
    masked_key,
    save_settings,
    summarise as summarise_backend,
)

from integrations.noviqx.settings import (
    is_configured as noviqx_is_configured,
    load_settings as load_noviqx_settings,
    masked_display as noviqx_masked_display,
    save_settings as save_noviqx_settings,
)

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QTimer, Signal, QSize, QThread, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPainterPath, QRadialGradient, QTextOption
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
    QMessageBox,
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
    QWidgetAction,
    QTabBar,
    QTabWidget,
)

from agent.core import NovaCore
from agent.cancellation import GenerationCancelled
from utils.math_parser import format_response_math
from storage.chat_store import ChatStore

BG_MAIN = "#0b0f14"
BG_PANEL = "#111821"
BG_INPUT = "#17212c"
BORDER = "#263342"
TEXT = "#e6edf3"
TEXT_MUTED = "#9aa9b8"
ACCENT = "#82aaff"

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


def nova_logo_path():
    """Return the optional Nova brand asset path."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "nova-logo.png")


def load_nova_logo(size):
    """Load and smoothly scale the user-provided Nova logo asset."""
    path = nova_logo_path()
    if not os.path.isfile(path):
        return QPixmap()
    source = QPixmap(path)
    if source.isNull():
        return QPixmap()
    return source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def make_avatar(letter="N", size=32):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(BG_INPUT))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)
    if letter == "N":
        logo = load_nova_logo(max(16, int(size * 0.88)))
        if not logo.isNull():
            painter.drawPixmap(
                (size - logo.width()) // 2,
                (size - logo.height()) // 2,
                logo,
            )
        else:
            painter.setPen(QColor(TEXT))
            painter.setFont(QFont("Segoe UI", max(10, size // 2), QFont.Bold))
            painter.drawText(pixmap.rect(), Qt.AlignCenter, letter)
    elif letter == "Y":
        try:
            profile = load_settings()
            avatar_path = str(profile.get("profile_avatar", "") or "")
            if not avatar_path:
                avatar_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "default-user-avatar.svg")
            source = QPixmap(avatar_path)
            if not source.isNull():
                painter.save()
                clip = QPainterPath()
                clip.addEllipse(0, 0, size, size)
                painter.setClipPath(clip)
                scaled = source.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
                painter.restore()
            else:
                painter.setPen(QColor(TEXT))
                painter.setFont(QFont("Segoe UI", max(10, size // 2), QFont.Bold))
                painter.drawText(pixmap.rect(), Qt.AlignCenter, letter)
        except Exception:
            painter.setPen(QColor(TEXT))
            painter.setFont(QFont("Segoe UI", max(10, size // 2), QFont.Bold))
            painter.drawText(pixmap.rect(), Qt.AlignCenter, letter)
    else:
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
    def __init__(self, text, font_size=16, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; color: #c9d1d9; }")
        self.document().setDocumentMargin(0)
        text_option = QTextOption()
        text_option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(text_option)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        
        body_style = f"""
        body {{ font-family: 'Segoe UI', sans-serif; font-size: {int(font_size)}px; color: {TEXT}; line-height: 1.55; }}
        h1, h2, h3 {{ color: {TEXT}; margin: 12px 0 6px 0; }}
        h1 {{ font-size: 20px; }} h2 {{ font-size: 18px; }} h3 {{ font-size: 16px; }}
        strong {{ color: #ffffff; }}
        code {{ background: {BG_INPUT}; color: {TEXT}; padding: 2px 5px; border-radius: 4px; font-family: monospace; }}
        a {{ color: #58a6ff; text-decoration: none; }}
        p {{ margin: 6px 0 12px 0; white-space: normal; }}
        li {{ margin: 3px 0; }}
        td, th {{ vertical-align: top; }}
        pre {{ white-space: pre-wrap; word-wrap: break-word; }}
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
        
        self._last_document_width = 0
        self.document().contentsChanged.connect(self.update_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def update_height(self):
        width = max(1, self.viewport().width())
        self.document().setTextWidth(width)
        self._last_document_width = width
        height = int(self.document().size().height() + 10)
        self.setFixedHeight(max(24, height))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(1, self.viewport().width())
        if width != self._last_document_width:
            self.update_height()

    def wheelEvent(self, event):
        # This browser is sized to its full document height and has no
        # internal scrollbar. Let the enclosing chat QScrollArea handle
        # mouse-wheel input instead of swallowing it here.
        event.ignore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_height()


def add_markdown_content(layout, text, font_size=14):
    for kind, value, language in split_markdown_blocks(text):
        if kind == "code":
            layout.addWidget(CodeBlock(value, language))
            continue
        if not value.strip():
            continue
        
        html = render_markdown_text(value)
        label = MarkdownLabel(html, font_size=font_size)
        layout.addWidget(label)


class TaskPlanWidget(QFrame):
    """Compact task ledger; checkmarks reflect planner execution state."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("taskPlan")
        self.setStyleSheet(f"QFrame#taskPlan {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(12, 9, 12, 10)
        self._root.setSpacing(6)
        header = QHBoxLayout()
        title = QLabel("TASK PLAN")
        title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 800; letter-spacing: 1px; border: none;")
        header.addWidget(title)
        header.addStretch(1)
        self._progress = QLabel("0 / 0")
        self._progress.setStyleSheet(f"color: {ACCENT}; font-size: 10px; font-weight: 700; border: none;")
        header.addWidget(self._progress)
        self._root.addLayout(header)
        self._steps = QVBoxLayout()
        self._steps.setContentsMargins(0, 0, 0, 0)
        self._steps.setSpacing(5)
        self._root.addLayout(self._steps)

    def set_plan(self, plan):
        while self._steps.count():
            item = self._steps.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        steps = plan.get("steps", []) if isinstance(plan, dict) else []
        steps = [step for step in steps if isinstance(step, dict)]
        completed = sum(
            str(step.get("status", "pending") or "pending").casefold()
            in {"completed", "complete", "done", "verified"}
            for step in steps
        )
        for index, step in enumerate(steps[:6], 1):
            status = str(step.get("status", "pending") or "pending").casefold()
            done = status in {"completed", "complete", "done", "verified"}
            failed = status in {"failed", "error"}
            marker = "✓" if done else "×" if failed else "●" if status in {"running", "in_progress", "in progress"} else "○"
            color = "#7ee787" if done else "#ff7b72" if failed else ACCENT if marker == "●" else TEXT_MUTED
            title = str(step.get("description") or step.get("action") or step.get("tool") or f"Step {index}")
            label = QLabel(f"{marker}  {title}")
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {color if done or failed or marker == '●' else TEXT}; font-size: 11px; border: none; background: transparent;")
            self._steps.addWidget(label)
        if len(steps) > 6:
            more = QLabel(f"+ {len(steps) - 6} more steps")
            more.setTextFormat(Qt.PlainText)
            more.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; border: none;")
            self._steps.addWidget(more)
        self._progress.setText(f"{completed} / {len(steps)} completed")
        self.setVisible(bool(steps))


class ModelDiscoveryWorker(QThread):
    """Discover Ollama models without blocking the GUI event loop."""
    models_ready = Signal(list)
    discovery_failed = Signal(str)

    def run(self):
        try:
            import ollama
            data = ollama.Client(timeout=3).list()
            items = data.get("models", []) if isinstance(data, dict) else getattr(data, "models", [])
            names = []
            for item in items or []:
                if isinstance(item, dict):
                    name = item.get("model") or item.get("name")
                else:
                    name = getattr(item, "model", None) or getattr(item, "name", None)
                if name:
                    names.append(str(name).strip())
            self.models_ready.emit(sorted(set(filter(None, names)), key=str.casefold))
        except Exception as exc:
            self.discovery_failed.emit(f"{type(exc).__name__}: {exc}")


class RemoteModelDiscoveryWorker(QThread):
    """Fetch model catalogs from explicitly configured remote profiles."""
    catalogs_ready = Signal(dict)

    def __init__(self, profiles, parent=None):
        super().__init__(parent)
        self.profiles = [dict(item) for item in (profiles or []) if isinstance(item, dict)]

    def run(self):
        import urllib.request
        catalogs = {}
        for profile in self.profiles:
            profile_id = str(profile.get("id", "") or "")
            base_url = str(profile.get("base_url", "") or "").strip().rstrip("/")
            api_key = str(profile.get("api_key", "") or "").strip()
            provider = str(profile.get("provider", "openai") or "openai").casefold()
            if not profile_id or not base_url or not api_key:
                continue
            if provider == "anthropic":
                endpoint_base = base_url if base_url.endswith("/v1") else base_url + "/v1"
                endpoint = endpoint_base + "/models?limit=1000"
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Accept": "application/json",
                }
            else:
                endpoint_base = base_url if base_url.endswith("/v1") else base_url + "/v1"
                endpoint = endpoint_base + "/models"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                }
            try:
                request = urllib.request.Request(endpoint, headers=headers, method="GET")
                with urllib.request.urlopen(request, timeout=4) as response:
                    payload = json.loads(response.read().decode("utf-8", "replace"))
                entries = payload.get("data", []) if isinstance(payload, dict) else []
                models = sorted({
                    str(item.get("id")).strip()
                    for item in entries
                    if isinstance(item, dict) and item.get("id")
                }, key=str.casefold)
                if models:
                    catalogs[profile_id] = models
            except Exception:
                # Some compatible endpoints intentionally do not expose /models.
                # The saved profile model remains available as a fallback.
                continue
        self.catalogs_ready.emit(catalogs)


class AgentWorker(QThread):
    """Run one agent turn outside the GUI thread with cooperative cancellation.

    Token callbacks can arrive hundreds of times per second. Coalesce them on
    the worker thread before crossing the Qt queued-signal boundary, otherwise
    the GUI event queue and QTextDocument layout work can fall behind generation.
    """
    status = Signal(str)
    completed = Signal(str)
    title_generated = Signal(str, str)
    failed = Signal(str)
    cancelled = Signal()
    _DELTA_PREFIXES = ("MODEL_ANSWER_DELTA:", "MODEL_THOUGHT_DELTA:")

    def __init__(self, core, message, parent=None, generate_title=False, chat_id=None):
        super().__init__(parent)
        self.core = core
        self.message = message
        self.generate_title = bool(generate_title)
        self.chat_id = str(chat_id or "")
        self.cancel_event = threading.Event()
        self._pending_deltas = []
        self._last_delta_flush = 0.0
        self._delta_interval = 1.0 / 30.0

    def request_stop(self):
        self.cancel_event.set()

    def _flush_deltas(self):
        pending, self._pending_deltas = self._pending_deltas, []
        self._last_delta_flush = time.monotonic()
        current_prefix = None
        current_values = []
        for prefix, value in pending:
            if current_prefix is not None and prefix != current_prefix:
                self.status.emit(current_prefix + "".join(current_values))
                current_values = []
            current_prefix = prefix
            current_values.append(value)
        if current_prefix is not None:
            self.status.emit(current_prefix + "".join(current_values))

    def _queue_status(self, message):
        message = str(message)
        for prefix in self._DELTA_PREFIXES:
            if message.startswith(prefix):
                value = message[len(prefix):]
                if value:
                    self._pending_deltas.append((prefix, value))
                if time.monotonic() - self._last_delta_flush >= self._delta_interval:
                    self._flush_deltas()
                return
        self._flush_deltas()
        self.status.emit(message)

    def run(self):
        self.core.cancel_event = self.cancel_event
        self.core.status_callback = self._queue_status
        try:
            result = self.core.ask(self.message)
            self._flush_deltas()
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.completed.emit(str(result))
                if self.generate_title and self.chat_id:
                    try:
                        title = self.core.brain.generate(
                            "Create a concise title for this conversation. "
                            "Use the same language as the user's message. "
                            "Return only the title, without quotes or explanation, "
                            "in at most 6 words.\n\n"
                            f"User's first message:\n{self.message[:1200]}",
                            system_prompt=(
                                "You generate short, accurate chat titles. "
                                "Do not answer the user's request; only name the conversation."
                            ),
                        )
                        title = " ".join(str(title or "").strip().strip(chr(34) + chr(39) + chr(96)).split())
                        title = re.sub(r"^(title|عنوان)\s*[:：-]\s*", "", title, flags=re.IGNORECASE)
                        title = title[:64].strip()
                        if title:
                            self.title_generated.emit(self.chat_id, title)
                    except Exception:
                        # Title generation is auxiliary; a failed title call
                        # must never turn a successful chat response into an error.
                        pass
        except GenerationCancelled:
            self._flush_deltas()
            self.cancelled.emit()
        except Exception as exc:
            self._flush_deltas()
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            if getattr(self.core, "cancel_event", None) is self.cancel_event:
                self.core.cancel_event = None
                self.core.status_callback = None


class StreamingMessageWidget(QFrame):
    """Plain-text assistant draft updated as model deltas arrive."""
    def __init__(self, font_size=18, parent=None):
        super().__init__(parent)
        self.setObjectName("streamingMessage")
        self.setStyleSheet("QFrame#streamingMessage { background: transparent; border: none; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 29)
        layout.setSpacing(17)
        avatar = QLabel()
        avatar.setFixedSize(34, 34)
        avatar.setPixmap(make_avatar("N", 32))
        avatar.setAlignment(Qt.AlignTop)
        avatar.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(avatar, 0, Qt.AlignTop)
        body = QVBoxLayout()
        name = QLabel("Nova")
        name.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 700; border: none; background: transparent;")
        body.addWidget(name)
        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setFrameShape(QFrame.NoFrame)
        self.editor.setStyleSheet(f"QPlainTextEdit {{ background: transparent; border: none; color: {TEXT}; font-size: {int(font_size)}px; padding: 0; }}")
        self.editor.setMinimumHeight(28)
        self.editor.setMaximumHeight(360)
        body.addWidget(self.editor)
        layout.addLayout(body, 1)

    def append_delta(self, delta):
        if not delta:
            return
        self.editor.moveCursor(self.editor.textCursor().MoveOperation.End)
        self.editor.insertPlainText(str(delta))
        self.editor.ensureCursorVisible()

    def clear(self):
        self.editor.clear()


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
        self.setFixedHeight(max(38, min(self.MAX_HEIGHT, wanted)))
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
        self._pulse_phase = 0

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
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(180)
        self._pulse_timer.timeout.connect(self._pulse)
        self._pulse_timer.start()

    def _pulse(self):
        if self._finished:
            self._pulse_timer.stop()
            return
        self._pulse_phase = (self._pulse_phase + 1) % 4
        colors = (ACCENT, "#9b8cff", "#c084fc", "#9b8cff")
        sizes = (8, 9, 10, 9)
        self._indicator.setStyleSheet(
            f"color: {colors[self._pulse_phase]}; font-size: {sizes[self._pulse_phase]}px; border: none; background: transparent;"
        )

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
        self._pulse_timer.stop()
        self._tick()
        self._indicator.setText("○")
        self._indicator.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8px; border: none; background: transparent;")
        if not self._has_content:
            self._body.setPlainText("The selected model did not return reasoning for this turn.")
        self._expanded = False
        self._body.setVisible(False)
        self._toggle.setText("Show")


class MessageWidget(QFrame):
    def __init__(self, role, text, attachments=None, font_size=16, parent=None):
        super().__init__(parent)
        is_user = role == "user"
        self.setObjectName("userMessageRow" if is_user else "assistantMessageRow")
        self.setStyleSheet("""
            QFrame#userMessageRow, QFrame#assistantMessageRow { background: transparent; border: none; }
            QFrame#userBubble { background: #151f2b; border: 1px solid #2b3b4e; border-radius: 15px; }
        """)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 20)
        row.setSpacing(12)
        avatar = QLabel()
        avatar.setFixedSize(32, 32)
        avatar.setPixmap(make_avatar("Y" if is_user else "N", 32))
        avatar.setAlignment(Qt.AlignTop)
        avatar.setStyleSheet("border: none; background: transparent;")
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(6)
        name = QLabel("You" if is_user else "Nova")
        name.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 650; border: none; background: transparent;")
        content.addWidget(name)
        add_markdown_content(content, text if text else ("Attached files" if attachments else " "), font_size=font_size if not is_user else 14)
        if is_user and attachments:
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
                badge.setStyleSheet(f"color: {TEXT}; background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 7px; padding: 5px 9px; font-size: 11px;")
                badge.setToolTip(path)
                badges.addWidget(badge)
            badges.addStretch(1)
            content.addLayout(badges)
        if is_user:
            bubble = QFrame()
            bubble.setObjectName("userBubble")
            bubble.setMaximumWidth(780)
            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(15, 11, 15, 11)
            bubble_layout.setSpacing(0)
            bubble_layout.addLayout(content)
            row.addStretch(1)
            row.addWidget(bubble, 0, Qt.AlignRight | Qt.AlignTop)
            row.addWidget(avatar, 0, Qt.AlignTop)
        else:
            row.addWidget(avatar, 0, Qt.AlignTop)
            row.addLayout(content, 1)


class EffortSlider(QSlider):
    """Six-stop slider with a softly animated halo around the active level."""

    LEVEL_COLORS = ("#8b949e", "#79c0ff", "#58a6ff", "#a78bfa", "#c084fc", "#f0abfc")

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._phase = 0.0
        self._visual_value = 0.0
        self._level_animation = QPropertyAnimation(self, b"visualValue", self)
        self._level_animation.setDuration(190)
        self._level_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self._advance_pulse)
        self.valueChanged.connect(self._animate_level)

    @Property(float)
    def visualValue(self):
        return self._visual_value

    @visualValue.setter
    def visualValue(self, value):
        self._visual_value = float(value)
        self.update()

    def _animate_level(self, value):
        self._level_animation.stop()
        self._level_animation.setStartValue(self._visual_value)
        self._level_animation.setEndValue(float(value))
        self._level_animation.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._pulse_timer.start()

    def hideEvent(self, event):
        self._pulse_timer.stop()
        super().hideEvent(event)

    def _advance_pulse(self):
        self._phase = (self._phase + 0.055) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderGroove, self)
        handle = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self)
        if self.maximum() <= self.minimum():
            return
        left = groove.left() + handle.width() / 2
        right = groove.right() - handle.width() / 2
        y = groove.center().y()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        visual_index = max(0.0, min(float(self.maximum()), self._visual_value))
        active_index = int(round(visual_index))
        active_x = left + (right - left) * visual_index / (self.maximum() - self.minimum())
        for index, color_hex in enumerate(self.LEVEL_COLORS):
            x = left + (right - left) * index / (self.maximum() - self.minimum())
            color = QColor(color_hex)
            if index == active_index:
                x = active_x
                pulse = (math.sin(self._phase) + 1.0) / 2.0
                painter.setPen(Qt.NoPen)
                if index == self.maximum():
                    center = QPointF(x, y)
                    radius = 17 + pulse * 5
                    glow = QRadialGradient(center, radius)
                    glow.setColorAt(0.0, QColor(190, 150, 255, 125))
                    glow.setColorAt(0.42, QColor(130, 110, 255, 62))
                    glow.setColorAt(1.0, QColor(130, 110, 255, 0))
                    painter.setBrush(glow)
                    painter.drawEllipse(center, radius, radius)
                    painter.setBrush(Qt.NoBrush)
                    painter.setPen(QPen(QColor(190, 160, 255, 170 + int(pulse * 70)), 1.4))
                    painter.drawEllipse(center, 8 + pulse * 2.5, 8 + pulse * 2.5)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor("#e8d8ff"))
                    painter.drawEllipse(center, 3.8, 3.8)
                    for spark in range(4):
                        angle = self._phase * 1.25 + spark * (math.pi / 2)
                        orbit = 12 + pulse * 2
                        sx = x + math.cos(angle) * orbit
                        sy = y + math.sin(angle) * orbit
                        painter.setBrush(QColor("#c7a5ff"))
                        painter.drawEllipse(QPointF(sx, sy), 1.5, 1.5)
                else:
                    halo = QColor(color)
                    halo.setAlpha(int(45 + pulse * 55))
                    painter.setBrush(halo)
                    painter.drawEllipse(QPointF(x, y), 7 + pulse * 3, 7 + pulse * 3)
                    painter.setBrush(color)
                    painter.drawEllipse(QPointF(x, y), 3.2, 3.2)
            else:
                color.setAlpha(150)
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(QPointF(x, y), 2.0, 2.0)
        painter.end()


class EffortSelector(QWidget):
    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QWidget { background: transparent; border: none; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._slider = EffortSlider()
        self._slider.setRange(0, len(EFFORT_LEVELS) - 1)
        self._slider.setValue(2)
        self._slider.setTickPosition(QSlider.TicksBelow)
        self._slider.setTickInterval(1)
        # Reserve breathing room around the animated NovaCode halo. The
        # handle sits inside this padded track, so its glow/sparks aren't
        # clipped by QSlider's paint boundary at the final stop.
        self._slider.setFixedWidth(340)
        self._slider.setFixedHeight(52)
        self._slider.setStyleSheet(f"""
            QSlider {{ border: none; background: transparent; padding: 0 20px; }}
            QSlider::groove:horizontal {{ height: 3px; background: #41454b; border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: #777b84; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: #e8e8eb; border: 2px solid #777b84; width: 12px; height: 12px; margin: -6px 0; border-radius: 7px; }}
            QSlider::handle:horizontal:hover {{ border-color: #ffffff; }}
            QSlider::add-page:horizontal {{ background: #41454b; }}
        """)
        self._slider.valueChanged.connect(self._changed)
        layout.addWidget(self._slider)

        labels = QHBoxLayout()
        # Match the slider's handle-center travel: the handle cannot reach
        # the widget edges, so labels need the same inset to sit under each stop.
        labels.setContentsMargins(29, 0, 29, 0)
        labels.setSpacing(0)
        for label_text in ("Off", "Low", "Med", "High", "Max", "Nova"):
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; background: transparent; border: none;")
            labels.addWidget(label, 1)
        layout.addLayout(labels)
        self._set_aura(2)

    def _set_aura(self, index):
        colors = EffortSlider.LEVEL_COLORS
        self._slider.setProperty("activeLevel", index)
        self._slider.update()

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


class RemoteModelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Add remote model')
        self.setModal(True)
        self.resize(480, 470)
        self.setStyleSheet(f'QDialog {{ background: {BG_MAIN}; color: {TEXT}; }} QLabel {{ color: {TEXT}; }} QLineEdit {{ background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 9px; }} QPushButton {{ background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 8px 12px; }}')
        layout = QVBoxLayout(self)
        self.name = QLineEdit(); self.name.setPlaceholderText('Display name, e.g. Claude Sonnet')
        self.openai = QRadioButton('OpenAI-compatible API')
        self.anthropic = QRadioButton('Anthropic Claude API')
        self.openai.setChecked(True)
        self.base = QLineEdit('https://api.openai.com/v1')
        self.model = QLineEdit(); self.model.setPlaceholderText('Model name / model ID')
        self.key = QLineEdit(); self.key.setEchoMode(QLineEdit.Password); self.key.setPlaceholderText('API key')
        self.reveal = QToolButton(); self.reveal.setText('Show'); self.reveal.setCheckable(True)
        self.reveal.toggled.connect(lambda value: (self.key.setEchoMode(QLineEdit.Normal if value else QLineEdit.Password), self.reveal.setText('Hide' if value else 'Show')))
        key_row = QHBoxLayout(); key_row.addWidget(self.key, 1); key_row.addWidget(self.reveal)
        for label, widget in [('Model provider', self.openai), ('', self.anthropic), ('Profile name', self.name), ('Base URL', self.base), ('Model name', self.model)]:
            if label: layout.addWidget(QLabel(label))
            layout.addWidget(widget)
        layout.addWidget(QLabel('API key')); layout.addLayout(key_row)
        self.anthropic.toggled.connect(self._provider_changed)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject)
        layout.addStretch(1); layout.addWidget(buttons)
    def _provider_changed(self, checked):
        if checked:
            self.base.setText('https://api.anthropic.com')
            self.model.setPlaceholderText('e.g. claude-sonnet-4-20250514')
        else:
            self.base.setText('https://api.openai.com/v1')
            self.model.setPlaceholderText('e.g. gpt-4o-mini')
    def _save(self):
        if not self.name.text().strip() or not self.model.text().strip() or not self.key.text().strip():
            QMessageBox.warning(self, 'Missing information', 'Name, model, and API key are required.')
            return
        self.accept()
    def values(self):
        return {'name': self.name.text().strip(), 'provider': 'anthropic' if self.anthropic.isChecked() else 'openai', 'base_url': self.base.text().strip(), 'model': self.model.text().strip(), 'api_key': self.key.text().strip()}

class ModelSettingsDialog(QDialog):
    def __init__(self, settings, installed_models, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Model settings")
        self.setModal(True)
        self.setObjectName("settingsDialog")
        available = self.screen().availableGeometry() if self.screen() else QApplication.primaryScreen().availableGeometry()
        dialog_width = min(820, max(560, available.width() - 64))
        dialog_height = min(900, max(420, available.height() - 64))
        self.setMinimumSize(min(560, dialog_width), min(420, dialog_height))
        self.setMaximumSize(dialog_width, dialog_height)
        self.resize(dialog_width, dialog_height)
        self.setStyleSheet(f"""
            QDialog#settingsDialog {{ background: {BG_MAIN}; color: {TEXT}; }}
            QLabel {{ color: {TEXT}; }}
            QLineEdit {{ background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 9px; padding: 10px 12px; min-height: 22px; selection-background-color: #304c70; }}
            QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
            QRadioButton {{ color: {TEXT}; spacing: 9px; padding: 7px 2px; }}
            QRadioButton::indicator {{ width: 16px; height: 16px; }}
            QPushButton {{ background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 9px; padding: 9px 16px; min-width: 86px; }}
            QPushButton:hover {{ background: #203044; border-color: #405a76; }}
        """)

        self._settings = dict(settings)
        self._installed = list(installed_models or [])
        self._existing_key = str(settings.get("api_key", "") or "")
        try:
            self._remote_profiles = json.loads(settings.get("remote_models", "[]") or "[]")
            if not isinstance(self._remote_profiles, list):
                self._remote_profiles = []
        except (TypeError, json.JSONDecodeError):
            self._remote_profiles = []
        self._active_remote_id = str(settings.get("active_remote_model_id", "") or "")
        self._avatar_path = str(settings.get("profile_avatar", "") or "")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        scroll = QScrollArea(self)
        scroll.setObjectName("settingsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet(f"QScrollArea#settingsScrollArea {{ background: transparent; border: none; }} QScrollBar:vertical {{ background: {BG_MAIN}; width: 9px; margin: 4px 2px; }} QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 28px; }} QScrollBar::handle:vertical:hover {{ background: #40536a; }} QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}")
        content = QWidget()
        content.setObjectName("settingsContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 25, 28, 24)
        layout.setSpacing(15)
        scroll.setWidget(content)
        root_layout.addWidget(scroll)

        brand = QLabel("NOVA  /  SETTINGS")
        brand.setStyleSheet(f"color: {ACCENT}; font-size: 10px; font-weight: 800; letter-spacing: 2px;")
        layout.addWidget(brand)
        heading = QLabel("Model & connections")
        heading.setStyleSheet("font-size: 23px; font-weight: 750; border: none; background: transparent;")
        layout.addWidget(heading)

        note = QLabel("Local keeps everything on this computer. Remote sends your messages, file contents, tool results, and any profile or custom instructions you enable to the provider you configure.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; border: none; background: transparent;")
        layout.addWidget(note)

        provider_title = QLabel("PROVIDER")
        provider_title.setStyleSheet(f"color: {ACCENT}; font-size: 10px; font-weight: 800; letter-spacing: 1.5px; padding-top: 10px;")
        layout.addWidget(provider_title)
        provider_rule = QFrame()
        provider_rule.setFixedHeight(1)
        provider_rule.setStyleSheet(f"background: {BORDER}; border: none;")
        layout.addWidget(provider_rule)

        self.local_radio = QRadioButton("Local model  ·  Ollama")
        layout.addWidget(self.local_radio)

        self.local_model = QLineEdit(str(settings.get("local_model", "") or ""))
        self.local_model.setPlaceholderText("Model name, e.g. qwen2.5:3b (blank = auto-detect)")
        layout.addWidget(self.local_model)

        if self._installed:
            hint = QLabel("Installed: " + ", ".join(self._installed[:6]))
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; border: none; background: transparent;")
            layout.addWidget(hint)

        self.remote_radio = QRadioButton("Remote API  ·  OpenAI-compatible")
        layout.addWidget(self.remote_radio)

        self.api_base = QLineEdit(str(settings.get("api_base_url", "") or ""))
        self.api_base.setPlaceholderText("https://api.openai.com/v1")
        layout.addWidget(self._labelled("Base URL", self.api_base))

        self.api_model = QLineEdit(str(settings.get("api_model", "") or ""))
        self.api_model.setPlaceholderText("e.g. gpt-4o-mini, or a gateway model id")
        layout.addWidget(self._labelled("Model", self.api_model))

        key_row = QHBoxLayout()
        self.api_key = QLineEdit(self._existing_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("API key")
        self.key_visibility = QToolButton()
        self.key_visibility.setText("Show")
        self.key_visibility.setCheckable(True)
        self.key_visibility.toggled.connect(lambda visible: (self.api_key.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password), self.key_visibility.setText("Hide" if visible else "Show")))
        key_row.addWidget(self.api_key, 1)
        key_row.addWidget(self.key_visibility)
        key_wrap = QWidget()
        key_wrap.setLayout(key_row)
        layout.addWidget(self._labelled("API key", key_wrap))

        remote_title = QLabel("SAVED REMOTE MODELS")
        remote_title.setStyleSheet(f"color: {ACCENT}; font-size: 10px; font-weight: 800; letter-spacing: 1.5px; padding-top: 12px;")
        layout.addWidget(remote_title)
        self.remote_list = QListWidget()
        self.remote_list.setMaximumHeight(100)
        self.remote_list.setStyleSheet(f"QListWidget {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }} QListWidget::item {{ padding: 7px; border-radius: 5px; }} QListWidget::item:selected {{ background: #26364b; }}")
        for profile in self._remote_profiles:
            if isinstance(profile, dict):
                self.remote_list.addItem(str(profile.get("name", "Remote model")) + "  ·  " + str(profile.get("model", "")))
                if str(profile.get("id", "")) == self._active_remote_id:
                    self.remote_list.setCurrentRow(self.remote_list.count() - 1)
        layout.addWidget(self.remote_list)
        self.remote_list.itemClicked.connect(lambda _item: self.remote_radio.setChecked(True))
        remote_actions = QHBoxLayout()
        add_remote = QPushButton("+ Add New Model")
        remove_remote = QPushButton("Remove Selected")
        add_remote.clicked.connect(self._add_remote_model)
        remove_remote.clicked.connect(self._remove_remote_model)
        remote_actions.addWidget(add_remote)
        remote_actions.addWidget(remove_remote)
        layout.addLayout(remote_actions)
        instructions_title = QLabel("MODEL INSTRUCTIONS")
        instructions_title.setStyleSheet(f"color: {ACCENT}; font-size: 10px; font-weight: 800; letter-spacing: 1.5px; padding-top: 12px;")
        layout.addWidget(instructions_title)
        self.model_instructions = QPlainTextEdit(str(settings.get("model_instructions", "") or ""))
        self.model_instructions.setPlaceholderText("Tell Nova how you want it to respond and collaborate...")
        self.model_instructions.setMaximumHeight(95)
        self.model_instructions.setStyleSheet(f"QPlainTextEdit {{ background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 9px; padding: 9px; }}")
        layout.addWidget(self.model_instructions)
        profile_title = QLabel("YOUR INFO")
        profile_title.setStyleSheet(f"color: {ACCENT}; font-size: 10px; font-weight: 800; letter-spacing: 1.5px; padding-top: 12px;")
        layout.addWidget(profile_title)
        self.profile_name = QLineEdit(str(settings.get("profile_name", "") or ""))
        self.profile_name.setPlaceholderText("Name (optional)")
        self.profile_age = QLineEdit(str(settings.get("profile_age", "") or ""))
        self.profile_age.setPlaceholderText("Age (optional)")
        self.profile_occupation = QLineEdit(str(settings.get("profile_occupation", "") or ""))
        self.profile_occupation.setPlaceholderText("Work / study / role (optional)")
        layout.addWidget(self._labelled("Name", self.profile_name))
        layout.addWidget(self._labelled("Age", self.profile_age))
        layout.addWidget(self._labelled("Occupation", self.profile_occupation))
        avatar_row = QHBoxLayout()
        self.avatar_label = QLabel(os.path.basename(self._avatar_path) if self._avatar_path else "Default user avatar")
        self.avatar_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        avatar_row.addWidget(self.avatar_label, 1)
        avatar_button = QPushButton("Choose profile picture")
        avatar_button.clicked.connect(self._choose_profile_avatar)
        avatar_row.addWidget(avatar_button)
        layout.addLayout(avatar_row)

        font_title = QLabel("ASSISTANT TEXT SIZE")
        font_title.setStyleSheet(f"color: {ACCENT}; font-size: 10px; font-weight: 800; letter-spacing: 1.5px; padding-top: 10px;")
        layout.addWidget(font_title)
        font_rule = QFrame()
        font_rule.setFixedHeight(1)
        font_rule.setStyleSheet(f"background: {BORDER}; border: none;")
        layout.addWidget(font_rule)
        font_row = QHBoxLayout()
        font_hint = QLabel("Nova response font")
        font_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        font_row.addWidget(font_hint)
        font_row.addStretch(1)
        self.font_value = QLabel(f'{settings.get("assistant_font_size", "18")} px')
        self.font_value.setStyleSheet(f"color: {ACCENT}; font-weight: 700;")
        font_row.addWidget(self.font_value)
        layout.addLayout(font_row)
        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(15, 24)
        try:
            self.font_slider.setValue(max(15, min(24, int(settings.get("assistant_font_size", "18")))))
        except (TypeError, ValueError):
            self.font_slider.setValue(18)
        self.font_slider.setTickPosition(QSlider.TicksBelow)
        self.font_slider.setTickInterval(1)
        self.font_slider.valueChanged.connect(lambda value: self.font_value.setText(f"{value} px"))
        self.font_slider.setStyleSheet(f"QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }} QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }} QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; margin: -6px 0; border-radius: 7px; }}")
        layout.addWidget(self.font_slider)

        # Turn the long settings form into clear product categories.
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.setObjectName("settingsTabs")
        tabs.setStyleSheet(f"""
            QTabWidget#settingsTabs::pane {{ border: 1px solid {BORDER}; border-radius: 10px; background: {BG_PANEL}; top: -1px; }}
            QTabBar::tab {{ color: {TEXT_MUTED}; background: transparent; border: 1px solid transparent; padding: 10px 15px; margin-right: 4px; font-size: 12px; }}
            QTabBar::tab:selected {{ color: {TEXT}; background: {BG_PANEL}; border-color: {BORDER}; border-bottom-color: {BG_PANEL}; border-top-left-radius: 7px; border-top-right-radius: 7px; }}
            QTabBar::tab:hover:!selected {{ color: {TEXT}; background: {BG_INPUT}; border-radius: 7px; }}
        """)
        tab_pages = {}
        tab_layouts = {}
        for key, label in (("models", "Models"), ("instructions", "Instructions"), ("profile", "Profile"), ("appearance", "Appearance")):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(16, 14, 16, 16)
            page_layout.setSpacing(12)
            tab_pages[key] = page
            tab_layouts[key] = page_layout
            tabs.addTab(page, label)

        active_page = "models"
        markers = {
            "MODEL INSTRUCTIONS": "instructions",
            "YOUR INFO": "profile",
            "ASSISTANT TEXT SIZE": "appearance",
        }
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None and isinstance(widget, QLabel):
                marker = widget.text().strip()
                if marker in markers:
                    active_page = markers[marker]
            if widget is not None:
                tab_layouts[active_page].addWidget(widget)
            elif item.layout() is not None:
                nested_layout = item.layout()
                nested_layout.setParent(None)
                tab_layouts[active_page].addLayout(nested_layout)
            else:
                tab_layouts[active_page].addItem(item)
        for page_layout in tab_layouts.values():
            page_layout.addStretch(1)
        layout.addWidget(tabs)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; border: none; background: transparent; padding: 5px 2px;")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        buttons.setStyleSheet(f"QDialogButtonBox {{ border: none; }} QPushButton {{ min-width: 104px; min-height: 38px; }}")
        layout.addStretch(1)
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
        selected = self.remote_list.currentRow()
        active_id = self._active_remote_id
        if 0 <= selected < len(self._remote_profiles):
            active_id = str(self._remote_profiles[selected].get("id", ""))
        active_profile = self._remote_profiles[selected] if 0 <= selected < len(self._remote_profiles) else {}
        return {
            "provider": "remote" if self.remote_radio.isChecked() else "local",
            "local_model": self.local_model.text().strip(),
            "api_base_url": str(active_profile.get("base_url") or self.api_base.text().strip()),
            "api_model": str(active_profile.get("model") or self.api_model.text().strip()),
            "api_key": str(active_profile.get("api_key") or typed_key or self._existing_key),
            "assistant_font_size": str(self.font_slider.value()),
            "remote_models": json.dumps(self._remote_profiles, ensure_ascii=False),
            "active_remote_model_id": active_id,
            "model_instructions": self.model_instructions.toPlainText().strip(),
            "profile_name": self.profile_name.text().strip(),
            "profile_age": self.profile_age.text().strip(),
            "profile_occupation": self.profile_occupation.text().strip(),
            "profile_avatar": self._avatar_path,
        }

    def _choose_profile_avatar(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose profile picture', '', 'Images (*.png *.jpg *.jpeg *.webp *.bmp)')
        if path:
            self._avatar_path = os.path.abspath(path)
            self.avatar_label.setText(os.path.basename(path))

    def _add_remote_model(self):
        dialog = RemoteModelDialog(self)
        if dialog.exec() == QDialog.Accepted:
            profile = dialog.values()
            profile['id'] = uuid.uuid4().hex
            self._remote_profiles.append(profile)
            self.remote_list.addItem(profile['name'] + '  ·  ' + profile['model'])
            self.remote_list.setCurrentRow(self.remote_list.count() - 1)
            self.remote_radio.setChecked(True)
            self._refresh()

    def _remove_remote_model(self):
        row = self.remote_list.currentRow()
        if 0 <= row < len(self._remote_profiles):
            self._remote_profiles.pop(row)
            self.remote_list.takeItem(row)
            if self.remote_list.count():
                self.remote_list.setCurrentRow(0)
            else:
                self._active_remote_id = ""
                self.remote_radio.setChecked(False)
                self.local_radio.setChecked(True)
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
        self.current_chat_id = saved_chats[0]["id"] if saved_chats else None
        self._restore_core_memory(self.current_chat_id)
        
        self.thread = None
        self.worker = None
        self._active_workers = set()
        self.busy = False
        self.thinking_panel = None
        self.task_plan_panel = None
        self.thinking_enabled = False
        self.streaming_message = None
        self.attachments = []
        self._agent_sessions = [{
            "id": uuid.uuid4().hex,
            "title": "Agent 1",
            "core": self.core,
            "chat_id": self.current_chat_id,
            "attachments": [],
        }]
        self._active_agent_index = 0
        self._agent_tab_counter = 1
        self._changing_agent_tabs = False

        self.setWindowTitle("Nova")
        logo = load_nova_logo(256)
        if not logo.isNull():
            self.setWindowIcon(QIcon(logo))
        self.setMinimumSize(960, 640)
        self.resize(1240, 820)
        
        self._build_ui()
        self._apply_theme()
        self._refresh_chat_history()
        self._render_current_chat()
        self._installed_models = []
        self._model_discovery_worker = None
        self._remote_model_catalog = {}
        self._remote_model_discovery_worker = None
        self._start_model_discovery()

    def closeEvent(self, event):
        workers = list(getattr(self, "_active_workers", set()))
        for active_worker in workers:
            if active_worker.isRunning():
                active_worker.request_stop()
        for active_worker in workers:
            if active_worker.isRunning() and not active_worker.wait(1800):
                QMessageBox.information(
                    self,
                    "Nova is stopping",
                    "The current model or tool call is still shutting down. Wait a moment, then close Nova again.",
                )
                event.ignore()
                return
        for discovery_worker in (self._model_discovery_worker, self._remote_model_discovery_worker):
            if discovery_worker is not None and discovery_worker.isRunning():
                if not discovery_worker.wait(4500):
                    event.ignore()
                    return
        super().closeEvent(event)

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
        self._sync_active_agent_session()
        return True

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        self.splitter = splitter
        splitter.setHandleWidth(1)
        main_layout.addWidget(splitter)

        # Sidebar
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(236)
        sidebar.setMaximumWidth(292)
        sidebar.setStyleSheet(f"QFrame#sidebar {{ background: {BG_MAIN}; border-right: 1px solid {BORDER}; }}")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 22, 16, 18)
        sidebar_layout.setSpacing(13)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(11)
        brand_mark = QLabel()
        brand_mark.setAlignment(Qt.AlignCenter)
        brand_mark.setFixedSize(34, 34)
        brand_mark.setStyleSheet(f"background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 10px;")
        brand_logo = load_nova_logo(30)
        if not brand_logo.isNull():
            brand_mark.setPixmap(brand_logo)
        else:
            brand_mark.setText("N")
            brand_mark.setStyleSheet(f"background: {BG_INPUT}; color: {ACCENT}; border: 1px solid {BORDER}; border-radius: 10px; font-size: 17px; font-weight: 800;")
        brand_row.addWidget(brand_mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        title = QLabel("Nova")
        title.setStyleSheet(f"font-size: 17px; font-weight: 750; color: {TEXT}; border: none; background: transparent;")
        subtitle = QLabel("LOCAL AI WORKSPACE")
        subtitle.setStyleSheet(f"font-size: 9px; color: {TEXT_MUTED}; border: none; background: transparent;")
        brand_text.addWidget(title)
        brand_text.addWidget(subtitle)
        brand_row.addLayout(brand_text)
        brand_row.addStretch(1)
        sidebar_layout.addLayout(brand_row)

        new_chat_btn = QPushButton("+ New Chat")
        new_chat_btn.setFixedHeight(42)
        new_chat_btn.setStyleSheet(f"QPushButton {{ background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 9px; padding: 0 13px; color: {TEXT}; font-weight: 600; text-align: left; }} QPushButton:hover {{ background: #1d2a38; border-color: #3a4d62; }} QPushButton:pressed {{ background: {BG_PANEL}; }}")
        new_chat_btn.setCursor(Qt.PointingHandCursor)
        new_chat_btn.clicked.connect(self._new_chat)
        sidebar_layout.addWidget(new_chat_btn)

        label_chats = QLabel("CHATS")
        label_chats.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 700; letter-spacing: 1px; margin-top: 13px; border: none; background: transparent;")
        sidebar_layout.addWidget(label_chats)

        self.chat_list = QListWidget()
        self.chat_list.setFrameShape(QFrame.NoFrame)
        self.chat_list.setSpacing(4)
        self.chat_list.setTextElideMode(Qt.ElideRight)
        self.chat_list.setUniformItemSizes(True)
        self.chat_list.setStyleSheet(f"QListWidget {{ background: transparent; border: none; outline: none; }} QListWidget::item {{ color: {TEXT_MUTED}; padding: 0 11px; min-height: 38px; border: 1px solid transparent; border-radius: 8px; }} QListWidget::item:hover {{ background: {BG_INPUT}; color: {TEXT}; }} QListWidget::item:selected {{ background: #172433; color: {TEXT}; border: 1px solid #2b4057; }}")
        self.chat_list.itemClicked.connect(self._on_chat_selected)
        sidebar_layout.addWidget(self.chat_list, 1)

        settings_btn = QPushButton("⚙  Settings")
        settings_btn.setFixedHeight(40)
        settings_btn.setStyleSheet(f"QPushButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; text-align: left; padding: 0 10px; color: {TEXT_MUTED}; font-size: 13px; }} QPushButton:hover {{ color: {TEXT}; background: {BG_INPUT}; border-color: {BORDER}; }}")
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
        # Live activity state: the chip itself is rendered in the composer
        # area (created below); only the animation state lives here.
        self._status_phase = 0
        self._activity_text = ""
        self._answer_started = False
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(420)
        self._status_timer.timeout.connect(self._animate_status)

        self.model_selector = QPushButton("Loading model…")
        self.model_selector.setCursor(Qt.PointingHandCursor)
        self.model_selector.setMinimumHeight(36)
        self.model_selector.setIcon(make_icon("chevron_down", TEXT_MUTED, 13))
        self.model_selector.setLayoutDirection(Qt.LeftToRight)
        self.model_selector.setStyleSheet(f"QPushButton {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 9px; padding: 0 12px; color: {TEXT}; font-size: 12px; font-weight: 600; text-align: left; }} QPushButton:hover {{ background: {BG_INPUT}; border-color: #405a76; }}")
        self.model_selector.clicked.connect(self._show_model_menu)

        # Independent agent sessions, presented as browser-like tabs.
        tabs_row = QWidget()
        tabs_row.setObjectName("agentTabsRow")
        tabs_layout = QHBoxLayout(tabs_row)
        tabs_layout.setContentsMargins(14, 7, 14, 6)
        tabs_layout.setSpacing(8)
        self.agent_tabs = QTabWidget()
        self.agent_tabs.setObjectName("agentTabs")
        self.agent_tabs.setDocumentMode(True)
        self.agent_tabs.setTabsClosable(False)
        self.agent_tabs.setMovable(True)
        self.agent_tabs.setFixedHeight(44)
        self.agent_tabs.setStyleSheet(f"""
            QTabWidget#agentTabs::pane {{ border: none; background: transparent; }}
            QTabBar::tab {{ color: {TEXT_MUTED}; background: {BG_PANEL}; border: 1px solid {BORDER}; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; padding: 8px 34px 8px 13px; min-width: 94px; max-width: 190px; margin-right: 4px; }}
            QTabBar::tab:selected {{ color: {TEXT}; background: {BG_INPUT}; border-color: #405a76; }}
            QTabBar::tab:hover:!selected {{ color: {TEXT}; background: #17212c; }}
        """)
        self.agent_tab_bar = self.agent_tabs.tabBar()
        self.agent_tab_bar.setExpanding(False)
        self.agent_tab_bar.setDrawBase(False)
        self.agent_tab_bar.setElideMode(Qt.ElideRight)
        self.agent_tabs.addTab(QWidget(), "Agent 1")
        self._install_agent_tab_close_button(0)
        self.agent_tabs.currentChanged.connect(self._on_agent_tab_changed)
        self.agent_tab_bar.tabMoved.connect(self._on_agent_tab_moved)
        tabs_layout.addWidget(self.agent_tabs, 1)
        add_agent_tab = QPushButton("+")
        add_agent_tab.setFixedSize(28, 28)
        add_agent_tab.setToolTip("New agent tab")
        add_agent_tab.setStyleSheet(f"QPushButton {{ color: {TEXT_MUTED}; background: transparent; border: 1px solid {BORDER}; border-radius: 7px; font-size: 17px; }} QPushButton:hover {{ color: {TEXT}; background: {BG_INPUT}; }}")
        add_agent_tab.clicked.connect(self._new_agent_tab)
        tabs_layout.addWidget(add_agent_tab)
        main_layout.addWidget(tabs_row)

        # Chat Area
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setStyleSheet(f"QScrollArea {{ background: {BG_MAIN}; border: none; }}")
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.chat_container = QWidget()
        self.chat_container.setStyleSheet(f"background: {BG_MAIN};")
        self.chat_container_layout = QVBoxLayout(self.chat_container)
        self.chat_container_layout.setContentsMargins(48, 30, 48, 34)
        self.chat_container_layout.setSpacing(0)
        self.chat_container_layout.addStretch()
        
        self.chat_scroll.setWidget(self.chat_container)
        main_layout.addWidget(self.chat_scroll, 1)

        # Composer
        composer_area = QFrame()
        composer_area.setObjectName("composerArea")
        composer_area.setStyleSheet(f"QFrame#composerArea {{ background: {BG_MAIN}; border-top: 1px solid {BORDER}; }}")
        composer_layout = QVBoxLayout(composer_area)
        composer_layout.setContentsMargins(34, 10, 34, 14)

        self.composer_box = QFrame()
        self.composer_box.setObjectName("composerBox")
        self.composer_box.setStyleSheet(f"QFrame#composerBox {{ background: {BG_PANEL}; border: 1px solid #304052; border-radius: 15px; }}")
        box_layout = QVBoxLayout(self.composer_box)
        box_layout.setContentsMargins(12, 8, 10, 8)
        box_layout.setSpacing(4)

        self.input = ComposerEdit()
        self.input.setPlaceholderText("Message Nova…")
        self.input.submitted.connect(self._send)
        box_layout.addWidget(self.input)

        # Pending files appear as portrait cards in a horizontal carousel
        # above the text editor, like a modern chat composer.
        self.attachment_scroll = QScrollArea()
        self.attachment_scroll.setObjectName("attachmentCarousel")
        self.attachment_scroll.setWidgetResizable(True)
        self.attachment_scroll.setFrameShape(QFrame.NoFrame)
        self.attachment_scroll.setAttribute(Qt.WA_TranslucentBackground, True)
        self.attachment_scroll.viewport().setAutoFillBackground(False)
        self.attachment_scroll.viewport().setStyleSheet("background: transparent; border: none;")
        self.attachment_scroll.setFixedHeight(112)
        self.attachment_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.attachment_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.attachment_scroll.setStyleSheet(f"QScrollArea#attachmentCarousel {{ background: transparent; border: none; }} QScrollBar:horizontal {{ height: 6px; background: transparent; }} QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 3px; min-width: 24px; }} QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}")
        self.attachment_preview = QWidget()
        self.attachment_preview.setAttribute(Qt.WA_TranslucentBackground, True)
        self.attachment_preview.setAutoFillBackground(False)
        self.attachment_preview.setStyleSheet("background: transparent; border: none;")
        self.attachment_preview_layout = QHBoxLayout(self.attachment_preview)
        self.attachment_preview_layout.setContentsMargins(1, 2, 1, 5)
        self.attachment_preview_layout.setSpacing(8)
        self.attachment_scroll.setWidget(self.attachment_preview)
        self.attachment_scroll.hide()
        box_layout.insertWidget(0, self.attachment_scroll)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)

        add_btn = QPushButton()
        add_btn.setStyleSheet(f"QPushButton {{ background: transparent; border: none; }} QPushButton:hover {{ background: {BG_INPUT}; border-radius: 6px; }}")
        add_btn.setIcon(make_icon("plus", TEXT_MUTED, 18))
        add_btn.setFixedSize(30, 30)
        add_btn.setToolTip("Attach files")
        add_btn.clicked.connect(self._choose_attachments)
        controls.addWidget(add_btn)

        self.sidebar_toggle = QPushButton("☰")
        self.sidebar_toggle.setFixedSize(30, 30)
        self.sidebar_toggle.setToolTip("Hide or show the sidebar")
        self.sidebar_toggle.setCursor(Qt.PointingHandCursor)
        self.sidebar_toggle.setStyleSheet(f"QPushButton {{ color: {TEXT_MUTED}; background: transparent; border: 1px solid transparent; border-radius: 7px; font-size: 15px; }} QPushButton:hover {{ color: {TEXT}; background: {BG_INPUT}; border-color: {BORDER}; }}")
        self.sidebar_toggle.clicked.connect(self._toggle_sidebar)
        controls.addWidget(self.sidebar_toggle)
        self._sidebar_collapsed = False
        self._sidebar_animation = None

        self.think_button = QPushButton("Think")
        self.think_button.setCheckable(True)
        self.think_button.setChecked(False)
        self.think_button.setToolTip("Show the model's native thinking output")
        self.think_button.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED}; border: 1px solid {BORDER}; border-radius: 8px; padding: 0 11px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton:checked {{ background: {BG_INPUT}; color: {ACCENT}; border-color: {ACCENT}; }}"
            f"QPushButton:disabled {{ color: {TEXT_MUTED}; border-color: {BORDER}; }}"
        )
        self.think_button.setFixedHeight(32)
        controls.addWidget(self.think_button)

        controls.addStretch()

        self.model_selector.setMinimumHeight(32)
        self.model_selector.setMaximumWidth(330)
        self.model_selector.setStyleSheet(f"QPushButton {{ background: transparent; border: 1px solid {BORDER}; border-radius: 8px; padding: 0 9px; color: {TEXT_MUTED}; font-size: 11px; font-weight: 600; text-align: left; }} QPushButton:hover {{ background: {BG_INPUT}; border-color: #405a76; color: {TEXT}; }}")
        controls.addWidget(self.model_selector)

        self.send_button = QPushButton()
        self.send_button.setStyleSheet(f"QPushButton {{ background: {ACCENT}; border: none; border-radius: 10px; }} QPushButton:hover {{ background: #a0bcff; }} QPushButton:pressed {{ background: #6f91e8; }} QPushButton:disabled {{ background: {BORDER}; }}")
        self.send_button.setIcon(make_icon("arrow_up", BG_MAIN, 17, 2.5))
        self.send_button.setFixedSize(32, 32)
        self.send_button.setToolTip("Send message")
        self.send_button.clicked.connect(self._send)
        controls.addWidget(self.send_button)

        box_layout.addLayout(controls)

        # Tiny live activity chip above the input box: a pulsing dot plus the
        # current phase in human words ("Thinking…", "Searching the web…",
        # "Writing…") so the user always knows what Nova is doing.
        self.status_row = QWidget()
        self.status_row.setAttribute(Qt.WA_TranslucentBackground, True)
        status_row_layout = QHBoxLayout(self.status_row)
        status_row_layout.setContentsMargins(8, 2, 8, 2)
        status_row_layout.setSpacing(7)
        self.status_indicator = QLabel("●")
        self.status_indicator.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
        self.status_indicator.setStyleSheet(f"color: {ACCENT}; font-size: 8px; border: none; background: transparent;")
        status_row_layout.addWidget(self.status_indicator)
        self.status_label = QLabel()
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        status_row_layout.addWidget(self.status_label)
        status_row_layout.addStretch()
        self.status_row.hide()
        composer_layout.addWidget(self.status_row)

        composer_layout.addWidget(self.composer_box)
        main_layout.addWidget(composer_area)

        splitter.addWidget(main_content)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([272, 968])

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {BG_MAIN}; color: {TEXT}; }}
            QSplitter::handle {{ background: {BORDER}; width: 1px; }}
            QScrollBar:vertical {{ background: transparent; width: 9px; margin: 3px; }}
            QScrollBar::handle:vertical {{ background: #344354; border-radius: 4px; min-height: 42px; }}
            QScrollBar::handle:vertical:hover {{ background: #52677d; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QToolTip {{ background: {BG_PANEL}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px 8px; }}
            QMenu {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 9px; padding: 5px; }}
            QMenu::item {{ padding: 9px 26px 9px 13px; border-radius: 6px; color: {TEXT}; font-size: 13px; }}
            QMenu::item:selected {{ background: {BG_INPUT}; }}
        """)

    def _refresh_model_labels(self):
        brain = getattr(self.core, "brain", None)
        model = str(getattr(brain, "model", "") or "model")
        remote = self._settings.get("provider") == "remote"
        provider = "API" if remote else "LOCAL"
        self.model_selector.setText(f"◈  {model}  ·  {provider}   /   {EFFORT_LABELS[EFFORT_LEVELS.index(self._effort)]}  ▾")
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
        self.status_indicator.setStyleSheet(
            f"color: {colors[self._status_phase]}; font-size: 8px; border: none; background: transparent;"
        )
        # Animate the trailing dots so the chip visibly keeps working even
        # when no new events arrive for a while.
        base = self._activity_text or "Working"
        self.status_label.setText(base + "." * (self._status_phase % 3 + 1))

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
            item.setToolTip(chat["title"])
            item.setSizeHint(QSize(0, 40))
            item.setData(Qt.UserRole, chat["id"])
            self.chat_list.addItem(item)
            if chat["id"] == self.current_chat_id:
                self.chat_list.setCurrentItem(item)
        self.chat_list.blockSignals(False)
        self._refresh_model_labels()

    def _sync_active_agent_session(self):
        sessions = getattr(self, "_agent_sessions", None)
        index = getattr(self, "_active_agent_index", -1)
        if isinstance(sessions, list) and 0 <= index < len(sessions):
            sessions[index]["core"] = self.core
            sessions[index]["chat_id"] = self.current_chat_id
            sessions[index]["attachments"] = list(getattr(self, "attachments", []) or [])

    def _on_agent_tab_changed(self, index):
        if self._changing_agent_tabs or not (0 <= index < len(self._agent_sessions)):
            return
        if self.busy:
            self.agent_tabs.blockSignals(True)
            self.agent_tabs.setCurrentIndex(self._active_agent_index)
            self.agent_tabs.blockSignals(False)
            return
        self._sync_active_agent_session()
        self._active_agent_index = index
        session = self._agent_sessions[index]
        self.core = session["core"]
        self.current_chat_id = session["chat_id"]
        self.attachments = list(session.get("attachments", []))
        self.thinking_panel = None
        self.streaming_message = None
        self._refresh_attachment_preview()
        self._refresh_chat_history()
        self._render_current_chat()

    def _install_agent_tab_close_button(self, index):
        """Install a close control with a real inset from the tab's right edge.

        QTabBar positions a right-side tab button against the edge of the tab.
        A wrapper reserves an explicit 8px trailing gutter so the visible ×
        never touches the tab border, regardless of the active Qt style.
        """
        container = QWidget(self.agent_tab_bar)
        container.setObjectName("agentTabCloseContainer")
        container.setFixedSize(28, 24)

        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 2, 8, 2)
        container_layout.setSpacing(0)

        button = QToolButton(container)
        button.setObjectName("agentTabCloseButton")
        button.setText("×")
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(20, 20)
        button.setFocusPolicy(Qt.NoFocus)
        button.setStyleSheet(
            "QToolButton { color: #9aa9b8; background: transparent; border: none; "
            "border-radius: 6px; font-size: 16px; font-weight: 500; padding: 0px; }"
            "QToolButton:hover { color: #e6edf3; background: #3a4654; }"
        )
        container_layout.addWidget(button)
        button.clicked.connect(
            lambda checked=False, control=button: self._close_agent_tab(
                self.agent_tab_bar.tabAt(
                    control.mapTo(self.agent_tab_bar, control.rect().center())
                )
            )
        )
        self.agent_tab_bar.setTabButton(index, QTabBar.RightSide, container)

    def _new_agent_tab(self):
        if self.busy:
            return
        self._sync_active_agent_session()
        access = self.core.get_access()
        apply_to_environment(self._settings)
        core = self._create_core()
        core.set_access(**access)
        if hasattr(core, "set_effort"):
            core.set_effort(self._effort)
        # A tab is an empty agent session, not a persisted conversation.
        # The chat row is created only when its first message is sent.
        chat_id = None
        self._agent_tab_counter += 1
        title = f"Agent {self._agent_tab_counter}"
        self._agent_sessions.append({
            "id": uuid.uuid4().hex,
            "title": title,
            "core": core,
            "chat_id": chat_id,
            "attachments": [],
        })
        self._changing_agent_tabs = True
        self.agent_tabs.blockSignals(True)
        self.agent_tabs.addTab(QWidget(), title)
        self._install_agent_tab_close_button(self.agent_tabs.count() - 1)
        self.agent_tabs.setCurrentIndex(len(self._agent_sessions) - 1)
        self.agent_tabs.blockSignals(False)
        self._changing_agent_tabs = False
        self._active_agent_index = len(self._agent_sessions) - 1
        self.core = core
        self.current_chat_id = chat_id
        self.attachments = []
        self._refresh_attachment_preview()
        self._refresh_chat_history()
        self._render_current_chat()

    def _close_agent_tab(self, index):
        if len(self._agent_sessions) <= 1 or not (0 <= index < len(self._agent_sessions)):
            return
        if self.busy and index == self._active_agent_index:
            return
        self._sync_active_agent_session()
        self._changing_agent_tabs = True
        self.agent_tabs.blockSignals(True)
        self.agent_tab_bar.blockSignals(True)
        self.agent_tabs.removeTab(index)
        self._agent_sessions.pop(index)
        if index < self._active_agent_index:
            self._active_agent_index -= 1
        elif index == self._active_agent_index:
            self._active_agent_index = min(index, len(self._agent_sessions) - 1)
        self.agent_tabs.setCurrentIndex(self._active_agent_index)
        self.agent_tab_bar.blockSignals(False)
        self.agent_tabs.blockSignals(False)
        self._changing_agent_tabs = False
        session = self._agent_sessions[self._active_agent_index]
        self.core = session["core"]
        self.current_chat_id = session["chat_id"]
        self.attachments = list(session.get("attachments", []))
        self._refresh_attachment_preview()
        self._refresh_chat_history()
        self._render_current_chat()

    def _on_agent_tab_moved(self, from_index, to_index):
        if from_index == to_index:
            return
        session = self._agent_sessions.pop(from_index)
        self._agent_sessions.insert(to_index, session)
        self._active_agent_index = self.agent_tab_bar.currentIndex()

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
        self._sync_active_agent_session()
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
        self.current_chat_id = None
        self.core.short_memory.messages = []
        self._sync_active_agent_session()
        self._refresh_model_labels()
        self._refresh_chat_history()
        self._render_current_chat()

    def _render_current_chat(self):
        self.task_plan_panel = None
        messages = self._restore_core_memory(self.current_chat_id) if self.current_chat_id else []
        while self.chat_container_layout.count():
            item = self.chat_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        for item in messages:
            widget = MessageWidget(
                item["role"], item["content"],
                attachments=item.get("attachments") or [],
                font_size=int(self._settings.get("assistant_font_size", "18") or 18),
            )
            self.chat_container_layout.addWidget(widget)
            
        self.chat_container_layout.addStretch()
        plan = getattr(self.core, "execution_state", {}).get("last_plan")
        if isinstance(plan, dict) and plan.get("steps"):
            self._insert_task_plan_panel().set_plan(plan)
        self._scroll_chat_to_bottom()

    def _add_message(self, role, text, attachments=None):
        stretch = self.chat_container_layout.takeAt(self.chat_container_layout.count() - 1)
        widget = MessageWidget(role, text, attachments=attachments, font_size=int(self._settings.get("assistant_font_size", "18") or 16))
        self.chat_container_layout.addWidget(widget)
        if stretch:
            self.chat_container_layout.addItem(stretch)
        self._scroll_chat_to_bottom()

    def _clear_task_plan_panel(self):
        if self.task_plan_panel is not None:
            self.chat_container_layout.removeWidget(self.task_plan_panel)
            self.task_plan_panel.deleteLater()
            self.task_plan_panel = None

    def _insert_task_plan_panel(self):
        if self.task_plan_panel is not None:
            return self.task_plan_panel
        stretch = self.chat_container_layout.takeAt(self.chat_container_layout.count() - 1)
        self.task_plan_panel = TaskPlanWidget()
        self.chat_container_layout.addWidget(self.task_plan_panel)
        if stretch:
            self.chat_container_layout.addItem(stretch)
        return self.task_plan_panel

    def _insert_thinking_panel(self):
        stretch = self.chat_container_layout.takeAt(self.chat_container_layout.count() - 1)
        panel = ThinkingPanel()
        self.chat_container_layout.addWidget(panel)
        if stretch:
            self.chat_container_layout.addItem(stretch)
        self._scroll_chat_to_bottom()
        return panel

    def _ensure_streaming_message(self):
        if self.streaming_message is not None:
            return self.streaming_message
        stretch = self.chat_container_layout.takeAt(self.chat_container_layout.count() - 1)
        self.streaming_message = StreamingMessageWidget(font_size=int(self._settings.get("assistant_font_size", "16") or 16))
        self.chat_container_layout.addWidget(self.streaming_message)
        if stretch:
            self.chat_container_layout.addItem(stretch)
        self._scroll_chat_to_bottom()
        return self.streaming_message

    def _discard_streaming_message(self):
        if self.streaming_message is not None:
            self.chat_container_layout.removeWidget(self.streaming_message)
            self.streaming_message.deleteLater()
            self.streaming_message = None

    def _scroll_chat_to_bottom(self):
        QTimer.singleShot(50, lambda: self.chat_scroll.verticalScrollBar().setValue(self.chat_scroll.verticalScrollBar().maximum()))

    def _start_model_discovery(self):
        worker = getattr(self, "_model_discovery_worker", None)
        if worker is not None and worker.isRunning():
            return
        worker = ModelDiscoveryWorker(self)
        self._model_discovery_worker = worker
        worker.models_ready.connect(self._on_models_discovered)
        worker.discovery_failed.connect(lambda _error: None)
        worker.finished.connect(lambda current=worker: self._on_model_discovery_finished(current))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _start_remote_model_discovery(self):
        worker = self._remote_model_discovery_worker
        if worker is not None and worker.isRunning():
            return
        try:
            profiles = json.loads(self._settings.get("remote_models", "[]") or "[]")
        except (TypeError, ValueError):
            profiles = []
        worker = RemoteModelDiscoveryWorker(profiles, self)
        self._remote_model_discovery_worker = worker
        worker.catalogs_ready.connect(self._on_remote_models_discovered)
        worker.finished.connect(lambda current=worker: self._on_remote_model_discovery_finished(current))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_remote_models_discovered(self, catalogs):
        self._remote_model_catalog = dict(catalogs or {})
        self._refresh_model_labels()

    def _on_remote_model_discovery_finished(self, worker):
        if self._remote_model_discovery_worker is worker:
            self._remote_model_discovery_worker = None

    def _on_models_discovered(self, models):
        self._installed_models = list(models or [])
        self._refresh_model_labels()

    def _on_model_discovery_finished(self, worker):
        if self._model_discovery_worker is worker:
            self._model_discovery_worker = None

    def _toggle_sidebar(self):
        self._sidebar_collapsed = not self._sidebar_collapsed
        collapsing = self._sidebar_collapsed
        was_visible = self.sidebar.isVisible()
        current_width = self.sidebar.width() if was_visible else 0
        self.sidebar.setMinimumWidth(0)
        self.sidebar.setVisible(True)
        if self._sidebar_animation is not None:
            self._sidebar_animation.stop()
        animation = QPropertyAnimation(self.sidebar, b"maximumWidth", self)
        animation.setDuration(240)
        animation.setEasingCurve(QEasingCurve.InOutCubic)
        animation.setStartValue(current_width)
        animation.setEndValue(0 if collapsing else 272)
        if not collapsing:
            self.sidebar.setMaximumWidth(current_width)
        def finish():
            if collapsing:
                self.sidebar.setVisible(False)
                self.sidebar.setMaximumWidth(292)
            else:
                self.sidebar.setMinimumWidth(236)
                self.sidebar.setMaximumWidth(292)
        animation.finished.connect(finish)
        self._sidebar_animation = animation
        animation.start()

    def _show_model_menu(self, anchor=None):
        if self.busy:
            return
        menu = QMenu(self)
        menu.setMinimumWidth(390)
        remote = self._settings.get("provider") == "remote"
        
        installed = list(getattr(self, "_installed_models", []) or [])
        current = str(getattr(getattr(self.core, "brain", None), "model", "")).strip()
        if current and not remote and current not in installed:
            installed.insert(0, current)

        search_action = QWidgetAction(menu)
        search_box = QLineEdit()
        search_box.setPlaceholderText("Search available models…")
        search_box.setClearButtonEnabled(True)
        search_box.setStyleSheet(f"QLineEdit {{ background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 7px; padding: 7px 9px; min-width: 260px; }}")
        search_action.setDefaultWidget(search_box)
        menu.addAction(search_action)
        menu.addSection("INSTALLED LOCAL MODELS")
        searchable_actions = []
        searchable_groups = []
        for name in sorted(set(installed), key=str.casefold):
            action = menu.addAction(("✓  " if (not remote and name == current) else "    ") + name)
            action.triggered.connect(lambda _, n=name: self._select_model(n))
            searchable_actions.append((action, name))

        try:
            remote_profiles = json.loads(self._settings.get("remote_models", "[]") or "[]")
        except (TypeError, ValueError):
            remote_profiles = []
        remote_profiles = [item for item in remote_profiles if isinstance(item, dict) and item.get("model")]
        if remote_profiles:
            menu.addSection("SAVED REMOTE MODELS")
            active_remote = str(self._settings.get("active_remote_model_id", "") or "")
            for profile in remote_profiles:
                profile_id = str(profile.get("id", ""))
                model_name = str(profile.get("model", ""))
                display_name = str(profile.get("name") or model_name or "Remote model")
                submenu = menu.addMenu(display_name)
                available_remote = list(self._remote_model_catalog.get(profile_id, []) or [])
                if model_name and model_name not in available_remote:
                    available_remote.insert(0, model_name)
                for available_model in available_remote:
                    action = submenu.addAction(
                        ("✓  " if remote and profile_id == active_remote and available_model == model_name else "    ")
                        + available_model
                    )
                    action.triggered.connect(
                        lambda _, pid=profile_id, model=available_model: self._select_remote_model(pid, model)
                    )
                    searchable_actions.append((action, display_name + " " + available_model))
                if not available_remote:
                    action = submenu.addAction("No model catalog available")
                    action.setEnabled(False)
                searchable_groups.append((submenu, display_name, available_remote))
        def filter_model_actions(query):
            needle = query.strip().casefold()
            for action, label in searchable_actions:
                action.setVisible(not needle or needle in label.casefold())
            for submenu, display_name, model_names in searchable_groups:
                group_match = not needle or needle in display_name.casefold() or any(
                    needle in model_name.casefold() for model_name in model_names
                )
                submenu.menuAction().setVisible(group_match)
        search_box.textChanged.connect(filter_model_actions)
        menu.aboutToShow.connect(search_box.setFocus)

        menu.addSeparator()
        effort_action = QWidgetAction(menu)
        effort_panel = QWidget(menu)
        effort_panel.setAttribute(Qt.WA_TranslucentBackground, True)
        effort_panel.setAutoFillBackground(False)
        effort_panel.setStyleSheet("background: transparent; border: none;")
        effort_layout = QVBoxLayout(effort_panel)
        effort_layout.setContentsMargins(14, 8, 14, 12)
        effort_layout.setSpacing(7)
        effort_head = QHBoxLayout()
        effort_title = QLabel("EFFORT")
        effort_title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 800; letter-spacing: 1px;")
        effort_head.addWidget(effort_title)
        effort_head.addStretch(1)
        current_effort = QLabel(EFFORT_LABELS[EFFORT_LEVELS.index(self._effort)])
        current_effort.setStyleSheet(f"color: {ACCENT}; font-weight: 700;")
        effort_head.addWidget(current_effort)
        effort_layout.addLayout(effort_head)
        popup_effort = EffortSelector()
        popup_effort.set_value(self._effort)
        popup_effort.changed.connect(self._on_effort_changed)
        popup_effort.changed.connect(lambda value: current_effort.setText(EFFORT_LABELS[EFFORT_LEVELS.index(value)]))
        popup_effort.changed.connect(lambda value: self.model_selector.setText(self.model_selector.text().rsplit("/", 1)[0].strip() + f"   /   {EFFORT_LABELS[EFFORT_LEVELS.index(value)]}  ▾"))
        effort_layout.addWidget(popup_effort)
        effort_action.setDefaultWidget(effort_panel)
        menu.addAction(effort_action)
        menu.addSeparator()
        menu.addAction("Refresh local models").triggered.connect(self._start_model_discovery)
        menu.addAction("Refresh remote model catalogs").triggered.connect(self._start_remote_model_discovery)
        menu.addAction("API & model settings…").triggered.connect(self._open_model_settings)
        noviqx_label = "NoviqX GitHub App…" + (
            "  ✓" if noviqx_is_configured() else "  (not set up)"
        )
        menu.addAction(noviqx_label).triggered.connect(self._open_noviqx_settings)
        anchor = anchor or self.model_selector
        menu.ensurePolished()
        menu.adjustSize()
        anchor_top = anchor.mapToGlobal(QPoint(0, 0))
        desired = QPoint(anchor_top.x(), anchor_top.y() - menu.sizeHint().height())
        screen = QApplication.screenAt(anchor_top)
        if screen is not None:
            available = screen.availableGeometry()
            x = max(available.left(), min(desired.x(), available.right() - menu.sizeHint().width() + 1))
            y = max(available.top(), desired.y())
            desired = QPoint(x, y)
        menu.exec(desired)

    def _select_remote_model(self, profile_id, model_name=None):
        if self.busy:
            return
        try:
            profiles = json.loads(self._settings.get("remote_models", "[]") or "[]")
        except (TypeError, ValueError):
            profiles = []
        profile = next((item for item in profiles if isinstance(item, dict) and str(item.get("id", "")) == str(profile_id)), None)
        if profile is None:
            return
        if model_name:
            profile["model"] = str(model_name)
            self._settings["remote_models"] = json.dumps(profiles, ensure_ascii=False)
        self._settings["provider"] = "remote"
        self._settings["active_remote_model_id"] = str(profile_id)
        self._settings["api_base_url"] = str(profile.get("base_url", ""))
        self._settings["api_model"] = str(profile.get("model", ""))
        self._settings["api_key"] = str(profile.get("api_key", ""))
        save_settings(self._settings)
        apply_to_environment(self._settings)
        if self._rebuild_core():
            self._refresh_model_labels()
            self._render_current_chat()

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
        dialog = ModelSettingsDialog(self._settings, getattr(self, "_installed_models", []), self)
        if dialog.exec() == QDialog.Accepted:
            values = dialog.values()
            save_settings(values)
            self._settings.update(values)
            self._remote_model_catalog = {}
            apply_to_environment(values)
            if self._rebuild_core():
                self._refresh_model_labels()
            self._render_current_chat()

    def _open_noviqx_settings(self):
        """Re-open the NoviqX setup wizard from the Settings menu.

        Always re-runs the connection test on save, so a user fixing a typo
        (wrong App ID, regenerated .pem) gets immediate confirmation. The
        wizard is opened with allow_dismiss=True for parity with first run,
        though 'Never show this again' from here is effectively a no-op
        because we are already in user-initiated mode.
        """
        from ui.noviqx_setup_wizard import NoviqXSetupWizard
        wizard = NoviqXSetupWizard(self, allow_dismiss=True)
        wizard.exec()

    def _choose_attachments(self):
        if self.busy:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Attach files", "", "All files (*)")
        changed = False
        for path in paths:
            path = os.path.abspath(path)
            if path not in self.attachments:
                self.attachments.append(path)
                changed = True
        if changed:
            self._refresh_attachment_preview()

    def _refresh_attachment_preview(self):
        """Render removable file chips for files waiting to be sent."""
        if not hasattr(self, "attachment_preview_layout"):
            return
        while self.attachment_preview_layout.count():
            item = self.attachment_preview_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.attachment_scroll.setVisible(bool(self.attachments))
        for index, path in enumerate(self.attachments):
            card = QFrame()
            card.setObjectName("attachmentCard")
            card.setFixedSize(132, 96)
            card.setStyleSheet(f"QFrame#attachmentCard {{ background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 10px; }}")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(9, 7, 8, 7)
            layout.setSpacing(3)

            top = QHBoxLayout()
            top.setContentsMargins(0, 0, 0, 0)
            file_icon = QLabel("▤")
            file_icon.setStyleSheet(f"color: {ACCENT}; font-size: 17px; border: none; background: transparent;")
            top.addWidget(file_icon)
            top.addStretch(1)
            remove = QToolButton()
            remove.setText("×")
            remove.setToolTip(f"Remove {os.path.basename(path)}")
            remove.setCursor(Qt.PointingHandCursor)
            remove.setFixedSize(20, 20)
            remove.setStyleSheet(f"QToolButton {{ color: {TEXT_MUTED}; background: transparent; border: none; font-size: 16px; }} QToolButton:hover {{ color: {TEXT}; background: {BORDER}; border-radius: 5px; }}")
            remove.clicked.connect(lambda checked=False, item_path=path: self._remove_attachment(item_path))
            top.addWidget(remove)
            layout.addLayout(top)

            filename = os.path.basename(path) or path
            name = QLabel(filename)
            name.setWordWrap(True)
            name.setMaximumHeight(34)
            name.setStyleSheet(f"color: {TEXT}; font-size: 10px; border: none; background: transparent;")
            name.setToolTip(path)
            layout.addWidget(name)
            try:
                size_text = format_bytes(os.path.getsize(path))
            except OSError:
                size_text = "Unavailable"
            size = QLabel(size_text)
            size.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9px; border: none; background: transparent;")
            layout.addWidget(size)
            self.attachment_preview_layout.addWidget(card)
        self.attachment_preview_layout.addStretch(1)

    def _remove_attachment(self, path):
        if path in self.attachments:
            self.attachments.remove(path)
            self._refresh_attachment_preview()

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
            self._stop_generation()
            return
        user_text = self.input.toPlainText().strip()
        attachments = list(self.attachments)
        if not user_text and not attachments:
            return

        attachment_context = self._attachment_context(attachments) if attachments else ""
        message = f"{user_text}\n\n{attachment_context}" if attachment_context else user_text

        self.input.clear()
        self.attachments.clear()
        self._refresh_attachment_preview()
        created_new_chat = not self.current_chat_id
        if created_new_chat:
            self.current_chat_id = self.chat_store.create_chat()
            self._sync_active_agent_session()
        self._add_message("user", user_text, attachments=attachments)
        self.chat_store.add_message(self.current_chat_id, "user", user_text, attachments=attachments, context=message)
        self._refresh_chat_history()

        self.busy = True
        self.input.setEnabled(False)
        self.send_button.setEnabled(True)
        self.send_button.setText("Stop")
        self.send_button.setIcon(QIcon())
        self.send_button.setFixedSize(58, 32)
        self.send_button.setToolTip("Stop generation")
        self._answer_started = False
        self._set_activity("Thinking")

        self._apply_effort(self._effort)
        self.thinking_enabled = self.think_button.isChecked()
        setter = getattr(self.core, "set_thinking_enabled", None)
        if callable(setter):
            setter(self.thinking_enabled)
        self.think_button.setEnabled(False)
        self.thinking_panel = None
        self._clear_task_plan_panel()
        execution_state = getattr(self.core, "execution_state", None)
        if isinstance(execution_state, dict):
            execution_state["last_plan"] = None
        self._discard_streaming_message()

        self.worker = AgentWorker(
            self.core, message, self,
            generate_title=created_new_chat,
            chat_id=self.current_chat_id,
        )
        self._active_workers.add(self.worker)
        self.worker.status.connect(self._on_status)
        self.worker.title_generated.connect(self._on_chat_title_generated)
        self.worker.completed.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.finished.connect(self._on_worker_thread_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread = self.worker
        self.worker.start()

    def _stop_generation(self):
        worker = self.worker
        if worker is None or not self.busy:
            return
        worker.request_stop()
        self.send_button.setEnabled(False)
        self.send_button.setText("Stopping…")
        self.send_button.setToolTip("Waiting for the active operation to stop safely")
        self._set_activity("Stopping")

    def _on_status(self, message):
        message = str(message)
        if message.startswith("TASK_PLAN:"):
            try:
                plan = json.loads(message[len("TASK_PLAN:"):])
            except (TypeError, ValueError):
                return
            if isinstance(plan, dict) and isinstance(plan.get("steps"), list):
                self._insert_task_plan_panel().set_plan(plan)
            return
        if message.startswith("MODEL_ANSWER_DELTA:"):
            if not self._answer_started:
                self._answer_started = True
                self._set_activity("Writing")
            self._ensure_streaming_message().append_delta(message[len("MODEL_ANSWER_DELTA:"):])
            return
        if message == "MODEL_ANSWER_RESET":
            self._discard_streaming_message()
            return
        if message.startswith("MODEL_THOUGHT_START"):
            self._set_activity("Thinking")
            return
        if message.startswith("MODEL_THOUGHT_DELTA:"):
            thought = message[len("MODEL_THOUGHT_DELTA:"):]
            if thought.strip():
                if self.thinking_enabled and self.thinking_panel is None:
                    self.thinking_panel = self._insert_thinking_panel()
                if self.thinking_panel:
                    self.thinking_panel.append_delta(thought)
            return
        if message == "MODEL_THOUGHT_END":
            if self.thinking_panel:
                self.thinking_panel.finish()
            return
        if message.startswith("ACTIVITY:"):
            self._set_activity(message[len("ACTIVITY:"):].strip() or "Working")
            return
        if message.startswith("THINKING_UPDATE:"):
            # Execution/status events are not model reasoning. Keep them in the
            # status line; the Thinking panel is reserved for Ollama's native
            # message.thinking stream.
            detail = message[len("THINKING_UPDATE:"):].strip()
            phrase = self._friendly_activity(detail)
            if phrase:
                self._set_activity(phrase)
            return
        phrase = self._friendly_activity(message)
        if phrase:
            self._set_activity(phrase)

    def _set_activity(self, text):
        """Show the current phase on the composer chip and keep it animating."""
        if not self.busy:
            # A queued event arrived after the request finished; never
            # resurrect the hidden chip for stale activity.
            return
        text = (text or "").strip() or "Working"
        self._activity_text = text
        self.status_label.setText(text)
        self.status_label.setToolTip(text)
        self.status_row.show()
        self._status_timer.start()
        self._animate_status()

    @staticmethod
    def _friendly_activity(detail):
        """Map legacy status phrases to a calm human activity label.

        Returns an empty string when the message should not disturb the
        current chip text (e.g. the phase-completion "Done" marker).
        """
        text = " ".join(str(detail or "").split())
        if not text:
            return ""
        if text == "Done":
            return ""
        lowered = text.lower()
        if lowered.startswith((
            "thinking",
            "choosing next action",
            "model is choosing",
            "re-evaluating",
            "preparing",
            "search limit reached",
            "tool input preparation",
            "stopping repeated",
            "working",
        )):
            return "Thinking"
        return text[:28]

    def _separate_thinking_panel_from_reply(self):
        """Add breathing room between the native-thinking card and Nova's reply."""
        if not self.thinking_panel:
            return
        self.thinking_panel.finish()
        self.thinking_panel = None
        # The final layout item is the stretch spacer. Insert a real layout
        # gap immediately before it so the next assistant message is separated.
        index = max(0, self.chat_container_layout.count() - 1)
        self.chat_container_layout.insertSpacing(index, 18)

    def _on_chat_title_generated(self, chat_id, title):
        """Persist the title chosen by the configured language model."""
        if not chat_id or not title:
            return
        setter = getattr(self.chat_store, "set_chat_title", None)
        if callable(setter):
            setter(chat_id, title)
            self._refresh_chat_history()

    def _on_finished(self, response):
        self._discard_streaming_message()
        self._separate_thinking_panel_from_reply()
        self._add_message("nova", str(response))
        self.chat_store.add_message(self.current_chat_id, "assistant", str(response))
        self._refresh_chat_history()
        self._finish_request()

    def _on_failed(self, error):
        self._discard_streaming_message()
        self._separate_thinking_panel_from_reply()
        text = f"I hit an internal error.\n\nError: {error}"
        self._add_message("nova", text)
        self.chat_store.add_message(self.current_chat_id, "assistant", text)
        self._refresh_chat_history()
        self._finish_request()

    def _on_cancelled(self):
        self._discard_streaming_message()
        self._separate_thinking_panel_from_reply()
        self._add_message("nova", "Generation stopped.")
        self.chat_store.add_message(self.current_chat_id, "assistant", "Generation stopped.")
        self._refresh_chat_history()
        self._finish_request()

    def _on_worker_thread_finished(self):
        worker = self.sender()
        self._active_workers.discard(worker)
        if self.worker is worker:
            self.worker = None
            self.thread = None

    def _finish_request(self):
        self.busy = False
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.send_button.setText("")
        self.send_button.setIcon(make_icon("arrow_up", BG_MAIN, 17, 2.5))
        self.send_button.setFixedSize(32, 32)
        self.send_button.setToolTip("Send message")
        self.think_button.setEnabled(True)
        self._status_timer.stop()
        self._activity_text = ""
        self._answer_started = False
        self.status_row.hide()
        self.input.setFocus()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    window = NovaWindow()
    window.show()
    # Show the NoviqX setup wizard on first launch if needed. Defer one event
    # loop tick so the main window paints first; the user sees Nova is alive
    # before being asked to configure anything.
    from integrations.noviqx.settings import should_show_wizard
    if should_show_wizard():
        from PySide6.QtCore import QTimer
        QTimer.singleShot(150, lambda: _maybe_show_noviqx_wizard(window))
    sys.exit(app.exec())


def _maybe_show_noviqx_wizard(parent):
    """Open the NoviqX wizard non-modally if still needed at fire time.

    The user may have configured credentials in another Nova instance between
    the schedule and the fire — re-check `should_show_wizard()` before opening.
    """
    try:
        from ui.noviqx_setup_wizard import NoviqXSetupWizard
        from integrations.noviqx.settings import should_show_wizard
        if not should_show_wizard():
            return
        wizard = NoviqXSetupWizard(parent, allow_dismiss=True)
        wizard.exec()
    except Exception:
        # The wizard is a convenience; if Qt or the integration can't start,
        # Nova must still be usable. The error is visible in the terminal.
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()