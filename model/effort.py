"""Backend-native controls for Nova's effort selector."""
_VALID = {"off", "low", "medium", "high", "max", "novacode"}
_LEVEL = {"low": "low", "medium": "medium", "high": "high", "max": "high", "novacode": "high"}


class EffortAwareBrain:
    """Apply selected effort consistently across planner, tools and responses."""
    def __init__(self, brain, effort="medium"):
        self.brain = brain
        self.effort = "medium"
        self.set_effort(effort)

    def __getattr__(self, name):
        return getattr(self.brain, name)

    def set_effort(self, effort):
        value = str(effort or "medium").strip().lower()
        self.effort = value if value in _VALID else "medium"

    def _remote_options(self, options):
        result = dict(options or {})
        if self.effort == "off":
            result.pop("reasoning_effort", None)
        else:
            result["reasoning_effort"] = _LEVEL.get(self.effort, "medium")
        return result

    @property
    def supports_tool_calls(self):
        return callable(getattr(self.brain, "generate_tool_turn", None))

    def generate_tool_turn(self, messages, tools, system_prompt=None, options=None):
        method = getattr(self.brain, "generate_tool_turn", None)
        if not callable(method):
            raise NotImplementedError("The configured model backend does not support native tool calls.")
        from model.remote import OpenAICompatibleBrain
        if isinstance(self.brain, OpenAICompatibleBrain):
            return method(
                messages=messages,
                tools=tools,
                system_prompt=system_prompt,
                options=self._remote_options(options),
            )
        return method(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            options=options,
            think=False if self.effort == "off" else _LEVEL.get(self.effort, "medium"),
        )

    def generate(self, prompt, system_prompt=None, json_mode=False, options=None):
        from model.remote import OpenAICompatibleBrain
        if isinstance(self.brain, OpenAICompatibleBrain):
            return self.brain.generate(prompt, system_prompt=system_prompt, json_mode=json_mode, options=self._remote_options(options))
        return self.brain.generate(prompt, system_prompt=system_prompt, json_mode=json_mode, options=options,
            think=False if self.effort == "off" else _LEVEL.get(self.effort, "medium"))

    def generate_stream(self, prompt, on_token, system_prompt=None, json_mode=False, options=None):
        from model.remote import OpenAICompatibleBrain
        stream = getattr(self.brain, "generate_stream", None)
        if not callable(stream):
            result = self.generate(prompt, system_prompt=system_prompt, json_mode=json_mode, options=options)
            if callable(on_token):
                on_token(result)
            return result
        if isinstance(self.brain, OpenAICompatibleBrain):
            return stream(prompt, on_token, system_prompt=system_prompt, json_mode=json_mode, options=self._remote_options(options))
        return stream(prompt, on_token, system_prompt=system_prompt, json_mode=json_mode, options=options,
            think=False if self.effort == "off" else _LEVEL.get(self.effort, "medium"))
