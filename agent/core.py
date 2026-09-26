import ollama


class OllamaBrain:

    def __init__(self, model="qwen2.5:3b"):
        # qwen2.5:3b is small (~2GB) but excellent at JSON and coding tasks
        # Upgrade options: qwen2.5:7b, qwen2.5:14b
        self.model = model

    def generate(self, prompt, system_prompt=None):

        system = system_prompt or (
            "You are Nova, a local AI agent running on the user's computer. "
            "You have real tools to create files, run terminal commands, "
            "read files, and search the web. "
            "When asked to perform a computer task, you MUST use the tools — "
            "never pretend to do something without actually doing it. "
            "Always return valid JSON when the task requires it."
        )

        response = ollama.chat(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": system
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            options={
                # Lower temperature = more deterministic JSON output
                "temperature": 0.1,
                "top_p": 0.9,
            }
        )

        return response["message"]["content"]