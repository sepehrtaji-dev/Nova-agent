import sys
import threading
from datetime import datetime

from config.runtime import load_capability_definitions, load_default_access

from PySide6.QtCore import QObject, QPoint, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent.core import NovaCore
from utils.math_parser import format_response_math


APP_BG = "#0b0c0f"
SIDEBAR_BG = "#111318"
PANEL_BG = "#0f1116"
BORDER = "#252a33"
TEXT = "#f5f7fa"
MUTED = "#8d95a3"
ACCENT = "#8b7cff"
ACCENT_HOVER = "#9d91ff"
GREEN = "#5fe09b"

# Default permissions come from the declarative tool manifest.
DEFAULT_ACCESS = load_default_access()
CAPABILITY_DEFINITIONS = load_capability_definitions()


def split_markdown_blocks(text):
    import re

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
        line = lines[i]
        match = re.match(r"^\s*(`{3}|~{3})([^\n]*)$", line)
        if not match:
            prose.append(line)
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


def _render_markdown_text(text):
    import html
    import re

    text = format_response_math(str(text or ""))
    escaped = html.escape(text)
    escaped = re.sub(r"^### (.+)$", lambda m: "<h3>" + m.group(1) + "</h3>", escaped, flags=re.MULTILINE)
    escaped = re.sub(r"^## (.+)$", lambda m: "<h2>" + m.group(1) + "</h2>", escaped, flags=re.MULTILINE)
    escaped = re.sub(r"^# (.+)$", lambda m: "<h1>" + m.group(1) + "</h1>", escaped, flags=re.MULTILINE)
    escaped = re.sub(r"^[-*] (.+)$", lambda m: "• " + m.group(1), escaped, flags=re.MULTILINE)
    escaped = re.sub(r"\*\*(.+?)\*\*", lambda m: "<strong>" + m.group(1) + "</strong>", escaped)
    escaped = re.sub(r"`([^`\n]+)`", lambda m: "<code>" + m.group(1) + "</code>", escaped)
    escaped = escaped.replace("\n", "<br>")
    return escaped

class CodeBlock(QFrame):
    def __init__(self, code, language="", parent=None):
        super().__init__(parent)
        self.setObjectName("codeBlock")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        if language:
            language_label = QLabel(language)
            language_label.setObjectName("codeLanguage")
            language_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            outer.addWidget(language_label)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("codeEditor")
        self.editor.setReadOnly(True)
        self.editor.setPlainText(code)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.editor.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        font = QFont("Cascadia Mono")
        if font.family() != "Cascadia Mono":
            font = QFont("Consolas")
        font.setPointSize(10)
        self.editor.setFont(font)

        line_count = max(1, code.count("\n") + 1)
        line_height = max(18, font.pointSize() + 9)
        editor_height = min(480, max(54, line_count * line_height + 22))
        self.editor.setFixedHeight(editor_height)
        outer.addWidget(self.editor)


