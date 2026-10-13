import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent.verifier import Verifier
from memory.episodic import EpisodicMemory
from model.ollama import OllamaBrain
from tools.git import GitTool
from tools.registry import ToolRegistry
from tools.terminal import TerminalTool


class AuditRegressionTests(unittest.TestCase):
    def test_registry_exposes_callable_input_contract_to_planner(self):
        def sample_tool(payload):
            """Input: {"path": "file.txt"}. Reads the named file."""
            return payload

        registry = ToolRegistry()
        registry.register("sample", "Read a file", sample_tool)

        descriptions = registry.get_descriptions()
        self.assertIn("Input contract:", descriptions)
        self.assertIn("path", descriptions)
        self.assertIn("Reads the named file", descriptions)

    def test_ollama_chat_response_model_is_supported(self):
        response = SimpleNamespace(message=SimpleNamespace(content="  hello Nova  "))
        with mock.patch("model.ollama.ollama.chat", return_value=response):
            self.assertEqual(OllamaBrain(model="test-model").generate("hi"), "hello Nova")

    def test_git_rejects_option_like_remote_names(self):
        with self.assertRaises(ValueError):
            GitTool._safe_remote_or_branch("--all", "remote")
        with self.assertRaises(ValueError):
            GitTool._safe_remote_or_branch("-c", "branch")

    def test_git_clone_rejects_loopback_destinations(self):
        with self.assertRaisesRegex(ValueError, "non-public"):
            GitTool._validate_clone_url("https://127.0.0.1/repo.git")

    def test_terminal_rejects_shell_wrappers(self):
        tool = TerminalTool()
        self.assertTrue(tool._is_blocked("env bash -c echo SHELL_BYPASS"))
        self.assertTrue(tool._is_blocked("command powershell -Command whoami"))

    def test_episodic_memory_redacts_natural_language_password(self):
        cleaned = EpisodicMemory._clean("my password is hunter2 and then continue")
        self.assertNotIn("hunter2", cleaned)
        self.assertIn("[REDACTED]", cleaned)

    def test_vector_memory_accepts_filename_without_parent_directory(self):
        class DummyEmbedder:
            def __init__(self, dimensions=256):
                self.dimensions = dimensions
            def encode(self, text):
                return [0.0] * self.dimensions

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("memory.vector_memory.EmbeddingModel", DummyEmbedder):
                old_cwd = os.getcwd()
                try:
                    os.chdir(directory)
                    from memory.vector_memory import VectorMemory
                    memory = VectorMemory(path="memories.json")
                    self.assertTrue(Path("memories.json").is_file())
                    self.assertEqual(memory.memories, [])
                finally:
                    os.chdir(old_cwd)

    def test_clone_verifier_respects_explicit_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "projects" / "chosen-destination"
            (project / ".git").mkdir(parents=True)
            verifier = Verifier(tools=None)
            with mock.patch("agent.verifier.os.getcwd", return_value=directory):
                result = verifier._verify_git(
                    {"action": "clone", "url": "https://example.com/source.git",
                     "dest": "chosen-destination"},
                    "Exit code: 0\nSTATUS: SUCCESS",
                )
            self.assertEqual(result.status, "confirmed")


if __name__ == "__main__":
    unittest.main()
