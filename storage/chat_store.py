"""SQLite-backed local chat history for Nova's desktop application."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _default_database_path() -> Path:
    """Choose a per-user application-data location, never the repository."""
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "Nova" / "chats.sqlite3"
    root = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "nova" / "chats.sqlite3"


class ChatStore:
    """Persist chat sessions and their conversation memory on this computer."""

    def __init__(self, path=None):
        self.path = Path(path).expanduser() if path else _default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._db() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    attachments TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                )
            """)
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_chat_id_id "
                "ON messages(chat_id, id)"
            )

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def create_chat(self, title="New chat"):
        chat_id = uuid.uuid4().hex
        now = self._now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO chats(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (chat_id, str(title or "New chat")[:100], now, now),
            )
        return chat_id

    def list_chats(self, limit=200):
        with self._connect() as db:
            rows = db.execute(
                "SELECT c.id, c.title, c.created_at, c.updated_at, "
                "(SELECT COUNT(*) FROM messages m WHERE m.chat_id=c.id) AS message_count "
                "FROM chats c ORDER BY c.updated_at DESC, c.rowid DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_messages(self, chat_id):
        with self._connect() as db:
            rows = db.execute(
                "SELECT role, content, attachments, created_at "
                "FROM messages WHERE chat_id=? ORDER BY id",
                (str(chat_id),),
            ).fetchall()
        result = []
        for row in rows:
            try:
                attachments = json.loads(row["attachments"] or "[]")
            except (TypeError, json.JSONDecodeError):
                attachments = []
            result.append({
                "role": row["role"],
                "content": row["content"],
                "attachments": attachments if isinstance(attachments, list) else [],
                "created_at": row["created_at"],
            })
        return result

    def add_message(self, chat_id, role, content, attachments=None):
        role = str(role)
        if role not in {"user", "assistant"}:
            raise ValueError("Only user and assistant messages can be saved.")
        content = str(content or "")
        attachment_list = [
            str(item) for item in (attachments or [])
            if isinstance(item, (str, os.PathLike))
        ]
        now = self._now()
        with self._connect() as db:
            exists = db.execute(
                "SELECT 1 FROM chats WHERE id=?", (str(chat_id),)
            ).fetchone()
            if not exists:
                raise KeyError(f"Unknown chat: {chat_id}")
            db.execute(
                "INSERT INTO messages(chat_id, role, content, attachments, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(chat_id), role, content,
                 json.dumps(attachment_list, ensure_ascii=False), now),
            )
            if role == "user":
                title_row = db.execute(
                    "SELECT title FROM chats WHERE id=?", (str(chat_id),)
                ).fetchone()
                if title_row and title_row["title"] == "New chat":
                    title = " ".join(content.split())[:52] or "New chat"
                    db.execute(
                        "UPDATE chats SET title=?, updated_at=? WHERE id=?",
                        (title, now, str(chat_id)),
                    )
                else:
                    db.execute(
                        "UPDATE chats SET updated_at=? WHERE id=?",
                        (now, str(chat_id)),
                    )
            else:
                db.execute(
                    "UPDATE chats SET updated_at=? WHERE id=?",
                    (now, str(chat_id)),
                )

    def delete_chat(self, chat_id):
        with self._connect() as db:
            cursor = db.execute("DELETE FROM chats WHERE id=?", (str(chat_id),))
            return cursor.rowcount > 0