class MessageTextBrowser(QTextBrowser):
    """Rich-text message view whose height follows its actual wrapped content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        self.document().setDocumentMargin(0)

    def update_content_height(self):
        width = max(1, self.viewport().width())
        self.document().setTextWidth(width)
        # Include a small rounding allowance so the last line is never clipped.
        height = int(self.document().size().height() + 10)
        self.setFixedHeight(max(24, height))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_content_height()


def add_markdown_content(layout, text):
    for kind, value, language in split_markdown_blocks(text):
        if kind == "code":
            layout.addWidget(CodeBlock(value, language))
            continue
        if not value.strip():
            continue
        body = MessageTextBrowser()
        body.document().setDefaultStyleSheet("""
            body { font-family: "Segoe UI"; font-size: 13px; color: #f5f7fa; }
            h1, h2, h3 { color: #f5f7fa; margin: 8px 0 5px 0; }
            h1 { font-size: 18px; }
            h2 { font-size: 16px; }
            h3 { font-size: 14px; }
            strong { color: #ffffff; }
            code { background: #171b22; color: #d7d2ff; padding: 2px 4px; }
            a { color: #a99fff; }
        """)
        body.setHtml(_render_markdown_text(value))
        body.update_content_height()
        layout.addWidget(body)

def make_avatar(letter="N", size=34):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#1b1e27"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.setPen(QColor("#c8c2ff"))
    painter.setFont(QFont("Segoe UI", max(10, size // 2), QFont.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, letter)
    painter.end()
    return pixmap


def make_icon(kind, color="#aeb5c1", size=20, width=1.8):
    """Crisp vector-drawn icons (no emoji / font glyph differences between PCs)."""
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
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


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
    """Multi-line input: Enter sends, Shift+Enter inserts a new line."""

    submitted = Signal()
    focus_changed = Signal(bool)
    MAX_HEIGHT = 150

    def __init__(self, parent=None):
        super().__init__(parent)
        self.min_height = 44
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setTabChangesFocus(True)
        self.setFrameShape(QFrame.NoFrame)
        self.textChanged.connect(self.fit_height)

    def set_min_height(self, value):
        self.min_height = value
        self.fit_height()

    def fit_height(self):
        # QPlainTextEdit reports its document size in LINES (wrapped lines included),
        # not pixels, so convert with the font's line height.
        lines = max(1, int(round(self.document().size().height())))
        margins = int(self.document().documentMargin() * 2)
        wanted = lines * self.fontMetrics().lineSpacing() + margins + 8
        self.setFixedHeight(max(self.min_height, min(self.MAX_HEIGHT, wanted)))
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if wanted > self.MAX_HEIGHT else Qt.ScrollBarAlwaysOff
        )

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focus_changed.emit(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focus_changed.emit(False)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
            event.modifiers() & Qt.ShiftModifier
        ):
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_height()


class MessageBubble(QFrame):
    def __init__(self, role, text, parent=None):
        super().__init__(parent)
        self.setObjectName("userBubble" if role == "user" else "novaBubble")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 14)
        layout.setSpacing(12)

        avatar = QLabel()
        avatar.setFixedSize(34, 34)
        avatar.setPixmap(make_avatar("Y" if role == "user" else "N", 34))
        avatar.setAlignment(Qt.AlignTop)
        layout.addWidget(avatar, 0, Qt.AlignTop)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(8)

        name = QLabel("You" if role == "user" else "Nova")
        name.setObjectName("messageName")
        content.addWidget(name)
        add_markdown_content(content, text if text else " ")
        layout.addLayout(content, 1)

class ActivityItem(QFrame):
    def __init__(self, message, parent=None):
        super().__init__(parent)
        self.setObjectName("activityItem")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(9)

        dot = QLabel("●")
        dot.setObjectName("activityDot")
        layout.addWidget(dot)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)

        time_label = QLabel(datetime.now().strftime("%H:%M:%S"))
        time_label.setObjectName("activityTime")
        text_layout.addWidget(time_label)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setObjectName("activityText")
        text_layout.addWidget(message_label)

        layout.addLayout(text_layout, 1)


class TurnStatus(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("turnStatus")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(9)

        self.dot = QLabel("●")
        self.dot.setObjectName("turnStatusDot")
        layout.addWidget(self.dot, 0, Qt.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.title = QLabel("Nova")
        self.title.setObjectName("turnStatusTitle")
        text_layout.addWidget(self.title)

        self.message = QLabel("Thinking…")
        self.message.setObjectName("turnStatusMessage")
        self.message.setWordWrap(True)
        text_layout.addWidget(self.message)

        layout.addLayout(text_layout, 1)

    def update_status(self, message):
        self.message.setText(message)


class CapabilityButton(QPushButton):
    changed = Signal(bool)

    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self.title = title
        self.subtitle = subtitle
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(54)
        self.toggled.connect(self._changed)
        self._refresh()

    def _changed(self, value):
        self._refresh()
        self.changed.emit(value)

    def _refresh(self):
        state = "ON" if self.isChecked() else "OFF"
        self.setText(f"{self.title}  ·  {state}\n{self.subtitle}")


class NovaWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.core = NovaCore()
        self.core.set_access(**DEFAULT_ACCESS)
        self.thread = None
        self._autoscroll = True
        self.worker = None
        self.busy = False
        self.current_turn_status = None

        self.setWindowTitle("Nova")
        self.setMinimumSize(980, 600)
        self.resize(1100, 760)

        self._build_ui()
        self._wire_composer_controls()
        self._apply_style()
        self._sync_capabilities()
        self._welcome()
        self._sync_responsive_layout()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar(), 0)

        main = QWidget()
        main.setObjectName("main")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self._build_header(), 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        chat = QWidget()
        chat.setObjectName("chatArea")
        chat_layout = QVBoxLayout(chat)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        self.chat_scroll = QScrollArea()
        self.chat_scroll.setObjectName("chatScroll")
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.NoFrame)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.chat_container = QWidget()
        self.chat_container.setObjectName("chatContainer")
        self.chat_container_layout = QVBoxLayout(self.chat_container)
        self.chat_container_layout.setContentsMargins(42, 30, 42, 24)
        self.chat_container_layout.setSpacing(0)
        self.chat_container_layout.addStretch()

        self.chat_scroll.setWidget(self.chat_container)
        chat_bar = self.chat_scroll.verticalScrollBar()
        chat_bar.rangeChanged.connect(self._on_chat_range_changed)
        chat_bar.valueChanged.connect(self._on_chat_scrolled)
        chat_layout.addWidget(self.chat_scroll, 1)
        chat_layout.addWidget(self._build_composer(), 0)

        self.main_splitter = splitter
        splitter.addWidget(chat)
        self.activity_panel = self._build_activity_panel()
        splitter.addWidget(self.activity_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        main_layout.addWidget(splitter, 1)
        root_layout.addWidget(main, 1)

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        self.sidebar = sidebar

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(12)

        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(make_avatar("N", 36))
        brand.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("Nova")
        title.setObjectName("brandTitle")
        subtitle = QLabel("Local AI Agent")
        subtitle.setObjectName("brandSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        brand.addLayout(title_box)
        brand.addStretch()
        layout.addLayout(brand)

        new_chat = QPushButton("+  New chat")
        new_chat.setObjectName("newChat")
        new_chat.setCursor(Qt.PointingHandCursor)
        new_chat.clicked.connect(self._new_chat)
        layout.addWidget(new_chat)

        label = QLabel("CHATS")
        label.setObjectName("sectionLabel")
        layout.addWidget(label)

        self.chat_list = QListWidget()
        self.chat_list.setObjectName("chatList")
        self.chat_list.setSpacing(3)
        self.chat_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_list.addItem(QListWidgetItem("New conversation"))
        self.chat_list.setMinimumHeight(120)
        self.chat_list.item(0).setSelected(True)
        layout.addWidget(self.chat_list, 1)

        layout.addSpacing(8)

        footer = QFrame()
        footer.setObjectName("sidebarFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(12, 12, 12, 12)
        footer_layout.setSpacing(5)

        model_label = QLabel("LOCAL MODEL")
        model_label.setObjectName("tinyLabel")
        model_name = str(
            getattr(
                getattr(self.core, "brain", None),
                "model",
                "Local model",
            )
        ).strip()
        model_value = QLabel(model_name)
        model_value.setObjectName("modelValue")
        self.sidebar_model_label = model_value
        footer_layout.addWidget(model_label)
        footer_layout.addWidget(model_value)

        privacy = QLabel("●  Local processing")
        privacy.setObjectName("privacy")
        footer_layout.addWidget(privacy)

        layout.addWidget(footer)
        return sidebar

    def _build_header(self):
        header = QFrame()
        header.setObjectName("header")
        self.header = header

        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 0, 18, 0)
        layout.setSpacing(10)

        title = QLabel("Nova")
        title.setObjectName("headerTitle")
        layout.addWidget(title)

        pill = QLabel("LOCAL")
        pill.setObjectName("localPill")
        layout.addWidget(pill, 0, Qt.AlignVCenter)

        layout.addStretch()

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label)

        activity = QPushButton("Activity")
        activity.setObjectName("headerButton")
        activity.setCursor(Qt.PointingHandCursor)
        activity.clicked.connect(self._focus_activity)
        layout.addWidget(activity)

        return header

    def _build_activity_panel(self):
        panel = QFrame()
        panel.setObjectName("activityPanel")
        self.activity_panel = panel

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        title = QLabel("Activity")
        title.setObjectName("panelTitle")
        heading.addWidget(title)
        heading.addStretch()

        self.live_badge = QLabel("IDLE")
        self.live_badge.setObjectName("idleBadge")
        heading.addWidget(self.live_badge)
        layout.addLayout(heading)

        info = QLabel(
            "High-level activity only. Nova's private reasoning is never shown."
        )
        info.setObjectName("panelInfo")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.activity_scroll = QScrollArea()
        self.activity_scroll.setWidgetResizable(True)
        self.activity_scroll.setFrameShape(QFrame.NoFrame)
        self.activity_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.activity_scroll.setObjectName("activityScroll")
        self.activity_scroll.viewport().setAutoFillBackground(False)
        self.activity_container = QWidget()
        self.activity_container.setObjectName("activityContainer")
        self.activity_layout = QVBoxLayout(self.activity_container)
        self.activity_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_layout.setSpacing(5)
        self.activity_layout.addStretch()

        self.activity_scroll.setWidget(self.activity_container)
        layout.addWidget(self.activity_scroll, 1)

        capabilities = QLabel("CAPABILITIES")
        capabilities.setObjectName("sectionLabel")
        layout.addWidget(capabilities)

        self.capability_buttons = {}
        capability_names = dict.fromkeys(
            (*DEFAULT_ACCESS.keys(), *CAPABILITY_DEFINITIONS.keys())
        )
        for capability in capability_names:
            definition = CAPABILITY_DEFINITIONS.get(capability, {})
            label = str(definition.get("label") or capability.replace("_", " ").upper())
            subtitle = str(definition.get("subtitle") or capability.replace("_", " "))
            button = CapabilityButton(label, subtitle)
            button.setToolTip(str(definition.get("description") or f"Toggle {label} capability."))
            button.changed.connect(
                lambda enabled, name=capability: self._set_access(name, enabled)
            )
            button.setAccessibleName(button.title)
            button.setAccessibleDescription(button.subtitle)
            self.capability_buttons[capability] = button
            layout.addWidget(button, 0)

        return panel

    def _build_composer(self):
        wrapper = QFrame()
        wrapper.setObjectName("composerArea")
        self.composer_area = wrapper

        layout = QVBoxLayout(wrapper)
        self.composer_layout = layout
        layout.setContentsMargins(34, 12, 34, 22)
        layout.setSpacing(0)

        # One rounded box holds the text field and the control row (like Ollama's app).
        box = QFrame()
        box.setObjectName("composerBox")
        box.setProperty("focused", False)
        self.composer_box = box
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(18, 12, 12, 12)
        box_layout.setSpacing(8)

        self.input = ComposerEdit()
        self.input.setObjectName("composer")
        self.input.setPlaceholderText("Send a message")
        self.input.submitted.connect(self._send)
        self.input.focus_changed.connect(self._on_composer_focus)
        box_layout.addWidget(self.input)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        size = 38

        add_button = QPushButton()
        add_button.setObjectName("roundButton")
        add_button.setIcon(make_icon("plus", "#aeb5c1"))
        add_button.setIconSize(QSize(20, 20))
        add_button.setFixedSize(size, size)
        add_button.setEnabled(False)
        add_button.setToolTip("Attachments are not available yet.")
        controls.addWidget(add_button)

        self.globe_button = QPushButton()
        self.globe_button.setObjectName("roundButton")
        self.globe_button.setCheckable(True)
        self.globe_button.setCursor(Qt.PointingHandCursor)
        self.globe_button.setIconSize(QSize(20, 20))
        self.globe_button.setFixedSize(size, size)
        controls.addWidget(self.globe_button)

        controls.addStretch(1)

        self.current_model = str(
            getattr(getattr(self.core, "brain", None), "model", "") or "Local model"
        ).strip()
        self.model_selector = QPushButton(self.current_model)
        self.model_selector.setObjectName("modelSelector")
        self.model_selector.setCursor(Qt.PointingHandCursor)
        self.model_selector.setIcon(make_icon("chevron_down", "#aeb5c1", 16))
        self.model_selector.setIconSize(QSize(16, 16))
        self.model_selector.setLayoutDirection(Qt.RightToLeft)  # chevron on the right
        self.model_selector.setFixedHeight(size)
        self.model_selector.setMinimumWidth(130)
        self.model_selector.setToolTip("Choose which installed Ollama model Nova uses.")
        self.model_selector.clicked.connect(self._show_model_menu)
        controls.addWidget(self.model_selector)

        self.send_button = QPushButton()
        self.send_button.setObjectName("sendButton")
        self.send_button.setIcon(make_icon("arrow_up", "#ffffff", 20, 2.2))
        self.send_button.setIconSize(QSize(20, 20))
        self.send_button.setFixedSize(size, size)
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setToolTip("Send (Enter)")
        self.send_button.clicked.connect(self._send)
        controls.addWidget(self.send_button)

        box_layout.addLayout(controls)
        layout.addWidget(box)
        return wrapper

    def _wire_composer_controls(self):
        """Connect the globe control to the configured web capability when present."""
        web_button = self.capability_buttons.get("web")
        if web_button is None:
            self.globe_button.setEnabled(False)
        else:
            self.globe_button.toggled.connect(web_button.setChecked)
            web_button.toggled.connect(self.globe_button.setChecked)
        self.globe_button.toggled.connect(self._refresh_globe)
        self._refresh_globe()

    def _refresh_globe(self, *_):
        on = self.globe_button.isChecked()
        self.globe_button.setIcon(make_icon("globe", "#7fb2ff" if on else "#747d8b"))
        self.globe_button.setToolTip(
            "Web search is ON (click to turn off)" if on else "Web search is OFF (click to turn on)"
        )

    def _on_composer_focus(self, focused):
        self.composer_box.setProperty("focused", bool(focused))
        self.composer_box.style().unpolish(self.composer_box)
        self.composer_box.style().polish(self.composer_box)

    def _installed_models(self):
        """Names of models installed in Ollama; falls back to the current one."""
        names = []
        try:
            import ollama

            data = ollama.list()
            items = data.get("models", []) if isinstance(data, dict) else getattr(data, "models", [])
            for item in items or []:
                if isinstance(item, dict):
                    name = item.get("model") or item.get("name")
                else:
                    name = getattr(item, "model", None) or getattr(item, "name", None)
                if name:
                    names.append(str(name))
        except Exception:
            pass
        if self.current_model and self.current_model not in names:
            names.insert(0, self.current_model)
        return sorted(set(names), key=str.lower)

    def _build_model_menu(self):
        menu = QMenu(self)
        for name in self._installed_models():
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == self.current_model)
            action.triggered.connect(lambda _checked=False, n=name: self._select_model(n))
        return menu

    def _show_model_menu(self):
        if self.busy:
            return
        menu = self._build_model_menu()
        button = self.model_selector
        menu.adjustSize()
        # Open upwards, aligned to the button's right edge (the composer sits at the bottom).
        point = button.mapToGlobal(QPoint(button.width() - menu.sizeHint().width(), -menu.sizeHint().height() - 6))
        menu.exec(point)

    def _select_model(self, name):
        if self.busy or not name or name == self.current_model:
            return
        self.current_model = name
        brain = getattr(self.core, "brain", None)
        if brain is not None:
            brain.model = name
        self.model_selector.setText(name)
        if hasattr(self, "sidebar_model_label"):
            self.sidebar_model_label.setText(name)
        self._add_activity(f"Model switched to {name}.")

    def _welcome(self):
        model_name = str(
            getattr(
                getattr(self.core, "brain", None),
                "model",
                "the configured local model",
            )
        ).strip()
        self._add_message(
            "nova",
            "## Welcome to Nova\n\n"
            f"I'm your local AI agent running through Ollama with **{model_name}**.\n\n"
            "I can reason about tasks, use enabled tools, inspect real results, "
            "and continue until the task is complete."
        )
        self._add_activity("Nova is ready.")

    def _apply_style(self):
        self.setStyleSheet(f"""
        * {{
            font-family: "Segoe UI";
            color: {TEXT};
        }}

        QMainWindow, #root, #main {{
            background: {APP_BG};
        }}

        #activityScroll, #activityScroll > QWidget > QWidget, #activityContainer,
        #chatScroll, #chatScroll > QWidget > QWidget, #chatContainer {{
            background: transparent;
            border: none;
        }}

        #sidebar {{
            background: {SIDEBAR_BG};
            border-right: 1px solid {BORDER};
        }}

        #brandTitle {{
            font-size: 17px;
            font-weight: 650;
        }}

        #brandSubtitle {{
            color: {MUTED};
            font-size: 11px;
        }}

        #newChat {{
            background: #1a1d24;
            border: 1px solid {BORDER};
            border-radius: 10px;
            padding: 10px 12px;
            text-align: left;
            font-size: 13px;
            font-weight: 600;
        }}

        #newChat:hover {{
            background: #1d2129;
            border-color: #343a46;
        }}

        #sectionLabel, #tinyLabel {{
            color: #68707e;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1.2px;
        }}

        #chatList {{
            background: transparent;
            border: none;
            outline: none;
            padding: 0;
        }}

        #chatList::item {{
            color: #aeb5c1;
            padding: 9px 10px;
            border-radius: 8px;
        }}

        #chatList::item:hover {{
            background: #171a21;
            color: {TEXT};
        }}

        #chatList::item:selected {{
            background: #1c2029;
            color: {TEXT};
        }}

        #sidebarFooter {{
            background: #15181f;
            border: 1px solid {BORDER};
            border-radius: 11px;
        }}

        #modelValue {{
            font-size: 12px;
            font-weight: 600;
        }}

        #privacy {{
            color: {GREEN};
            font-size: 10px;
            margin-top: 3px;
        }}

        #header {{
            background: {APP_BG};
            border-bottom: 1px solid {BORDER};
        }}

        #headerTitle {{
            font-size: 15px;
            font-weight: 650;
        }}

        #localPill {{
            color: #aaa3ff;
            background: #1a1828;
            border: 1px solid #302b49;
            border-radius: 6px;
            padding: 3px 7px;
            font-size: 9px;
            font-weight: 700;
        }}

        #statusLabel {{
            color: {MUTED};
            font-size: 12px;
            margin-right: 6px;
        }}

        #headerButton {{
            background: transparent;
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 7px 11px;
            color: #b8bec8;
        }}

        #headerButton:hover {{
            background: #171a21;
            color: {TEXT};
        }}

        #activityPanel {{
            background: {PANEL_BG};
            border-left: 1px solid {BORDER};
        }}

        #panelTitle {{
            font-size: 14px;
            font-weight: 650;
        }}

        #panelInfo {{
            color: {MUTED};
            font-size: 10px;
            line-height: 1.3;
        }}

        #idleBadge, #liveBadge {{
            background: #161a20;
            color: #747d8b;
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 3px 6px;
            font-size: 9px;
            font-weight: 700;
        }}

        #turnStatus {{
            background: #12151b;
            border: 1px solid #262b34;
            border-radius: 10px;
        }}

        #turnStatusDot {{
            color: #8b7cff;
            font-size: 9px;
        }}

        #turnStatusTitle {{
            color: #8b7cff;
            font-size: 10px;
            font-weight: 700;
        }}

        #turnStatusMessage {{
            color: #b8bec8;
            font-size: 11px;
        }}

        #activityItem {{
            background: #14171d;
            border: 1px solid #20242c;
            border-radius: 9px;
        }}

        #activityDot {{
            color: {ACCENT};
            font-size: 9px;
        }}

        #activityTime {{
            color: #646c79;
            font-size: 9px;
        }}

        #activityText {{
            color: #b8bec8;
            font-size: 10px;
        }}

        #composerArea {{
            background: {APP_BG};
            border-top: none;
        }}

        #composerBox {{
            background: #15181f;
            border: 1px solid #2a2f39;
            border-radius: 22px;
        }}

        #composerBox[focused="true"] {{
            border-color: #514a72;
        }}

        #composer {{
            background: transparent;
            border: none;
            padding: 2px 2px;
            font-size: 14px;
            selection-background-color: #4a426f;
        }}

        #roundButton {{
            background: #1e222b;
            border: none;
            border-radius: 19px;
        }}

        #roundButton:hover {{
            background: #262b36;
        }}

        #roundButton:checked {{
            background: #1a2438;
        }}

        #roundButton:disabled {{
            background: #191c23;
        }}

        #modelSelector {{
            background: #1e222b;
            color: {TEXT};
            border: none;
            border-radius: 19px;
            padding: 0 16px;
            font-size: 12px;
            font-weight: 600;
        }}

        #modelSelector:hover {{
            background: #262b36;
        }}

        #sendButton {{
            background: {ACCENT};
            border: none;
            border-radius: 19px;
        }}

        #sendButton:hover {{
            background: {ACCENT_HOVER};
        }}

        #sendButton:disabled {{
            background: #2a2833;
        }}

        QMenu {{
            background: #15181f;
            border: 1px solid #2a2f39;
            border-radius: 10px;
            padding: 6px;
        }}

        QMenu::item {{
            padding: 8px 26px 8px 14px;
            border-radius: 6px;
            color: {TEXT};
            font-size: 12px;
        }}

        QMenu::item:selected {{
            background: #222733;
        }}

        QMenu::indicator {{
            width: 0px;
        }}

        QMenu::item:checked {{
            color: {ACCENT_HOVER};
            font-weight: 700;
        }}

        #chatArea, #chatScroll, #chatContainer, QScrollArea#chatScroll QWidget#qt_scrollarea_viewport {{
            background: {APP_BG};
            border: none;
        }}

        #messageName {{
            color: #aeb5c1;
            font-size: 11px;
            font-weight: 650;
        }}

        #userMessage, #novaMessage {{
            background: transparent;
            border: none;
            color: {TEXT};
            font-size: 13px;
        }}

        #userMessage {{
            color: #d9dde4;
        }}

        #codeBlock {{
            background: #10131a;
            border: 1px solid #292f3a;
            border-radius: 10px;
        }}

        #codeLanguage {{
            background: #151922;
            color: #858e9d;
            border-bottom: 1px solid #292f3a;
            padding: 6px 10px;
            font-size: 10px;
            font-weight: 650;
        }}

        #codeEditor {{
            background: #10131a;
            color: #e6e9ef;
            border: none;
            padding: 11px;
            selection-background-color: #343047;
            selection-color: #ffffff;
        }}

        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 2px;
        }}

        QScrollBar::handle:vertical {{
            background: #2a2f38;
            border-radius: 4px;
            min-height: 35px;
        }}

        QScrollBar::handle:vertical:hover {{
            background: #383f4b;
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}

        QSplitter::handle {{
            background: {BORDER};
        }}
        """)

    def _sync_responsive_layout(self):
        width = max(980, self.width())
        height = max(640, self.height())

        sidebar_width = max(220, min(280, int(width * 0.19)))
        activity_width = max(260, min(340, int(width * 0.225)))

        if width < 1180:
            activity_width = max(260, int(width * 0.24))
        elif width > 1600:
            activity_width = min(340, int(width * 0.21))

        self.sidebar.setFixedWidth(sidebar_width)
        self.activity_panel.setMinimumWidth(activity_width)
        self.activity_panel.setMaximumWidth(activity_width)

        available_main = max(1, width - sidebar_width)
        if self.activity_panel.isVisible():
            chat_width = max(1, available_main - activity_width)
            self.main_splitter.setSizes([chat_width, activity_width])
        else:
            chat_width = available_main

        side_pad = max(12, min(20, int(sidebar_width * 0.06)))
        self._set_layout_margins(
            self.sidebar.layout(),
            side_pad,
            max(12, int(height * 0.018)),
            side_pad,
            max(12, int(height * 0.018)),
        )

        self.header.setFixedHeight(max(58, min(72, int(height * 0.082))))

        chat_margin_x = max(24, min(64, int(chat_width * 0.055)))
        self.chat_container_layout.setContentsMargins(
            chat_margin_x,
            max(20, min(34, int(height * 0.035))),
            chat_margin_x,
            max(18, min(28, int(height * 0.03))),
        )

        composer_x = max(20, min(44, int(chat_width * 0.045)))
        self.composer_layout.setContentsMargins(
            composer_x,
            max(10, min(16, int(height * 0.018))),
            composer_x,
            max(16, min(24, int(height * 0.026))),
        )

        self.input.set_min_height(30)

        capability_height = max(48, min(58, int(height * 0.067)))
        for button in self.capability_buttons.values():
            button.setFixedHeight(capability_height)

        self._refresh_capability_styles()

    @staticmethod
    def _set_layout_margins(layout, left, top, right, bottom):
        layout.setContentsMargins(left, top, right, bottom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "main_splitter"):
            self._sync_responsive_layout()

    def _sync_capabilities(self):
        access = self.core.get_access()
        for capability, button in self.capability_buttons.items():
            button.blockSignals(True)
            button.setChecked(access.get(capability, DEFAULT_ACCESS.get(capability, False)))
            button.blockSignals(False)
            button._refresh()

        web_button = self.capability_buttons.get("web")
        self.globe_button.blockSignals(True)
        self.globe_button.setChecked(web_button.isChecked() if web_button else False)
        self.globe_button.blockSignals(False)
        self._refresh_globe()
        self._refresh_capability_styles()

    def _refresh_capability_styles(self):
        for button in self.capability_buttons.values():
            if button.isChecked():
                button.setStyleSheet(
                    """
                    QPushButton {
                        text-align: left;
                        background: #171b21;
                        border: 1px solid #303641;
                        border-radius: 11px;
                        padding: 7px 12px;
                        color: #e5e8ee;
                        font-size: 10px;
                        font-weight: 650;
                    }
                    QPushButton:hover {
                        background: #1c2028;
                        border-color: #3c4350;
                    }
                    """
                )
            else:
                button.setStyleSheet(
                    """
                    QPushButton {
                        text-align: left;
                        background: #111318;
                        border: 1px solid #20242b;
                        border-radius: 11px;
                        padding: 7px 12px;
                        color: #747d8b;
                        font-size: 10px;
                        font-weight: 650;
                    }
                    QPushButton:hover {
                        background: #15181e;
                    }
                    """
                )

    def _set_access(self, name, value):
        self.core.set_access(**{name: value})
        self._refresh_capability_styles()
        self._add_activity(
            f"{name.upper()} access {'enabled' if value else 'disabled'}."
        )

    def _new_chat(self):
        if self.busy:
            return

        access = self.core.get_access() if self.core else dict(DEFAULT_ACCESS)
        self.core = NovaCore()
        restored_access = {
            capability: access.get(capability, default)
            for capability, default in DEFAULT_ACCESS.items()
        }
        restored_access.update({
            capability: enabled
            for capability, enabled in access.items()
            if capability not in restored_access
        })
        self.core.set_access(**restored_access)

        if getattr(self, "current_model", None):
            self.core.brain.model = self.current_model

        while self.chat_container_layout.count():
            item = self.chat_container_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.chat_container_layout.addStretch()

        while self.activity_layout.count():
            item = self.activity_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.activity_layout.addStretch()
        self.current_turn_status = None
        self._sync_capabilities()
        self._welcome()
        self.status_label.setText("Ready")
        self.input.setFocus()

    def _add_message(self, role, text):
        stretch = self.chat_container_layout.takeAt(
            self.chat_container_layout.count() - 1
        )

        bubble = MessageBubble(role, text)
        self.chat_container_layout.addWidget(bubble)

        if stretch:
            self.chat_container_layout.addItem(stretch)

        self._scroll_chat()

    def _add_turn_status(self, message):
        stretch = self.chat_container_layout.takeAt(
            self.chat_container_layout.count() - 1
        )

        status = TurnStatus()
        status.update_status(message)
        self.chat_container_layout.addWidget(status)

        if stretch:
            self.chat_container_layout.addItem(stretch)

        self._scroll_chat()
        return status

    def _add_activity(self, message):
        stretch = self.activity_layout.takeAt(
            self.activity_layout.count() - 1
        )

        item = ActivityItem(message)
        self.activity_layout.addWidget(item)

        if stretch:
            self.activity_layout.addItem(stretch)

        self._scroll_activity()

    def _scroll_chat(self):
        self._autoscroll = True
        QTimer.singleShot(0, self._chat_to_bottom)
        QTimer.singleShot(80, self._chat_to_bottom)

    def _chat_to_bottom(self):
        if self._autoscroll:
            bar = self.chat_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _on_chat_range_changed(self, _minimum, _maximum):
        # Content height changes after layout (wrapped text); keep following the end.
        self._chat_to_bottom()

    def _on_chat_scrolled(self, value):
        bar = self.chat_scroll.verticalScrollBar()
        # If the user scrolls up to read, stop auto-following until the next message.
        self._autoscroll = value >= bar.maximum() - 24

    def _scroll_activity(self):
        QTimer.singleShot(0, self._activity_to_bottom)

    def _activity_to_bottom(self):
        bar = self.activity_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _focus_activity(self):
        """Show or hide the Activity / Capabilities panel."""
        self.activity_panel.setVisible(not self.activity_panel.isVisible())
        self._sync_responsive_layout()
        if self.activity_panel.isVisible():
            self._scroll_activity()

    def _send(self):
        if self.busy:
            return

        message = self.input.toPlainText().strip()
        if not message:
            return

        self.input.clear()
        self._add_message("user", message)
        self._add_activity("Request received.")
        self.current_turn_status = self._add_turn_status("Thinking…")
        self.status_label.setText("Working…")
        self.live_badge.setText("LIVE")
        self.live_badge.setStyleSheet(
            f"""
            background: #16221b;
            color: {GREEN};
            border: 1px solid #294936;
            border-radius: 6px;
            padding: 3px 6px;
            font-size: 9px;
            font-weight: 700;
            """
        )

        self.busy = True
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.worker = AgentWorker(self.core, message)
        self.worker.status.connect(self._on_status)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)

        # Daemon thread: a long model call can never keep the app alive after the
        # window is closed (a QThread would crash with "destroyed while running").
        self.thread = threading.Thread(target=self.worker.run, daemon=True)
        self.thread.start()

    def _on_status(self, message):
        self.status_label.setText(message)
        self._add_activity(message)
        if getattr(self, "current_turn_status", None):
            self.current_turn_status.update_status(message)

    def _on_finished(self, response):
        self._add_message("nova", response)
        self._finish_request("Done")

    def _on_failed(self, error):
        self._add_message(
            "nova",
            "I hit an internal error while processing that request.\n\n"
            f"Error: {error}"
        )
        self._add_activity(f"Error: {error}")
        self._finish_request("Error")

    def _finish_request(self, status):
        # Turn status is temporary progress UI, not a permanent chat message.
        if getattr(self, "current_turn_status", None):
            item = self.chat_container_layout.indexOf(self.current_turn_status)
            if item >= 0:
                self.chat_container_layout.takeAt(item)
            self.current_turn_status.deleteLater()
            self.current_turn_status = None
        self.busy = False
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self._refresh_capability_styles()
        self._sync_capabilities()
        self.status_label.setText(status)
        self.live_badge.setText("IDLE")
        self.live_badge.setStyleSheet(
            """
            background: #161a20;
            color: #747d8b;
            border: 1px solid #252a33;
            border-radius: 6px;
            padding: 3px 6px;
            font-size: 9px;
            font-weight: 700;
            """
        )
        self.input.setFocus()
        self.worker = None
        self.thread = None

    def closeEvent(self, event):
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Nova")
    app.setOrganizationName("Nova")
    app.setFont(QFont("Segoe UI", 10))

    window = NovaWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()