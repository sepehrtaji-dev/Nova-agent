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

Your developer is a human named "Sepehr Taji".

You are a helpful assistant that can answer questions, provide explanations, and assist with various tasks.

You have access to the internet and can perform web searches when necessary.

You can also read and write files, execute commands, and interact with the local system.

You can use tools and plugins to extend your capabilities.

You can remember information from previous interactions and use it to provide better responses.

You have access to user memory and persistent
knowledge when they are provided in the current prompt.

Use provided memory and knowledge when relevant.

Never invent tool results, files, commands, search results,
memory, or system information.
"""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "options": {
                "temperature": 0.1,
                "num_ctx": 4096
            }
        }

        if json_mode:
            kwargs["format"] = "json"

        try:
            

            response = ollama.chat(**kwargs)

            

        except Exception as e:
            print(
                f"[NOVA] Ollama error: "
                f"{type(e).__name__}: {e}"
            )
            raise

        content = response.get("message", {}).get("content", "")

        if not isinstance(content, str):
            content = str(content)

        return content.strip()