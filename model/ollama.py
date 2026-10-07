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

    def generate(self, prompt, system_prompt=None, json_mode=False, options=None):
        system = system_prompt or SYSTEM_PROMPT

        base_options = {
            "temperature": 0.1,
            "num_ctx": 4096,
            "num_predict": 1024,
            "repeat_penalty": 1.3,
            "repeat_last_n": 128,
        }

        if isinstance(options, dict):
            base_options.update(options)

        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "options": base_options,
        }

        if json_mode:
            kwargs["format"] = "json"

        try:
            response = ollama.chat(**kwargs)
        except Exception as exc:
            error_text = str(exc).lower()
            if "token repeat limit reached" not in error_text:
                print(f"[NOVA] Ollama error: {type(exc).__name__}: {exc}")
                raise

            retry_options = dict(base_options)
            retry_options.update({
                "temperature": 0.0,
                "num_ctx": max(int(base_options.get("num_ctx", 4096)), 8192),
                "num_predict": min(int(base_options.get("num_predict", 1024)), 256),
                "repeat_penalty": max(float(base_options.get("repeat_penalty", 1.3)), 1.15),
                "repeat_last_n": 128,
            })
            kwargs["options"] = retry_options
            print("[NOVA] Ollama repeat-limit hit; retrying with a compact deterministic profile...")

            try:
                response = ollama.chat(**kwargs)
            except Exception as retry_error:
                print(f"[NOVA] Ollama retry error: {type(retry_error).__name__}: {retry_error}")
                raise

        content = response.get("message", {}).get("content", "")

        if not isinstance(content, str):
            content = str(content)

        return content.strip()

    def c_gen(self, prompt, json_mode=False):
        return self.generate(prompt, json_mode=json_mode)
