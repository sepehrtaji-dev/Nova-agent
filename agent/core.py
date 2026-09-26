from model.ollama import OllamaBrain


class NovaCore:
    def __init__(self):
        self.brain = OllamaBrain()
        self.memory = []

    def ask(self, message):
        self.memory.append(
            {
                "role": "user",
                "content": message,
            }
        )

        response = self.brain.generate(message)

        self.memory.append(
            {
                "role": "assistant",
                "content": response,
            }
        )

        return response