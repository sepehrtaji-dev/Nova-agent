import unittest

from agent.tool_loop import ToolCallingLoop


class StreamedNativeBrain:
    def __init__(self, responses):
        self.responses = list(responses)
        self.streamed = []

    def generate_tool_turn_stream(self, messages, tools, system_prompt=None, on_token=None):
        response = self.responses.pop(0)
        for chunk in response.get("chunks", []):
            self.streamed.append(chunk)
            if callable(on_token):
                on_token(chunk)
        return {
            "content": "".join(response.get("chunks", [])),
            "tool_calls": response.get("tool_calls", []),
        }


class ToolRegistry:
    tools = {}
    def exists(self, name):
        return name in self.tools
    def validate_input(self, name, arguments):
        return True, None
    def execute(self, name, encoded):
        return "actual tool result"


class StreamedNativeLoopTests(unittest.TestCase):
    def test_final_answer_deltas_are_forwarded_and_progress_is_published(self):
        brain = StreamedNativeBrain([{"chunks": ["Hello", " ", "world."]}])
        events = []
        loop = ToolCallingLoop(
            brain=brain,
            tools=ToolRegistry(),
            verifier=None,
            allowed_tools={"read_file"},
            status=events.append,
            on_answer_delta=events.append,
        )
        # The empty tool list is rejected before the provider is called.
        with self.assertRaises(Exception):
            loop.run("hi", system_prompt="Nova")
        self.assertTrue(any("No enabled tools" in item for item in events))

    def test_tool_loop_streams_a_final_response(self):
        brain = StreamedNativeBrain([{"chunks": ["Hello", " ", "world."]}])
        events = []
        tools = ToolRegistry()
        tools.tools = {
            "read_file": {
                "description": "Read a file",
                "capability": "pc",
                "input_schema": {"type": "object", "properties": {}},
            }
        }
        loop = ToolCallingLoop(
            brain=brain,
            tools=tools,
            verifier=None,
            allowed_tools={"read_file"},
            status=events.append,
            on_answer_delta=lambda token: events.append("DELTA:" + token),
        )
        result = loop.run("hi", system_prompt="Nova")
        self.assertEqual(result, "Hello world.")
        self.assertEqual(
            [item for item in events if item.startswith("DELTA:")],
            ["DELTA:Hello", "DELTA: ", "DELTA:world."],
        )
        self.assertTrue(any(item.startswith("THINKING_UPDATE:") for item in events))


if __name__ == "__main__":
    unittest.main()
