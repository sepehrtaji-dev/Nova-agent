"""Evidence-based runtime self-knowledge for Nova.

This describes observable configuration and registered tools; it does not imply
human-like consciousness or guarantee that external services are reachable.
"""
import platform
import re
import sys

from agent.introspection import inspect_model, runtime_profile


class SelfKnowledge:
    """Build self-descriptions from the live NovaCore instance."""

    @staticmethod
    def _allowed(core, capability):
        access = getattr(core, "access", {}) or {}
        return bool(access.get(capability, True))

    def snapshot(self, core):
        brain = getattr(core, "brain", None)
        model = getattr(brain, "model", None) or "unknown (model not configured)"
        registry = getattr(core, "tools", None)
        registered = getattr(registry, "tools", {}) or {}
        access = getattr(core, "access", {}) or {}

        tools = []
        for name, data in sorted(registered.items()):
            data = data if isinstance(data, dict) else {}
            capability = str(data.get("capability", "pc"))
            tools.append({
                "name": str(name),
                "description": str(data.get("description", "")).strip(),
                "capability": capability,
                "enabled": bool(access.get(capability, True)),
            })

        return {
            "identity": "Nova",
            "developer": "Taji-Soft",
            "model_provider": "Ollama",
            "configured_model": str(model),
            "python_version": platform.python_version(),
            "platform": sys.platform,
            "tools": tools,
            "access": {
                key: bool(access.get(key, True))
                for key in ("web", "git", "pc")
            },
            "limitations": [
                "I am software; I should not claim human-like consciousness, feelings, or personal experiences.",
                "My abilities depend on tools registered in this running instance and their enabled permissions.",
                "A registered/enabled web-search tool does not guarantee that the network or website is reachable.",
                "The configured Ollama model name does not prove that the model is currently loaded or responding.",
                "Terminal execution is not a complete operating-system sandbox; scripts may act with the Nova process account's permissions.",
                "I must not claim a file, command, search, or other action succeeded without actual tool evidence.",
            ],
        }

    def context(self, core):
        state = self.snapshot(core)
        profile = runtime_profile(core)
        lines = [
            "Identity: Nova, a local AI agent developed by Taji-Soft.",
            f"Model provider: {state['model_provider']}.",
            f"Configured Ollama model: {state['configured_model']} (configuration only; not proof it is currently loaded).",
            f"Runtime: Python {state['python_version']} on {state['platform']}.",
            f"Configured generation budgets: context={profile['context_budget']} tokens; output={profile['output_budget']} tokens.",
            f"Agent components present: {profile['present_components']}/{profile['component_count']}.",
            "Component status (observed from this running instance):",
        ]
        for component in profile["components"]:
            status = "present" if component["present"] else "missing"
            lines.append(f"- {component['name']}: {component['implementation']} [{status}]")
        lines.append("Registered tools:")
        if state["tools"]:
            for tool in state["tools"]:
                status = "enabled" if tool["enabled"] else "disabled by capability permission"
                detail = f" — {tool['description']}" if tool["description"] else ""
                lines.append(f"- {tool['name']} [{tool['capability']}; {status}]{detail}")
        else:
            lines.append("- None registered.")
        lines.append("Access flags: " + ", ".join(
            f"{key}={'enabled' if value else 'disabled'}"
            for key, value in state["access"].items()
        ) + ".")
        lines.append("Limitations:")
        lines.extend(f"- {item}" for item in state["limitations"])
        lines.append("These are runtime observations, not evidence that a particular tool call has succeeded.")
        return "\n".join(lines)

    def answer(self, message, core):
        if not isinstance(message, str):
            return None
        text = re.sub(r"\s+", " ", message.strip().casefold())
        if not text:
            return None
        state = self.snapshot(core)

        parameter_question = bool(re.search(
            r"\bhow many parameters (?:do you have|does your model have|are in your model)\b|"
            r"\bparameter count\b|\bnumber of parameters\b|"
            r"(?:مدلت چند پارامتر داره|مدل تو چند پارامتر داره|چند پارامتر داری|تعداد پارامترهای مدل)",
            text,
        ))
        if parameter_question:
            model = inspect_model(core)
            if model["status"] == "available":
                return (
                    f"Ollama reports {model['parameter_count']} parameters for the configured model "
                    f"{model['configured_name']}. Reported model size: {model['parameter_size']}; "
                    f"architecture: {model['architecture']}; quantization: {model['quantization']}. "
                    "These are model metadata, not a count of parameters in Nova's Python agent code. "
                    "Metadata availability does not prove generation is working."
                )
            return (
                f"I cannot verify the parameter count for {model['configured_name']}: "
                f"{model['detail']} I will not guess it from the model tag."
            )

        model_question = bool(re.search(
            r"\b(?:what|which) model (?:are you using|do you use|is this)|"
            r"\bwhat is your model\b|\bwhich llm\b|\bwhat llm\b|"
            r"(?:از چه مدلی استفاده می.?کنی|مدلت چیه|چه مدلی هستی)",
            text,
        ))
        if model_question:
            return (
                f"My configured model provider is Ollama, with model name "
                f"{state['configured_model']}. This is the configured name; "
                "I have not verified from this answer alone that the model is currently loaded."
            )

        tools_question = bool(re.search(
            r"\b(?:what tools do you have|list your tools|what tools are available|"
            r"what are your capabilities|what can you do|what can i ask you to do|"
            r"what can you help me with|tell me about your capabilities)\b|"
            r"(?:چه ابزارهایی داری|چه کارهایی می.?تونی انجام بدی|قابلیت.?هات چیه)",
            text,
        ))
        if tools_question:
            active = [item["name"].replace("_", " ") for item in state["tools"] if item["enabled"]]
            inactive = [item["name"].replace("_", " ") for item in state["tools"] if not item["enabled"]]
            if active:
                result = "In this running instance, my enabled tools are: " + ", ".join(active) + "."
            else:
                result = "No tools are currently enabled in this running instance."
            if inactive:
                result += " Registered but permission-disabled tools: " + ", ".join(inactive) + "."
            result += " Tool availability does not guarantee that every call will succeed."
            return result

        web_question = bool(re.search(
            r"\b(?:can you|do you)\b.*\b(?:browse|search|access)\b.*\b(?:web|internet|online)\b|"
            r"\b(?:do you have|is)\b.*\b(?:internet|web access)\b|"
            r"(?:به اینترنت دسترسی داری|می.?تونی وب رو جستجو کنی)",
            text,
        ))
        if web_question:
            available = any(
                tool["name"] == "web_search" and tool["enabled"]
                for tool in state["tools"]
            )
            if available:
                return "The web_search tool is registered and enabled. Network access can still fail, so I need a real search result before claiming a search worked."
            return "Web search is not currently available to me: the web_search tool is missing or its permission is disabled."

        limitations_question = bool(re.search(
            r"\b(?:what are your limitations|what can.?t you do|what are you unable to do|"
            r"do you have limitations|are you conscious|are you sentient|do you have feelings)\b|"
            r"(?:محدودیت.?هات چیه|آگاهی انسانی داری|احساسات واقعی داری)",
            text,
        ))
        if limitations_question:
            return (
                "I'm software, not a human, and I shouldn't claim human-like consciousness, "
                "feelings, or personal experiences. My practical limits are the tools and "
                "permissions available in this run, possible model mistakes, and external "
                "services that may be unreachable. I must verify actions before saying they succeeded."
            )

        self_knowledge_question = bool(re.search(
            r"\b(?:what do you know about yourself|describe yourself accurately|"
            r"what is your current status|what do you know about your own system)\b|"
            r"(?:خودت رو معرفی کن|درباره خودت چی می.?دونی|وضعیت فعلیت چیه)",
            text,
        ))
        if self_knowledge_question:
            return self.context(core)

        return None
