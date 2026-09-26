
import ollama


class OllamaBrain:

    def __init__(self, model="qwen2.5:3b"):
        self.model = model

    def generate(self, prompt, json_mode=False):
        kwargs = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": """
You are Nova, a local AI agent.

You are powered by qwen2.5:3b through Ollama.

You have access to user memory and persistent knowledge
when they are provided in the current prompt.

Use provided memory and knowledge when relevant.

Never invent tool results, files, commands, search results,
memory, or system information.
"""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        if json_mode:
            kwargs["format"] = "json"

        response = ollama.chat(**kwargs)

        content = response.get("message", {}).get("content", "")

        if not isinstance(content, str):
            content = str(content)

        return content.strip()

