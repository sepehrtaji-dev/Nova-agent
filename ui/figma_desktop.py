"""Figma-aligned PySide6 desktop shell for Nova.

The shell owns presentation and navigation only. Agent execution, settings
persistence, tool permissions, messages and attachments remain in App.py.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

BG = "#0f172a"
SIDEBAR_TOP = "#1f2937"
SIDEBAR_BOTTOM = "#111827"
BORDER = "#334155"
BLUE = "#1677ff"
GREEN = "#22c55e"
MUTED = "#93c5fd"
TEXT = "#ffffff"
SECONDARY = "#cbd5e1"


def label(text: str, size=14, color=TEXT, weight=400, parent=None):
    item = QLabel(text, parent)
    item.setWordWrap(True)
    item.setStyleSheet(
        f'font-family: "Inter", "Segoe UI"; font-size: {size}px; '
        f'font-weight: {weight}; color: {color}; background: transparent;'
    )
    return item


def card(parent=None, padding=24):
    frame = QFrame(parent)
    frame.setObjectName("figmaCard")
    frame.setStyleSheet(
        f"QFrame#figmaCard {{ background: rgba(255,255,255,0.05); "
        f"border: 1px solid {BORDER}; border-radius: 20px; }}"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(padding, padding, padding, padding)
    layout.setSpacing(18)
    return frame, layout


def action_button(text, primary=False, parent=None):
    button = QPushButton(text, parent)
    button.setCursor(Qt.PointingHandCursor)
    bg = BLUE if primary else "rgba(255,255,255,0.08)"
    button.setStyleSheet(
        f"QPushButton {{ background: {bg}; color: white; border: 1px solid {BORDER}; "
        f"border-radius: 20px; padding: 10px 18px; font-size: 14px; "
        f"font-weight: 600; }} QPushButton:hover {{ border-color: {BLUE}; }}"
    )
    return button


class FigmaDesktopShell:
    """Build the 280px sidebar + 1000px content canvas and its three pages."""

    def __init__(self, owner):
        self.owner = owner
        self.nav_buttons = {}
        self.stack = None
        self.workspace_tree = None
        self.workspace_activity = None
        self.workspace_stats = {}
        self.welcome_hero = None
        self.extra_workspace_roots = []

    def build(self):
        root = QWidget()
        root.setObjectName("root")
        root.setStyleSheet(
            "QWidget#root { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #0b1020, stop:0.55 #1e1b4b, stop:1 #0f172a); }"
        )
        self.owner.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._sidebar(), 0)

        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        self.stack.addWidget(self._chat_page())
        self.stack.addWidget(self._settings_page())
        self.stack.addWidget(self._workspace_page())
        shell.addWidget(self.stack, 1)

        # Keep the legacy activity/capability widgets alive as the source of
        # truth for permission toggles and existing status callbacks.
        self.owner.activity_panel = self.owner._build_activity_panel()
        self.owner.activity_panel.hide()
        self.owner._desktop_shell = self
        self.owner.sidebar = self.sidebar
        self.show_welcome()
        self.navigate("chat")
        return root

    def _sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(280)
        sidebar.setStyleSheet(
            f"QFrame#sidebar {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {SIDEBAR_TOP}, stop:1 {SIDEBAR_BOTTOM}); "
            f"border-right: 1px solid {BORDER}; }}"
        )
        self.sidebar = sidebar
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 24, 16, 24)
        layout.setSpacing(20)

        brand = QHBoxLayout()
        logo = QLabel("✦")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(40, 40)
        logo.setStyleSheet(f"background:{BLUE}; border-radius:12px; color:white; font-size:22px;")
        brand.addWidget(logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        brand_text.addWidget(label("Nova", 18, TEXT, 700))
        brand_text.addWidget(label("AI Assistant", 12, MUTED))
        brand.addLayout(brand_text)
        brand.addStretch(1)
        layout.addLayout(brand)

        nav = QVBoxLayout()
        nav.setSpacing(8)
        for key, title, glyph in (
            ("chat", "Chats", "▤"),
            ("settings", "Settings", "⚙"),
            ("workspace", "Workspace", "▣"),
        ):
            button = QPushButton(f"{glyph}    {title}")
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(46)
            button.setStyleSheet(
                "QPushButton { text-align:left; padding:0 12px; border-radius:10px; "
                f"color:{MUTED}; background:rgba(255,255,255,0.05); border:1px solid {BORDER}; }}"
                "QPushButton:hover { color:white; background:rgba(255,255,255,0.10); }"
            )
            button.clicked.connect(lambda _=False, page=key: self.navigate(page))
            self.nav_buttons[key] = button
            nav.addWidget(button)
        layout.addLayout(nav)

        quick_label = label("QUICK ACTIONS", 12, MUTED, 600)
        layout.addWidget(quick_label)
        new_chat = QPushButton("＋    New Chat")
        new_chat.setCursor(Qt.PointingHandCursor)
        new_chat.setFixedHeight(46)
        new_chat.setStyleSheet(
            f"QPushButton {{ background:{GREEN}; color:white; border:0; border-radius:10px; "
            "text-align:left; padding:0 12px; font-weight:600; }}"
            "QPushButton:hover { background:#16a34a; }"
        )
        new_chat.clicked.connect(self.owner._new_chat)
        layout.addWidget(new_chat)
        layout.addStretch(1)

        status = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet("color:#22c55e; font-size:11px;")
        status.addWidget(dot)
        status.addWidget(label("Nova is online", 13, MUTED))
        status.addStretch(1)
        layout.addLayout(status)
        return sidebar

    def _page(self, name):
        page = QWidget()
        page.setObjectName(name)
        page.setStyleSheet(f"QWidget#{name} {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {BG},stop:1 #111827); }}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(32)
        return page, layout

    def _chat_page(self):
        page, layout = self._page("chatPage")
        header = QHBoxLayout()
        badge = QLabel("N")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(48, 48)
        badge.setStyleSheet(f"background:{BLUE}; border-radius:24px; color:white; font-size:20px; font-weight:800;")
        header.addWidget(badge)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(label("Nova AI Assistant", 20, TEXT, 700))
        titles.addWidget(label("Typically replies in seconds", 14, MUTED))
        header.addLayout(titles)
        header.addStretch(1)
        self.owner.status_label = label("Ready", 12, MUTED)
        header.addWidget(self.owner.status_label)
        layout.addLayout(header)

        # Reuse the existing message container and scroll behavior unchanged.
        self.owner.chat_scroll = QScrollArea()
        self.owner.chat_scroll.setObjectName("chatScroll")
        self.owner.chat_scroll.setWidgetResizable(True)
        self.owner.chat_scroll.setFrameShape(QFrame.NoFrame)
        self.owner.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.owner.chat_container = QWidget()
        self.owner.chat_container.setObjectName("chatContainer")
        self.owner.chat_container_layout = QVBoxLayout(self.owner.chat_container)
        self.owner.chat_container_layout.setContentsMargins(0, 0, 0, 0)
        self.owner.chat_container_layout.setSpacing(16)
        self.owner.chat_container_layout.addStretch(1)
        self.owner.chat_scroll.setWidget(self.owner.chat_container)
        bar = self.owner.chat_scroll.verticalScrollBar()
        bar.rangeChanged.connect(self.owner._on_chat_range_changed)
        bar.valueChanged.connect(self.owner._on_chat_scrolled)
        layout.addWidget(self.owner.chat_scroll, 1)

        suggestions = QHBoxLayout()
        suggestions.setSpacing(12)
        for title, color, prompt in (
            ("✦  Generate ideas", GREEN, "Help me generate ideas for a project."),
            ("▦  Summarize a document", "#f59e0b", "Help me summarize a document."),
            ("?  Help Center", "#8b5cf6", "/help"),
        ):
            button = QPushButton(title)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                f"QPushButton {{ color:{color}; background:rgba(255,255,255,0.05); "
                f"border:1px solid {color}; border-radius:20px; padding:10px 16px; }}"
                "QPushButton:hover { background:rgba(255,255,255,0.10); }"
            )
            button.clicked.connect(lambda _=False, text=prompt: self._use_suggestion(text))
            suggestions.addWidget(button)
        suggestions.addStretch(1)
        layout.addLayout(suggestions)

        self.owner.composer_area = self.owner._build_composer()
        # Figma has a 48px attachment action and a full-width input/send row.
        layout.addWidget(self.owner.composer_area)
        return page

    def _use_suggestion(self, text):
        if text == "/help":
            self.owner.input.setPlainText(text)
            self.owner._send()
        else:
            self.owner.input.setPlainText(text)
            self.owner.input.setFocus()

    def show_welcome(self):
        if not self.owner.chat_container_layout:
            return
        hero = QWidget()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(0, 32, 0, 24)
        hero_layout.setSpacing(16)
        hero_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        mark = QLabel("N")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(64, 64)
        mark.setStyleSheet(f"background:{BLUE}; border-radius:32px; color:white; font-size:28px; font-weight:800;")
        hero_layout.addWidget(mark, 0, Qt.AlignHCenter)
        hero_layout.addWidget(label("Hello! I’m Nova, your AI assistant.", 30, TEXT, 700), 0, Qt.AlignHCenter)
        hero_layout.addWidget(label("How can I assist you today?", 18, MUTED, 600), 0, Qt.AlignHCenter)
        copy = label(
            "I can help you generate ideas, summarize long documents, write emails, "
            "or even just chat about your day. I'm here to make your workflow easier and more efficient.",
            15, SECONDARY
        )
        copy.setMaximumWidth(620)
        copy.setAlignment(Qt.AlignCenter)
        hero_layout.addWidget(copy, 0, Qt.AlignHCenter)
        self.welcome_hero = hero
        self.owner.chat_container_layout.insertWidget(0, hero)

    def _settings_page(self):
        page, layout = self._page("settingsPage")
        header = QHBoxLayout()
        icon = QLabel("⚙")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(48, 48)
        icon.setStyleSheet(f"background:{BLUE}; border-radius:24px; color:white; font-size:22px;")
        header.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(label("Settings", 20, TEXT, 700))
        titles.addWidget(label("Customize how Nova looks, sounds, and works", 14, MUTED))
        header.addLayout(titles)
        header.addStretch(1)
        reset = action_button("Reset")
        save = action_button("✓  Save changes", True)
        reset.clicked.connect(self._reset_settings)
        save.clicked.connect(self._save_settings)
        header.addWidget(reset)
        header.addWidget(save)
        layout.addLayout(header)

        columns = QHBoxLayout()
        columns.setSpacing(24)
        left = QVBoxLayout()
        right = QVBoxLayout()
        left.setSpacing(24)
        right.setSpacing(24)

        assistant, a = card()
        a.addWidget(label("▣   Assistant", 16, TEXT, 600))
        a.addWidget(label("Default model", 14, TEXT, 500))
        self.model_combo = QComboBox()
        self.model_combo.addItems(self.owner._installed_models() or [self.owner.current_model])
        self.model_combo.setCurrentText(self.owner.current_model)
        self._style_combo(self.model_combo)
        a.addWidget(self.model_combo)
        a.addWidget(label("Language", 14, TEXT, 500))
        self.language_combo = QComboBox()
        self.language_combo.addItems(["English", "Persian"])
        self._style_combo(self.language_combo)
        self.language_combo.setEnabled(False)
        self.language_combo.setToolTip("Additional UI translations are not implemented yet.")
        a.addWidget(self.language_combo)
        provider = action_button("Configure API / Provider")
        provider.clicked.connect(self.owner._open_model_settings)
        a.addWidget(provider)
        left.addWidget(assistant)

        appearance, ap = card()
        ap.addWidget(label("◐   Appearance", 16, TEXT, 600))
        ap.addWidget(label("Theme", 14, TEXT, 500))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light", "System"])
        self.theme_combo.setCurrentText("Dark")
        self._style_combo(self.theme_combo)
        self.theme_combo.setEnabled(False)
        self.theme_combo.setToolTip("The current desktop build supports the Dark theme.")
        ap.addWidget(self.theme_combo)
        ap.addWidget(label("Accent color", 14, TEXT, 500))
        self.accent_combo = QComboBox()
        self.accent_combo.addItems(["Blue", "Purple", "Green"])
        self._style_combo(self.accent_combo)
        self.accent_combo.setEnabled(False)
        self.accent_combo.setToolTip("Accent customization is not implemented yet.")
        ap.addWidget(self.accent_combo)
        left.addWidget(appearance)
        left.addStretch(1)

        notifications, n = card()
        n.addWidget(label("♧   Notifications", 16, TEXT, 600))
        self.notify_completion = QCheckBox("Task completion notifications")
        self.notify_errors = QCheckBox("Error notifications")
        for control in (self.notify_completion, self.notify_errors):
            control.setStyleSheet(f"QCheckBox {{ color:{SECONDARY}; spacing:10px; }} QCheckBox::indicator {{ width:18px; height:18px; }}")
            control.setEnabled(False)
            control.setToolTip("Desktop notifications are not implemented yet.")
            n.addWidget(control)
        right.addWidget(notifications)

        privacy, p = card()
        p.addWidget(label("▣   Privacy & Data", 16, TEXT, 600))
        p.addWidget(label("Provider", 13, MUTED, 500))
        p.addWidget(label("Local processing" if self.owner._settings.get("provider") != "remote" else "Remote provider configured", 14, TEXT, 600))
        p.addWidget(label("API keys are masked and stored separately. Remote mode sends prompts and tool results to the selected provider.", 12, MUTED))
        right.addWidget(privacy)
        right.addStretch(1)

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns, 1)
        return page

    @staticmethod
    def _style_combo(combo):
        combo.setMinimumHeight(44)
        combo.setStyleSheet(
            f"QComboBox {{ background:rgba(255,255,255,0.08); color:{TEXT}; "
            f"border:1px solid {BORDER}; border-radius:22px; padding:0 16px; }}"
            f"QComboBox QAbstractItemView {{ background:#1f2937; color:{TEXT}; "
            f"selection-background-color:{BLUE}; }}"
        )

    def _save_settings(self):
        model = self.model_combo.currentText().strip()
        if model and model != self.owner.current_model and self.owner._settings.get("provider") != "remote":
            self.owner._select_model(model)
        self.owner._add_activity("Settings saved.")
        self.owner.status_label.setText("Settings saved")

    def _reset_settings(self):
        self.model_combo.setCurrentText(self.owner.current_model)
        self.language_combo.setCurrentText("English")
        self.theme_combo.setCurrentText("Dark")
        self.accent_combo.setCurrentText("Blue")
        self.notify_completion.setChecked(False)
        self.notify_errors.setChecked(False)

    def _workspace_page(self):
        page, layout = self._page("workspacePage")
        header = QHBoxLayout()
        icon = QLabel("▣")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(48, 48)
        icon.setStyleSheet(f"background:{BLUE}; border-radius:24px; color:white; font-size:22px;")
        header.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(label("Workspace", 20, TEXT, 700))
        titles.addWidget(label("Files and commands Nova has touched in this session", 14, MUTED))
        header.addLayout(titles)
        header.addStretch(1)
        refresh = action_button("↻  Refresh")
        refresh.clicked.connect(self.refresh_workspace)
        add_folder = action_button("＋  Add folder", True)
        add_folder.clicked.connect(self._add_workspace_folder)
        header.addWidget(refresh)
        header.addWidget(add_folder)
        layout.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(24)
        files_card, files_layout = card()
        files_layout.addWidget(label("▣   Files", 16, TEXT, 600))
        self.workspace_path = label(str(Path.cwd()), 12, SECONDARY)
        files_layout.addWidget(self.workspace_path)
        self.workspace_tree = QTreeWidget()
        self.workspace_tree.setHeaderHidden(True)
        self.workspace_tree.setStyleSheet(
            f"QTreeWidget {{ background:transparent; color:{SECONDARY}; border:0; "
            f"font-size:13px; }} QTreeWidget::item {{ height:28px; padding:3px; }}"
            f"QTreeWidget::item:selected {{ background:rgba(22,119,255,0.2); color:white; }}"
        )
        files_layout.addWidget(self.workspace_tree, 1)
        legend = label("● Read     ● Modified", 11, MUTED)
        files_layout.addWidget(legend)
        content.addWidget(files_card, 3)

        right = QVBoxLayout()
        stats = QHBoxLayout()
        for title in ("Files read", "Files changed", "Commands run"):
            box, box_layout = card(padding=16)
            value = label("0", 22, TEXT, 700)
            caption = label(title, 12, MUTED)
            box_layout.addWidget(value)
            box_layout.addWidget(caption)
            self.workspace_stats[title] = value
            stats.addWidget(box)
        right.addLayout(stats)

        activity_card, activity_layout = card()
        activity_layout.addWidget(label("◷   Recent Activity", 16, TEXT, 600))
        self.workspace_activity = QVBoxLayout()
        self.workspace_activity.setSpacing(8)
        activity_layout.addLayout(self.workspace_activity)
        right.addWidget(activity_card, 1)

        latest, latest_layout = card()
        latest_layout.addWidget(label("✎   Latest Change", 16, TEXT, 600))
        self.latest_change = label("No file changes recorded in this session.", 12, MUTED)
        latest_layout.addWidget(self.latest_change)
        right.addWidget(latest)
        content.addLayout(right, 7)
        layout.addLayout(content, 1)
        self.refresh_workspace()
        return page

    def refresh_workspace(self):
        if not self.workspace_tree:
            return
        self.workspace_tree.clear()
        root_path = Path.cwd()
        root = QTreeWidgetItem([root_path.name or str(root_path)])
        self.workspace_tree.addTopLevelItem(root)
        self._populate_tree(root, root_path, depth=0)
        root.setExpanded(True)
        for extra in self.extra_workspace_roots:
            extra_root = QTreeWidgetItem([extra.name or str(extra)])
            self.workspace_tree.addTopLevelItem(extra_root)
            self._populate_tree(extra_root, extra, depth=0)
            extra_root.setExpanded(True)
        self.workspace_path.setText(str(root_path) + (f"  ·  +{len(self.extra_workspace_roots)} folder(s)" if self.extra_workspace_roots else ""))

    def _populate_tree(self, parent, path, depth):
        if depth >= 2:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        for entry in entries[:80]:
            if entry.name.startswith(".") or entry.name in {"__pycache__", ".venv", "venv", "node_modules"}:
                continue
            item = QTreeWidgetItem([("▣  " if entry.is_dir() else "▤  ") + entry.name])
            parent.addChild(item)
            if entry.is_dir():
                self._populate_tree(item, entry, depth + 1)

    def _add_workspace_folder(self):
        folder = QFileDialog.getExistingDirectory(self.owner, "Add workspace folder", str(Path.cwd()))
        if folder:
            selected = Path(folder).resolve()
            if selected not in self.extra_workspace_roots:
                self.extra_workspace_roots.append(selected)
            self.owner._add_activity(f"Workspace folder added: {selected}")
            self.refresh_workspace()

    def record_activity(self, message):
        if not self.workspace_activity:
            return
        row = QFrame()
        row.setStyleSheet(f"QFrame {{ background:rgba(255,255,255,0.05); border:1px solid {BORDER}; border-radius:10px; }}")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(10, 7, 10, 7)
        row_layout.setSpacing(3)
        row_layout.addWidget(label("●  " + message, 11, SECONDARY))
        self.workspace_activity.insertWidget(0, row)
        while self.workspace_activity.count() > 12:
            item = self.workspace_activity.takeAt(self.workspace_activity.count() - 1)
            if item.widget():
                item.widget().deleteLater()
        lowered = message.lower()
        if any(token in lowered for token in ("read", "opened", "inspected")):
            self.workspace_stats["Files read"].setText(str(int(self.workspace_stats["Files read"].text()) + 1))
        if any(token in lowered for token in ("write", "modified", "created", "updated")):
            self.workspace_stats["Files changed"].setText(str(int(self.workspace_stats["Files changed"].text()) + 1))
            self.latest_change.setText(message)
        if any(token in lowered for token in ("terminal", "command", "ran ", "executed")):
            self.workspace_stats["Commands run"].setText(str(int(self.workspace_stats["Commands run"].text()) + 1))

    def navigate(self, page):
        indexes = {"chat": 0, "settings": 1, "workspace": 2}
        self.stack.setCurrentIndex(indexes[page])
        for key, button in self.nav_buttons.items():
            active = key == page
            button.setStyleSheet(
                f"QPushButton {{ text-align:left; padding:0 12px; border-radius:10px; "
                f"color:white; background:{BLUE if active else 'rgba(255,255,255,0.05)'}; "
                f"border:1px solid {BLUE if active else BORDER}; font-weight:{600 if active else 500}; }}"
            )
        if page == "workspace":
            self.refresh_workspace()

    def sync_responsive(self):
        # Fixed sidebar mirrors the 280px Figma frame. Content uses Qt layouts,
        # so all inner widths are recomputed by Qt rather than hard-coded pixels.
        self.sidebar.setFixedWidth(280)
        if self.stack.currentIndex() == 2:
            self.refresh_workspace()
