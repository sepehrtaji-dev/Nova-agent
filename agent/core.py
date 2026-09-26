from model.ollama import OllamaBrain
from memory.memory import Memory


class NovaCore:
    def __init__(self):
        self.brain = OllamaBrain()
        self.memory = Memory()

    def ask(self, message):

        self.memory.add(
            "user",
            message
        )

        history = self.memory.get_recent()

        response = self.brain.generate(
            history
        )

        self.memory.add(
            "assistant",
            response
        )

        return response