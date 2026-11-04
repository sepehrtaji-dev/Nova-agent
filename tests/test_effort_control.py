import unittest
from unittest.mock import Mock
from model.effort import EffortAwareBrain
from model.remote import OpenAICompatibleBrain

class EffortAwareBrainTests(unittest.TestCase):
    def test_remote_medium_sets_reasoning_effort(self):
        brain=Mock(spec=OpenAICompatibleBrain)
        EffortAwareBrain(brain,"medium").generate("hi")
        self.assertEqual(brain.generate.call_args.kwargs["options"]["reasoning_effort"],"medium")
    def test_remote_max_maps_to_high(self):
        brain=Mock(spec=OpenAICompatibleBrain)
        EffortAwareBrain(brain,"max").generate("hi")
        self.assertEqual(brain.generate.call_args.kwargs["options"]["reasoning_effort"],"high")
    def test_remote_off_omits_reasoning_effort(self):
        brain=Mock(spec=OpenAICompatibleBrain)
        EffortAwareBrain(brain,"off").generate("hi")
        self.assertNotIn("reasoning_effort",brain.generate.call_args.kwargs["options"])
    def test_local_maps_effort_to_ollama_think(self):
        from model.ollama import OllamaBrain
        brain=Mock(spec=OllamaBrain)
        EffortAwareBrain(brain,"high").generate("hi")
        self.assertEqual(brain.generate.call_args.kwargs["think"],"high")
    def test_streaming_also_receives_effort(self):
        from model.ollama import OllamaBrain
        brain=Mock(spec=OllamaBrain)
        EffortAwareBrain(brain,"low").generate_stream("hi",lambda _:None)
        self.assertEqual(brain.generate_stream.call_args.kwargs["think"],"low")

if __name__ == "__main__":
    unittest.main()
