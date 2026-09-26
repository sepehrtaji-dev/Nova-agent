import ollama


class OllamaBrain:
    def __init__(self, model="llama3.2:3b"):
        self.model = model

    def generate(self, prompt):
        response = ollama.chat(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Nova, a local AI agent. "
                        "Be helpful, precise and logical."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )

        return response["message"]["content"]