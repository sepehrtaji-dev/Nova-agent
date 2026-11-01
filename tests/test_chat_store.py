import tempfile
import unittest
from pathlib import Path

from storage.chat_store import ChatStore


class ChatStoreTests(unittest.TestCase):
    def test_messages_are_isolated_between_chats_and_restore_attachments(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ChatStore(Path(directory) / "chats.sqlite3")
            first = store.create_chat()
            second = store.create_chat()

            store.add_message(
                first, "user", "Hello Nova", ["/tmp/notes.txt"],
                context="Hello Nova\\n\\n[Attached File: notes.txt] private document context"
            )
            store.add_message(first, "assistant", "Hello! How can I help?")
            store.add_message(second, "user", "A separate conversation")

            first_messages = store.get_messages(first)
            second_messages = store.get_messages(second)

            self.assertEqual(
                [item["role"] for item in first_messages],
                ["user", "assistant"],
            )
            self.assertEqual(first_messages[0]["attachments"], ["/tmp/notes.txt"])
            self.assertIn("private document context", first_messages[0]["context"])
            self.assertEqual(len(second_messages), 1)
            self.assertEqual(second_messages[0]["content"], "A separate conversation")

    def test_first_user_message_becomes_chat_title(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ChatStore(Path(directory) / "chats.sqlite3")
            chat_id = store.create_chat()
            store.add_message(chat_id, "user", "  Help me build Nova  ")

            chat = next(item for item in store.list_chats() if item["id"] == chat_id)
            self.assertEqual(chat["title"], "Help me build Nova")
            self.assertEqual(chat["message_count"], 1)

    def test_deleting_chat_cascades_to_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ChatStore(Path(directory) / "chats.sqlite3")
            chat_id = store.create_chat()
            store.add_message(chat_id, "user", "Temporary chat")

            self.assertTrue(store.delete_chat(chat_id))
            self.assertEqual(store.get_messages(chat_id), [])
            self.assertFalse(store.delete_chat(chat_id))


if __name__ == "__main__":
    unittest.main()
