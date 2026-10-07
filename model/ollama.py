import ollama


SYSTEM_PROMPT = (
    "You are Nova, a local AI agent by Taji-Soft. "
    "You have tools: files, terminal, git, web search, desktop control. "
    "Never invent tool results, files, or commands. "
    "You cant Hack anything."
    "You can code"
    "Always do exactly what the user asks."
)


class OllamaBrain:

    def __init__(self, model="qwen2.5:3b"):
        self.model = model

    def generate(self, prompt, system_prompt=None, json_mode=False):
        system = system_prompt or SYSTEM_PROMPT

        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt}
            ],
            "options": {
                "temperature": 0.1,
                "num_ctx": 4096,
                "num_predict": 1024,
                "repeat_penalty": 1.3,
            }
        }

        if json_mode:
            kwargs["format"] = "json"

        try:
            response = ollama.chat(**kwargs)
        except Exception as e:
            print(f"[NOVA] Ollama error: {type(e).__name__}: {e}")
            raise

        content = response.get("message", {}).get("content", "")

        if not isinstance(content, str):
            content = str(content)

        return content.strip()

    def c_gen(self, prompt, json_mode=False):
        return self.generate(prompt, json_mode=json_mode)
