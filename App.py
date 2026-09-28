import sys
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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


APP_BG = "#0b0c0f"
SIDEBAR_BG = "#111318"
PANEL_BG = "#0f1116"
BORDER = "#252a33"
TEXT = "#f5f7fa"
MUTED = "#8d95a3"
ACCENT = "#8b7cff"
ACCENT_HOVER = "#9d91ff"
GREEN = "#5fe09b"


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

    escaped = html.escape(str(text or ""))
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
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        font = QFont("Cascadia Mono")
        if font.family() != "Cascadia Mono":
            font = QFont("Consolas")
        font.setPointSize(10)
        self.editor.setFont(font)

        line_count = max(1, code.count("\\n") + 1)
        line_height = max(18, font.pointSize() + 9)
        editor_height = min(480, max(54, line_count * line_height + 22))
        self.editor.setFixedHeight(editor_height)
        outer.addWidget(self.editor)


def add_markdown_content(layout, text):
    for kind, value, language in split_markdown_blocks(text):
        if kind == "code":
            layout.addWidget(CodeBlock(value, language))
            continue
        if not value.strip():
            continue
        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setFrameShape(QFrame.NoFrame)
        body.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        body.setHtml(_render_markdown_text(value))
        body.document().setDocumentMargin(0)
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
        self.thread = None
        self.worker = None
        self.busy = False
        self.current_turn_status = None

        self.setWindowTitle("Nova")
        self.setMinimumSize(1120, 720)
        self.resize(1400, 860)

        self._build_ui()
        self._apply_style()
        self._sync_capabilities()
        self._welcome()

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
        chat_layout = QVBoxLayout(chat)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.NoFrame)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.chat_container = QWidget()
        self.chat_container_layout = QVBoxLayout(self.chat_container)
        self.chat_container_layout.setContentsMargins(42, 30, 42, 24)
        self.chat_container_layout.setSpacing(0)
        self.chat_container_layout.addStretch()

        self.chat_scroll.setWidget(self.chat_container)
        chat_layout.addWidget(self.chat_scroll, 1)
        chat_layout.addWidget(self._build_composer(), 0)

        splitter.addWidget(chat)
        splitter.addWidget(self._build_activity_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1060, 310])

        main_layout.addWidget(splitter, 1)
        root_layout.addWidget(main, 1)

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(260)

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
        model_value = QLabel("Qwen 2.5 · 3B")
        model_value.setObjectName("modelValue")
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
        header.setFixedHeight(70)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 0, 18, 0)
        layout.setSpacing(10)

        title = QLabel("Nova")
        title.setObjectName("headerTitle")
        layout.addWidget(title)

        pill = QLabel("LOCAL")
        pill.setObjectName("localPill")
        layout.addWidget(pill)

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
        panel.setMinimumWidth(290)
        panel.setMaximumWidth(330)

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

        self.activity_container = QWidget()
        self.activity_layout = QVBoxLayout(self.activity_container)
        self.activity_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_layout.setSpacing(5)
        self.activity_layout.addStretch()

        self.activity_scroll.setWidget(self.activity_container)
        layout.addWidget(self.activity_scroll, 1)

        capabilities = QLabel("CAPABILITIES")
        capabilities.setObjectName("sectionLabel")
        layout.addWidget(capabilities)

        self.web_button = CapabilityButton("WEB SEARCH", "Public web access")
        self.web_button.setToolTip("Allow Nova to use public web search.")
        self.git_button = CapabilityButton("GIT", "Repository operations")
        self.git_button.setToolTip("Allow Nova to use Git repository operations.")
        self.pc_button = CapabilityButton("PC USE", "Terminal + files")
        self.pc_button.setToolTip("Allow Nova to use terminal and filesystem tools.")

        self.web_button.changed.connect(lambda v: self._set_access("web", v))
        self.git_button.changed.connect(lambda v: self._set_access("git", v))
        self.pc_button.changed.connect(lambda v: self._set_access("pc", v))

        for button in (self.web_button, self.git_button, self.pc_button):
            button.setAccessibleName(button.title)
            button.setAccessibleDescription(button.subtitle)

        layout.addWidget(self.web_button, 0)
        layout.addWidget(self.git_button, 0)
        layout.addWidget(self.pc_button, 0)

        return panel

    def _build_composer(self):
        wrapper = QFrame()
        wrapper.setObjectName("composerArea")

        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(34, 14, 34, 22)
        layout.setSpacing(10)

        self.input = QLineEdit()
        self.input.setObjectName("composer")
        self.input.setPlaceholderText("Message Nova...")
        self.input.setFixedHeight(52)
        self.input.returnPressed.connect(self._send)
        layout.addWidget(self.input, 1)

        self.send_button = QPushButton("↑")
        self.send_button.setObjectName("sendButton")
        self.send_button.setFixedSize(52, 52)
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.clicked.connect(self._send)
        layout.addWidget(self.send_button)

        return wrapper

    def _welcome(self):
        self._add_message(
            "nova",
            "## Welcome to Nova\n\n"
            "I'm your local AI agent powered by **Qwen 2.5 3B** through Ollama.\n\n"
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
            border-top: 1px solid {BORDER};
        }}

        #composer {{
            background: #15181f;
            border: 1px solid #2b3039;
            border-radius: 15px;
            padding: 0 16px;
            font-size: 13px;
            selection-background-color: #4a426f;
        }}

        #composer:focus {{
            border-color: #514a72;
        }}

        #sendButton {{
            background: {ACCENT};
            color: #0b0c0f;
            border: none;
            border-radius: 14px;
            font-size: 23px;
            font-weight: 700;
        }}

        #sendButton:hover {{
            background: {ACCENT_HOVER};
        }}

        #sendButton:disabled {{
            background: #292733;
            color: #666172;
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

    def _sync_capabilities(self):
        access = self.core.get_access()

        self.web_button.blockSignals(True)
        self.git_button.blockSignals(True)
        self.pc_button.blockSignals(True)

        self.web_button.setChecked(access.get("web", True))
        self.git_button.setChecked(access.get("git", True))
        self.pc_button.setChecked(access.get("pc", True))

        self.web_button.blockSignals(False)
        self.git_button.blockSignals(False)
        self.pc_button.blockSignals(False)

        self._refresh_capability_styles()

    def _refresh_capability_styles(self):
        for button in (self.web_button, self.git_button, self.pc_button):
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
                        min-height: 54px;
                        max-height: 54px;
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
        kwargs = {"web": None, "git": None, "pc": None}
        kwargs[name] = value
        self.core.set_access(**kwargs)
        self._refresh_capability_styles()
        self._add_activity(
            f"{name.upper()} access {'enabled' if value else 'disabled'}."
        )

    def _new_chat(self):
        if self.busy:
            return

        self.core = NovaCore()

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
        bar = self.chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _scroll_activity(self):
        bar = self.activity_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _focus_activity(self):
        self.activity_scroll.setFocus()
        self._scroll_activity()

    def _send(self):
        if self.busy:
            return

        message = self.input.text().strip()
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
        self.thread = QThread()
        self.worker = AgentWorker(self.core, message)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.status.connect(self._on_status)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)

        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._thread_cleanup)

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
        if getattr(self, "current_turn_status", None):
            self.current_turn_status.update_status(status)
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

    def _thread_cleanup(self):
        if self.worker:
            self.worker.deleteLater()
        if self.thread:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None


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
