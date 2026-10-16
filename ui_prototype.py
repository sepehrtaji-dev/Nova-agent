"""Nova minimalist desktop UI prototype.

This is a visual prototype only. It deliberately does not instantiate NovaCore
or claim that demo controls execute real tools. The production App.py and all
terminal interfaces remain untouched while the layout is evaluated.

Run with: python ui_prototype.py
Requires: PySide6
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)


BG = "#212121"
SIDEBAR = "#171717"
PANEL = "#2b2b2b"
PANEL_HOVER = "#333333"
BORDER = "#3a3a3a"
TEXT = "#f3f3f3"
MUTED = "#a1a1aa"
ACCENT = "#8b7cff"
GREEN = "#55c78a"


class Pill(QLabel):
    def __init__(self, text: str, color: str = MUTED, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            f"color:{color}; background:#252525; border:1px solid {BORDER};"
            "border-radius:10px; padding:5px 9px; font-size:11px;"
        )


class ChatMessage(QFrame):
    def __init__(self, role: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("message")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(12)

        avatar = QLabel("S" if role == "You" else "✳")
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            f"background:{'#3a3a3a' if role == 'You' else '#332b55'};"
            f"color:{'#ffffff' if role == 'You' else ACCENT};"
            "border-radius:15px; font-weight:700;"
        )
        layout.addWidget(avatar, 0, Qt.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(5)
        name = QLabel(role)
        name.setStyleSheet("font-weight:650; color:#f5f5f5; font-size:13px;")
        content = QLabel(text)
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.setStyleSheet("font-size:14px; color:#dedede; line-height:1.45;")
        body.addWidget(name)
        body.addWidget(content)
        layout.addLayout(body, 1)


class ToolRow(QFrame):
    def __init__(self, title: str, description: str, enabled: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("toolRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(11, 10, 10, 10)
        row.setSpacing(9)
        icon = QLabel("◈")
        icon.setFixedWidth(22)
        icon.setStyleSheet(f"color:{ACCENT}; font-size:16px;")
        row.addWidget(icon)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(title)
        name.setStyleSheet("font-size:12px; font-weight:600;")
        detail = QLabel(description)
        detail.setWordWrap(True)
        detail.setStyleSheet(f"font-size:10px; color:{MUTED};")
        text_col.addWidget(name)
        text_col.addWidget(detail)
        row.addLayout(text_col, 1)
        state = QLabel("Enabled" if enabled else "Optional")
        state.setStyleSheet(
            f"font-size:10px; color:{GREEN if enabled else MUTED};"
        )
        row.addWidget(state, 0, Qt.AlignRight | Qt.AlignVCenter)


class NovaPrototype(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nova — UI Prototype")
        self.resize(1380, 880)
        self.setMinimumSize(980, 650)
        self.setStyleSheet(f"""
            * {{ font-family: 'Segoe UI', sans-serif; color: {TEXT}; }}
            QMainWindow, QWidget#root {{ background:{BG}; }}
            QWidget#sidebar {{ background:{SIDEBAR}; border-right:1px solid #292929; }}
            QLabel#brand {{ font-size:20px; font-weight:750; }}
            QLabel#subbrand {{ font-size:11px; color:{MUTED}; }}
            QPushButton {{ border:1px solid transparent; border-radius:9px;
                padding:9px 11px; text-align:left; background:transparent; }}
            QPushButton:hover {{ background:{PANEL_HOVER}; }}
            QPushButton#newChat {{ background:#f2f2f2; color:#171717;
                font-weight:650; padding:11px 12px; }}
            QPushButton#newChat:hover {{ background:#ffffff; }}
            QLabel#section {{ color:#888888; font-size:10px; font-weight:700;
                letter-spacing:1px; padding-top:12px; }}
            QListWidget {{ background:transparent; border:none; outline:none; }}
            QListWidget::item {{ padding:10px 9px; border-radius:8px;
                color:#c6c6c6; margin:1px 0; }}
            QListWidget::item:hover {{ background:#262626; }}
            QListWidget::item:selected {{ background:#2c2c2c; color:white; }}
            QFrame#topbar {{ background:{BG}; border-bottom:1px solid #303030; }}
            QLabel#pageTitle {{ font-size:14px; font-weight:650; }}
            QFrame#toolPanel {{ background:#1c1c1c; border-left:1px solid #303030; }}
            QFrame#toolRow {{ background:#242424; border:1px solid #343434;
                border-radius:10px; }}
            QFrame#composer {{ background:#2b2b2b; border:1px solid #454545;
                border-radius:18px; }}
            QLineEdit {{ background:transparent; border:none; padding:8px 4px;
                font-size:14px; selection-background-color:{ACCENT}; }}
            QPushButton#send {{ background:#f5f5f5; color:#111111;
                border-radius:17px; font-size:17px; font-weight:700;
                padding:0; text-align:center; }}
            QPushButton#send:hover {{ background:#ffffff; }}
            QScrollArea {{ background:transparent; border:none; }}
            QScrollBar:vertical {{ background:transparent; width:7px; }}
            QScrollBar::handle:vertical {{ background:#454545; border-radius:3px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)

        root = QWidget()
        root.setObjectName("root")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(root)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(235)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(13, 18, 13, 14)
        side.setSpacing(8)

        brand = QLabel("✳  Nova")
        brand.setObjectName("brand")
        side.addWidget(brand)
        subbrand = QLabel("AI agent · UI prototype")
        subbrand.setObjectName("subbrand")
        side.addWidget(subbrand)
        side.addSpacing(12)

        new_chat = QPushButton("＋   New chat")
        new_chat.setObjectName("newChat")
        side.addWidget(new_chat)

        section = QLabel("RECENT")
        section.setObjectName("section")
        side.addWidget(section)
        chats = QListWidget()
        chats.addItems([
            "Review Python project", "Explain a codebase",
            "Research AI models", "Fix a test failure",
        ])
        chats.setCurrentRow(0)
        side.addWidget(chats, 1)

        side.addSpacing(8)
        model_card = QFrame()
        model_card.setStyleSheet(
            f"background:#222222; border:1px solid {BORDER}; border-radius:12px;"
        )
        mc = QVBoxLayout(model_card)
        mc.setContentsMargins(12, 11, 12, 11)
        mc.setSpacing(5)
        local = QLabel("MODEL")
        local.setStyleSheet(f"color:{MUTED}; font-size:10px; font-weight:700;")
        model = QLabel("Configured model")
        model.setStyleSheet("font-size:12px; font-weight:650;")
        note = QLabel("Prototype · not connected")
        note.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        mc.addWidget(local)
        mc.addWidget(model)
        mc.addWidget(note)
        side.addWidget(model_card)
        outer.addWidget(sidebar)

        center = QWidget()
        center_col = QVBoxLayout(center)
        center_col.setContentsMargins(0, 0, 0, 0)
        center_col.setSpacing(0)

        top = QFrame()
        top.setObjectName("topbar")
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(22, 0, 22, 0)
        top_row.setSpacing(10)
        title = QLabel("New conversation")
        title.setObjectName("pageTitle")
        top_row.addWidget(title)
        top_row.addStretch()
        prototype_badge = Pill("VISUAL PROTOTYPE", ACCENT)
        top_row.addWidget(prototype_badge)
        center_col.addWidget(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        messages_root = QWidget()
        messages = QVBoxLayout(messages_root)
        messages.setContentsMargins(0, 28, 0, 30)
        messages.setSpacing(0)
        messages.addStretch(1)

        welcome = QLabel("What can I help with?")
        welcome.setAlignment(Qt.AlignCenter)
        welcome.setStyleSheet("font-size:27px; font-weight:650; padding:18px 0 5px;")
        subtitle = QLabel("A calmer workspace for your local AI agent.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f"color:{MUTED}; font-size:13px; padding-bottom:24px;")
        messages.addWidget(welcome)
        messages.addWidget(subtitle)

        suggestions = QHBoxLayout()
        suggestions.setSpacing(8)
        for label in ("Review code", "Search the web", "Analyze files"):
            chip = QPushButton(label)
            chip.setStyleSheet(
                f"border:1px solid {BORDER}; background:#262626;"
                "border-radius:12px; padding:10px 12px; text-align:center;"
            )
            suggestions.addWidget(chip)
        messages.addLayout(suggestions)
        messages.addSpacing(20)
        messages.addWidget(ChatMessage(
            "You", "Review the router and find any bugs that could cause incorrect tool selection."
        ))
        messages.addWidget(ChatMessage(
            "Nova", "When connected, Nova will respond here using the existing agent engine. "
                   "This screen is a layout prototype; no request has been sent."
        ))
        messages.addStretch(2)
        scroll.setWidget(messages_root)
        center_col.addWidget(scroll, 1)

        composer_wrap = QWidget()
        composer_layout = QVBoxLayout(composer_wrap)
        composer_layout.setContentsMargins(28, 12, 28, 20)
        composer = QFrame()
        composer.setObjectName("composer")
        comp = QHBoxLayout(composer)
        comp.setContentsMargins(15, 7, 8, 7)
        comp.setSpacing(8)
        attach = QPushButton("＋")
        attach.setFixedSize(QSize(34, 34))
        attach.setToolTip("Attachment control in the future connected UI")
        attach.setStyleSheet("font-size:20px; padding:0; text-align:center;")
        comp.addWidget(attach)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Message Nova")
        self.input.returnPressed.connect(self._prototype_send)
        comp.addWidget(self.input, 1)
        send = QPushButton("↑")
        send.setObjectName("send")
        send.setFixedSize(QSize(34, 34))
        send.clicked.connect(self._prototype_send)
        comp.addWidget(send)
        composer_layout.addWidget(composer)
        hint = QLabel("Prototype only · sending is disabled until the real engine is connected")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color:#777777; font-size:10px; padding-top:7px;")
        composer_layout.addWidget(hint)
        center_col.addWidget(composer_wrap)
        outer.addWidget(center, 1)

        tools_panel = QWidget()
        tools_panel.setObjectName("toolPanel")
        tools_panel.setFixedWidth(260)
        tp = QVBoxLayout(tools_panel)
        tp.setContentsMargins(15, 20, 15, 16)
        tp.setSpacing(9)
        panel_title = QLabel("Workspace")
        panel_title.setStyleSheet("font-size:15px; font-weight:700;")
        tp.addWidget(panel_title)
        panel_subtitle = QLabel("Agent capabilities")
        panel_subtitle.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        tp.addWidget(panel_subtitle)
        tp.addSpacing(8)
        for name, desc, enabled in [
            ("Web search", "Search public information", True),
            ("Files", "Read and manage workspace files", True),
            ("Terminal", "Run permitted commands", True),
            ("Git", "Inspect local repositories", True),
            ("PC control", "Optional desktop actions", False),
        ]:
            tp.addWidget(ToolRow(name, desc, enabled))
        tp.addSpacing(12)
        status_title = QLabel("CONNECTION")
        status_title.setStyleSheet(f"color:{MUTED}; font-size:10px; font-weight:700;")
        tp.addWidget(status_title)
        status = QFrame()
        status.setStyleSheet(
            f"background:#242424; border:1px solid {BORDER}; border-radius:10px;"
        )
        status_col = QVBoxLayout(status)
        status_col.setContentsMargins(12, 12, 12, 12)
        status_col.setSpacing(7)
        status_col.addWidget(QLabel("Engine  ·  Not connected"))
        status_col.addWidget(QLabel("Model   ·  Not detected"))
        status_col.addWidget(QLabel("Tools    ·  Preview only"))
        for child in status.findChildren(QLabel):
            child.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        tp.addWidget(status)
        tp.addStretch(1)
        foot = QLabel("Real status will come from NovaCore")
        foot.setWordWrap(True)
        foot.setStyleSheet(f"color:#777777; font-size:10px;")
        tp.addWidget(foot)
        outer.addWidget(tools_panel)

    def _prototype_send(self):
        # Avoid pretending a real agent has executed. This prototype is layout-only.
        self.input.clear()
        self.statusBar().showMessage(
            "Prototype only — connect NovaCore before sending messages.", 4500
        )


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Nova UI Prototype")
    app.setFont(QFont("Segoe UI", 10))
    window = NovaPrototype()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
