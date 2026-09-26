import ollama


class OllamaBrain:

    def __init__(self, model="llama3.2:3b"):
        self.model = model


    def generate(self, messages):

        response = ollama.chat(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content":
                    """
You are Nova.
You are a local AI agent.
Remember the conversation context.
"""
                },
                *messages
            ]
        )

        return response["message"]["content"]