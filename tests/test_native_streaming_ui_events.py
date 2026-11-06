import unittest

from agent.tool_loop import ToolCallingLoop, ToolLoopError


class StreamedNativeBrain:
    def __init__(self, responses):
        self.responses = list(responses)
        self.streamed = []

    def generate_tool_turn_stream(
        self, messages, tools, system_prompt=None, on_token=None,
        on_thought_delta=None,
    ):
        response = self.responses.pop(0)
        for chunk in response.get("thought_chunks", []):
            if callable(on_thought_delta):
                on_thought_delta(chunk)
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
        brain = StreamedNativeBrain([{
            "thought_chunks": ["I should answer this greeting briefly. "],
            "chunks": ["Hello", " ", "world."],
        }])
        events = []
        loop = ToolCallingLoop(
            brain=brain,
            tools=ToolRegistry(),
            verifier=None,
            allowed_tools={"read_file"},
            status=events.append,
            on_answer_delta=events.append,
        )
        # A registry with no definitions fails explicitly before provider access.
        with self.assertRaises(ToolLoopError):
            loop.run("hi", system_prompt="Nova")
        self.assertEqual(brain.streamed, [])

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
        # Native model thinking and final answer are separate streams.
        thought_events = [
            item for item in events
            if item == "I should answer this greeting briefly. "
        ]
        self.assertEqual(thought_events, ["I should answer this greeting briefly. "])
        self.assertFalse(any("Reviewing the request" in item for item in events))
        self.assertFalse(any("Preparing the final response" in item for item in events))


if __name__ == "__main__":
    unittest.main()
