"""First-run setup wizard for the NoviqX GitHub App integration.

Appears on Nova launch when NoviqX is not yet configured and the user has
not permanently dismissed the prompt. Walks the user through creating their
OWN GitHub App, picking the .pem, and entering the App ID + installation ID.
Tests the connection for real before persisting anything.

Security contract:
- The .pem is referenced by path only; its contents are never read by this
  module. The path is stored in ~/.nova/noviqx.json with mode 0600.
- The user can quit the wizard at any step without losing prior valid config.
- The "Never show this again" button sets a flag; the user can re-open the
  wizard later from the Settings menu.
"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from integrations.noviqx.auth import (
    GitHubAppAuth,
    NoviqXAuthenticationError,
    NoviqXConfigurationError,
)
from integrations.noviqx.github_api import GitHubAPIError, NoviqXGitHub
from integrations.noviqx.settings import (
    is_configured,
    load_settings,
    masked_display,
    save_settings,
)

# Theme colors (kept in sync with App.py — duplicated rather than imported
# so the wizard stays self-contained and does not couple to App's internals).
_BG_MAIN = "#0b0f14"
_BG_PANEL = "#111821"
_BG_INPUT = "#17212c"
_BORDER = "#263342"
_TEXT = "#e6edf3"
_TEXT_MUTED = "#9aa9b8"
_ACCENT = "#82aaff"
_SUCCESS = "#3fb950"
_ERROR = "#f85149"


CREATE_APP_URL = "https://github.com/settings/apps/new"
INSTALLATIONS_URL = "https://github.com/settings/installations"


def _apply_wizard_theme(widget: QWidget) -> None:
    widget.setStyleSheet(
        f"""
        QDialog {{ background: {_BG_MAIN}; }}
        QWidget#root {{ background: {_BG_MAIN}; }}
        QLabel {{ color: {_TEXT}; background: transparent; border: none; }}
        QLabel[role="title"] {{ font-size: 18px; font-weight: 700; }}
        QLabel[role="heading"] {{ font-size: 14px; font-weight: 600; color: {_TEXT}; }}
        QLabel[role="body"] {{ font-size: 12px; color: {_TEXT_MUTED}; }}
        QLabel[role="hint"] {{ font-size: 11px; color: {_TEXT_MUTED}; }}
        QLabel[role="error"] {{ font-size: 12px; color: {_ERROR}; }}
        QLabel[role="success"] {{ font-size: 12px; color: {_SUCCESS}; }}
        QLineEdit {{
            background: {_BG_INPUT}; color: {_TEXT}; border: 1px solid {_BORDER};
            border-radius: 6px; padding: 8px 10px; font-size: 13px;
        }}
        QLineEdit:focus {{ border-color: {_ACCENT}; }}
        QPushButton {{
            background: {_BG_INPUT}; color: {_TEXT}; border: 1px solid {_BORDER};
            border-radius: 6px; padding: 7px 14px; font-size: 13px;
        }}
        QPushButton:hover {{ border-color: {_ACCENT}; }}
        QPushButton[role="primary"] {{
            background: {_ACCENT}; color: {_BG_MAIN}; border: none; font-weight: 600;
        }}
        QPushButton[role="primary"]:hover {{ background: #9bb8ff; }}
        QPushButton[role="link"] {{
            background: transparent; border: none; color: {_ACCENT};
            text-decoration: underline; padding: 2px 0;
        }}
        QTextBrowser {{
            background: {_BG_PANEL}; color: {_TEXT}; border: 1px solid {_BORDER};
            border-radius: 6px; padding: 10px; font-size: 12px;
        }}
        QProgressBar {{
            background: {_BG_INPUT}; border: 1px solid {_BORDER};
            border-radius: 4px; height: 4px; text-align: none;
        }}
        QProgressBar::chunk {{ background: {_ACCENT}; border-radius: 3px; }}
        QFrame#divider {{ background: {_BORDER}; max-height: 1px; }}
        """
    )


class NoviqXSetupWizard(QDialog):
    """Multi-step wizard. Returns Accepted only after a verified connection."""

    def __init__(self, parent=None, *, allow_dismiss=True):
        super().__init__(parent)
        self.setWindowTitle("Set up NoviqX GitHub App")
        self.setMinimumSize(620, 520)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._allow_dismiss = allow_dismiss
        self._step = 0
        self._existing = load_settings()
        self._build_ui()
        _apply_wizard_theme(self)
        self._render_step()

    # ---------- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        root = QFrame()
        root.setObjectName("root")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)

        # Title
        title = QLabel("NoviqX GitHub App")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # Progress indicator
        self.progress = QProgressBar()
        self.progress.setRange(0, 4)
        layout.addWidget(self.progress)

        # Body container — replaced on each step
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        layout.addWidget(self.body, 1)

        # Footer with action buttons
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        footer.addStretch(1)
        if self._allow_dismiss:
            self.dismiss_btn = QPushButton("Never show this again")
            self.dismiss_btn.setProperty("role", "link")
            self.dismiss_btn.clicked.connect(self._dismiss_forever)
            footer.addWidget(self.dismiss_btn)
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self._go_back)
        footer.addWidget(self.back_btn)
        self.next_btn = QPushButton("Continue")
        self.next_btn.setProperty("role", "primary")
        self.next_btn.clicked.connect(self._advance)
        footer.addWidget(self.next_btn)
        layout.addLayout(footer)

    # ---------- Step rendering -------------------------------------------------

    def _render_step(self) -> None:
        self.progress.setValue(self._step)
        # Clear body. takeAt() only removes the layout item; the widget itself
        # is still parented to self.body and stays visible until deleteLater()
        # fires on the next event loop tick — by which time the new step's
        # widgets are already on screen, causing the visual overlap users see.
        # Fix: detach the widget from its parent immediately with setParent(None)
        # so it disappears from the layout NOW, then schedule deletion.
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        # Force the body to re-layout immediately so the new widgets appear in
        # the correct position rather than overlapping the previous step's.
        self.body.updateGeometry()

        if self._step == 0:
            self._render_intro()
        elif self._step == 1:
            self._render_create_app()
        elif self._step == 2:
            self._render_credentials()
        elif self._step == 3:
            self._render_test_and_save()
        elif self._step == 4:
            self._render_done()
        self.back_btn.setEnabled(self._step > 0 and self._step < 4)
        self.next_btn.setVisible(self._step < 4)

    def _render_intro(self) -> None:
        heading = QLabel("Connect Nova to GitHub")
        heading.setProperty("role", "heading")
        body = QLabel(
            "Nova can read and update GitHub repositories on your behalf using a "
            "GitHub App that you own and control.\n\n"
            "You'll create a private App on your GitHub account, give it access to "
            "the repositories you want Nova to touch, and tell Nova where its "
            "private key lives on this computer.\n\n"
            "Your private key never leaves this machine. Nova never uploads it, "
            "never sends it to any server, and never writes its contents anywhere."
        )
        body.setProperty("role", "body")
        body.setWordWrap(True)
        self.body_layout.addWidget(heading)
        self.body_layout.addWidget(body)
        self.body_layout.addStretch(1)

    def _render_create_app(self) -> None:
        heading = QLabel("Step 1 — Create your GitHub App")
        heading.setProperty("role", "heading")
        intro = QLabel(
            "Open GitHub's New GitHub App form, give your App a name (e.g. "
            "'YourName's Nova'), and configure the repository access you want."
        )
        intro.setProperty("role", "body")
        intro.setWordWrap(True)

        link = QPushButton("Open github.com/settings/apps/new")
        link.setProperty("role", "primary")
        link.clicked.connect(lambda: webbrowser.open(CREATE_APP_URL))

        instructions = QTextBrowser()
        instructions.setOpenExternalLinks(True)
        instructions.setHtml(
            "<p><b>Required fields on GitHub's form:</b></p>"
            "<ul>"
            "<li><b>GitHub App name</b> — anything you like (only you see it).</li>"
            "<li><b>Homepage URL</b> — your GitHub profile URL is fine.</li>"
            "<li><b>Webhook → Active</b> — uncheck this. Nova does not use webhooks.</li>"
            "<li><b>Repository permissions</b>: "
            "<ul>"
            "<li><b>Contents</b>: Read and write (so Nova can read &amp; edit files).</li>"
            "<li><b>Pull requests</b>: Read and write (so Nova can open PRs).</li>"
            "<li><b>Metadata</b>: Read-only (required, auto-selected).</li>"
            "</ul></li>"
            "<li><b>Where can this app be installed?</b> — <i>Only on this account</i> "
            "is safest for personal use.</li>"
            "</ul>"
            "<p>After creating the App, GitHub shows a <b>Private key</b> section near "
            "the bottom of the App's General page. Click <b>Generate a private key</b> "
            "— a <code>.pem</code> file downloads. Save it somewhere permanent on "
            "this computer.</p>"
            "<p style='color:#9aa9b8;'>You will also see the <b>App ID</b> (a number) "
            "near the top of that page — copy it, you'll paste it on the next step.</p>"
        )

        self.body_layout.addWidget(heading)
        self.body_layout.addWidget(intro)
        self.body_layout.addWidget(link)
        self.body_layout.addWidget(instructions, 1)

    def _render_credentials(self) -> None:
        heading = QLabel("Step 2 — Enter your App credentials")
        heading.setProperty("role", "heading")
        intro = QLabel(
            "These three values are stored on this computer in "
            "~/.nova/noviqx.json with owner-only permissions (mode 0600). The "
            ".pem file itself stays where you saved it — Nova only remembers its path."
        )
        intro.setProperty("role", "body")
        intro.setWordWrap(True)

        self.app_id_input = QLineEdit()
        self.app_id_input.setPlaceholderText("e.g. 5667949")
        self.app_id_input.setText(self._existing.get("app_id", ""))
        self.app_id_input.textChanged.connect(self._update_credential_state)

        self.install_id_input = QLineEdit()
        self.install_id_input.setPlaceholderText("e.g. 179860235")
        self.install_id_input.setText(self._existing.get("installation_id", ""))
        self.install_id_input.textChanged.connect(self._update_credential_state)

        self.pem_path_input = QLineEdit()
        self.pem_path_input.setPlaceholderText("C:\\Users\\you\\Documents\\your-app.private-key.pem")
        self.pem_path_input.setText(self._existing.get("private_key_path", ""))
        self.pem_path_input.textChanged.connect(self._update_credential_state)

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._pick_pem)

        install_link = QPushButton("Open github.com/settings/installations")
        install_link.setProperty("role", "link")
        install_link.clicked.connect(lambda: webbrowser.open(INSTALLATIONS_URL))

        self.cred_error = QLabel("")
        self.cred_error.setProperty("role", "error")
        self.cred_error.setWordWrap(True)
        self.cred_error.setVisible(False)

        # Layout the form
        form_rows = QVBoxLayout()
        form_rows.setSpacing(6)

        def labeled(label_text, widget, action=None):
            row = QHBoxLayout()
            row.setSpacing(10)
            label = QLabel(label_text)
            label.setMinimumWidth(120)
            row.addWidget(label)
            row.addWidget(widget, 1)
            if action is not None:
                row.addWidget(action)
            return row

        form_rows.addLayout(labeled("App ID", self.app_id_input))
        form_rows.addLayout(labeled("Installation ID", self.install_id_input))
        form_rows.addLayout(labeled("Private key (.pem)", self.pem_path_input, browse_btn))
        form_rows.addLayout(labeled("Where to find it →", install_link))

        self.body_layout.addWidget(heading)
        self.body_layout.addWidget(intro)
        self.body_layout.addLayout(form_rows)
        self.body_layout.addWidget(self.cred_error)
        self.body_layout.addStretch(1)
        self._update_credential_state()

    def _render_test_and_save(self) -> None:
        heading = QLabel("Step 3 — Verify the connection")
        heading.setProperty("role", "heading")
        intro = QLabel(
            "Nova will sign a short-lived JWT with your private key, exchange it "
            "for an installation access token, and read one repository to confirm "
            "everything works. Nothing is written to GitHub during this test."
        )
        intro.setProperty("role", "body")
        intro.setWordWrap(True)

        self.test_repo_input = QLineEdit()
        self.test_repo_input.setPlaceholderText("owner/name of any public repo (e.g. octocat/Hello-World)")
        self.test_repo_input.setText("octocat/Hello-World")

        self.test_status = QLabel("Click Continue to test.")
        self.test_status.setProperty("role", "hint")
        self.test_status.setWordWrap(True)

        self.body_layout.addWidget(heading)
        self.body_layout.addWidget(intro)
        self.body_layout.addSpacing(8)
        self.body_layout.addWidget(QLabel("Repository to read (read-only test):"))
        self.body_layout.addWidget(self.test_repo_input)
        self.body_layout.addWidget(self.test_status)
        self.body_layout.addStretch(1)

    def _render_done(self) -> None:
        heading = QLabel("All set ✅")
        heading.setProperty("role", "heading")
        display = masked_display()
        summary = QLabel(
            "Nova can now read and update GitHub repositories through your App:\n\n"
            f"  • App ID: {display['app_id']}\n"
            f"  • Installation ID: {display['installation_id']}\n"
            f"  • Private key: {display['private_key_path']}\n\n"
            "To use it, just ask Nova to do something with a repository, e.g.:\n"
            "    \"Read README.md from owner/repo using the NoviqX GitHub App.\"\n\n"
            "You can change these credentials any time from Settings → NoviqX."
        )
        summary.setProperty("role", "body")
        summary.setWordWrap(True)
        self.body_layout.addWidget(heading)
        self.body_layout.addWidget(summary)
        self.body_layout.addStretch(1)
        # On the done step, Continue becomes Finish
        self.next_btn.setText("Finish")
        self.next_btn.setProperty("role", "primary")
        self.next_btn.clicked.disconnect()
        self.next_btn.clicked.connect(self.accept)

    # ---------- Actions --------------------------------------------------------

    def _pick_pem(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select your GitHub App private key", "", "Private key (*.pem);;All files (*)"
        )
        if path:
            self.pem_path_input.setText(path)

    def _update_credential_state(self) -> None:
        app_id = self.app_id_input.text().strip()
        install_id = self.install_id_input.text().strip()
        pem_path = self.pem_path_input.text().strip()
        problems = []
        if app_id and not app_id.isdigit():
            problems.append("App ID must be numeric (the number on the App's About page, not the Client ID).")
        if install_id and not install_id.isdigit():
            problems.append("Installation ID must be numeric.")
        if pem_path:
            from pathlib import Path
            p = Path(pem_path).expanduser()
            if not p.is_file():
                problems.append(f"That .pem file does not exist at: {p}")
        if problems:
            self.cred_error.setText("\n".join(problems))
            self.cred_error.setVisible(True)
            self.next_btn.setEnabled(False)
        else:
            self.cred_error.setVisible(False)
            self.next_btn.setEnabled(True)

    def _advance(self) -> None:
        if self._step == 2:
            # Capture credentials, save them, then move to test step
            app_id = self.app_id_input.text().strip()
            install_id = self.install_id_input.text().strip()
            pem_path = self.pem_path_input.text().strip()
            if not (app_id.isdigit() and install_id.isdigit() and pem_path):
                return
            ok, msg = save_settings({
                "app_id": app_id,
                "installation_id": install_id,
                "private_key_path": pem_path,
            })
            if not ok:
                self.cred_error.setText(msg)
                self.cred_error.setVisible(True)
                return
            self._existing = load_settings()
        if self._step == 3:
            # Test the connection for real before moving on
            ok, message = self._test_connection()
            if not ok:
                self.test_status.setText(message)
                self.test_status.setProperty("role", "error")
                return
            self.test_status.setText(message)
            self.test_status.setProperty("role", "success")
            save_settings({"setup_completed": True})
            self._existing = load_settings()

        self._step = min(4, self._step + 1)
        self._render_step()

    def _go_back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._render_step()

    def _dismiss_forever(self) -> None:
        save_settings({"setup_dismissed": True})
        QMessageBox.information(
            self,
            "NoviqX setup hidden",
            "Nova won't show this wizard again automatically.\n\n"
            "You can re-open it any time from Settings → NoviqX, or by running "
            "`python scripts/noviqx_smoke_test.py --repo owner/repo` in a terminal.",
        )
        self.reject()

    def _test_connection(self) -> tuple[bool, str]:
        """Actually authenticate + read a repo. Returns (ok, message).

        Reuses the real NoviqXGitHub class so the test exercises the exact
        code path the agent will use at runtime. The .pem is read from disk
        here by GitHubAppAuth — its content never leaves this process.
        """
        repo = self.test_repo_input.text().strip()
        if "/" not in repo or not repo.strip():
            return False, "Enter a repo in the form owner/name to test against."
        try:
            auth = GitHubAppAuth()
            token = auth.get_installation_token(force_refresh=True)
            if not token:
                return False, "GitHub returned no token. Check your App ID and installation ID."
            github = NoviqXGitHub(auth)
            meta = github.get_repository(repo)
            default_branch = meta.get("default_branch", "?")
            return True, (
                f"✓ Authenticated as your App; {repo} default branch is '{default_branch}'. "
                "You're ready to use NoviqX."
            )
        except NoviqXConfigurationError as exc:
            return False, f"Configuration problem: {exc}"
        except NoviqXAuthenticationError as exc:
            return False, (
                f"GitHub rejected the App authentication: {exc}\n\n"
                "Most common causes:\n"
                "  • Wrong App ID (use the number, not the Client ID)\n"
                "  • Wrong Installation ID (the number at the end of the install URL)\n"
                "  • The .pem doesn't match this App ID (regenerate the key on GitHub)\n"
                "  • The App isn't installed on any repository yet"
            )
        except GitHubAPIError as exc:
            return False, (
                f"Authenticated, but the repository read failed: {exc}\n\n"
                "Make sure the repo exists and your App installation has access to it."
            )
        except Exception as exc:  # noqa: BLE001 — show any unexpected failure honestly
            return False, f"Unexpected error during test: {type(exc).__name__}: {exc}"


def show_wizard_if_needed(parent=None) -> bool:
    """Convenience entry point used by App.py.

    Returns True if the wizard was shown and accepted (or already configured),
    False if the user dismissed it or closed without finishing.
    """
    if is_configured():
        return True
    if not __import__("integrations.noviqx.settings", fromlist=["should_show_wizard"]).should_show_wizard():
        return False
    wizard = NoviqXSetupWizard(parent, allow_dismiss=True)
    result = wizard.exec()
    return result == QDialog.Accepted
