import unittest

from agent.router import ToolRouter


class CaptureBrain:
    def __init__(self, response='{"task_type":"computer"}'):
        self.response = response
        self.prompt = ""
        self.options = None

    def generate(self, prompt, **kwargs):
        self.prompt = prompt
        self.options = kwargs.get("options")
        return self.response


class Registry:
    tools = {
        "read_file": {"description": "Read an uploaded or local text file"},
        "write_file": {"description": "Write complete file content"},
    }

    def exists(self, name):
        return name in self.tools

    def get_descriptions(self):
        return "\n".join(f"- {name}: {data['description']}" for name, data in self.tools.items())


class GemmaFileRegressionTests(unittest.TestCase):
    def test_attached_file_edit_is_explicitly_classified_as_an_action(self):
        brain = CaptureBrain()
        router = ToolRouter(brain, Registry())

        result = router.classify_task(
            "read this file, add my GitHub link to the footer, and give me the code",
            allowed_tools=["read_file", "write_file"],
        )

        self.assertEqual(result, "computer")
        self.assertIn("read this file", brain.prompt)
        self.assertIn("attached/uploaded", brain.prompt)
        self.assertIn("give me the updated code", brain.prompt)

    def test_file_generation_uses_large_output_budget(self):
        brain = CaptureBrain(response="<!doctype html>\n<html>\n<body>complete</body>\n</html>")
        router = ToolRouter(brain, Registry())

        result = router.generate_file_content(
            user_request="Create a complete HTML page",
            path="index.html",
            location="projects",
        )

        self.assertIn("</html>", result)
        self.assertEqual(brain.options["num_predict"], 8192)


if __name__ == "__main__":
    unittest.main()
