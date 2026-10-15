"""Evidence-based runtime self-knowledge for Nova.

Product identity comes from agent.identity; everything the running process can
measure (registered tools, model metadata, network reachability) is probed live
so a stale declaration can never be reported as a current capability.
"""
import platform
import re
import sys

from agent import capability_probe
from agent.identity import (
    NOVA_CAPABILITIES,
    NOVA_DEVELOPER,
    NOVA_NAME,
    NOVA_REPOSITORY,
    NOVA_VERSION,
    identity_lines,
    identity_sentence,
)
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

        # Report the backend actually in use. Hardcoding "Ollama" would make Nova
        # describe itself incorrectly whenever a remote provider is configured.
        try:
            from model.provider import backend_kind, describe_brain

            kind = backend_kind(brain)
            provider_description = describe_brain(brain)
        except Exception:
            kind = "local"
            provider_description = "Ollama"

        details = capability_probe.probe_model_details(core)

        return {
            "identity": NOVA_NAME,
            "version": NOVA_VERSION,
            "developer": NOVA_DEVELOPER,
            "repository": NOVA_REPOSITORY,
            "capabilities": list(NOVA_CAPABILITIES),
            "model_provider": "Ollama" if kind == "local" else "remote API",
            "backend_kind": kind,
            "backend_description": provider_description,
            "configured_model": str(model),
            # Runtime facts, probed rather than asserted. Unknown values stay
            # None so nothing downstream can state them as if they were known.
            "model_location": details.get("location"),
            "model_parameter_size": details.get("parameter_size"),
            "model_parameter_count": details.get("parameter_count"),
            "model_quantization": details.get("quantization"),
            "model_architecture": details.get("architecture"),
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
                "The configured model name does not prove that the model is currently loaded or responding.",
                "Terminal execution is not a complete operating-system sandbox; scripts may act with the Nova process account's permissions.",
                "I must not claim a file, command, search, or other action succeeded without actual tool evidence.",
                "When a remote provider is configured, conversation content and tool results are sent to that provider's servers.",
            ],
        }

    def context(self, core):
        state = self.snapshot(core)
        profile = runtime_profile(core)
        lines = [
            "Identity:",
        ]
        lines.extend(f"- {line}" for line in identity_lines())
        lines.extend([
            f"Model provider: {state['model_provider']}.",
            f"Configured model: {state['configured_model']} (configuration only; not proof it is currently loaded).",
            f"Backend: {state.get('backend_description', state['model_provider'])}.",
            f"Runtime: Python {state['python_version']} on {state['platform']}.",
            f"Configured generation budgets: context={profile['context_budget']} tokens; output={profile['output_budget']} tokens.",
            f"Agent components present: {profile['present_components']}/{profile['component_count']}.",
            "Component status (observed from this running instance):",
        ])
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

    def _web_probe(self):
        """Reachability probe, overridable in tests to avoid real network use."""
        return capability_probe.probe_web()

    def _web_answer(self, core, state):
        """Answer 'can you search?' by actually testing, not reading config.

        A registered tool proves only that code exists. This probes the network
        so the answer reflects what Nova can do in this run.
        """
        registered = any(
            item["name"] == "web_search" for item in state["tools"]
        )
        allowed = bool(state["access"].get("web", False))

        if not registered:
            return (
                "No web search is available: the web_search tool is not "
                "registered in this build."
            )
        if not allowed:
            return (
                "I have a web_search tool, but the 'web' capability is turned "
                "off by permission in this session, so I cannot search right now. "
                "Enable it in the capability settings and I can."
            )

        probe = self._web_probe()
        if probe.get("reachable"):
            return (
                "Yes — I can search the web. I just verified it: "
                f"{probe.get('detail')} "
                "The web_search tool is registered, the 'web' capability is "
                "enabled, and the network responded to a live probe. Ask me to "
                "search something and I will run a real search and cite the "
                "sources I actually get back."
            )
        return (
            "I have web search enabled and the tool is registered, but I could "
            f"not reach the network just now: {probe.get('detail')}. "
            "So right now a search would likely fail. I will not claim a search "
            "worked unless a real result comes back."
        )

    def _capability_report(self, core, state):
        """Report capabilities from identity plus live probes."""
        lines = [identity_sentence(), "", "What I can do in this run:"]

        probe = self._web_probe()
        if probe.get("reachable"):
            web_state = f"working ({probe.get('detail')})"
        elif probe.get("status") == "unreachable":
            web_state = f"not working right now ({probe.get('detail')})"
        else:
            web_state = f"unverified ({probe.get('detail')})"
        lines.append(f"- Search the web: {web_state}")

        coding = capability_probe.probe_coding()
        lines.append(f"- Write and run code: {coding.get('status')} "
                     f"({coding.get('detail')})")

        maths = capability_probe.probe_math()
        lines.append(f"- Solve math: {maths.get('status')} "
                     f"({maths.get('detail')})")

        active = [item["name"] for item in state["tools"] if item["enabled"]]
        inactive = [item["name"] for item in state["tools"] if not item["enabled"]]
        if active:
            lines.append("Enabled tools: " + ", ".join(active) + ".")
        else:
            lines.append("No tools are enabled in this run.")
        if inactive:
            lines.append("Permission-disabled tools: " + ", ".join(inactive) + ".")

        ollama = capability_probe.probe_ollama()
        if ollama.get("reachable"):
            lines.append(
                f"Local model server: running "
                f"({len(ollama.get('models', []))} model(s) installed)."
            )
        else:
            lines.append(f"Local model server: {ollama.get('detail')}")

        lines.append(
            "These are live probe results from this session, not cached claims."
        )
        return "\n".join(lines)

    def answer(self, message, core):
        if not isinstance(message, str):
            return None
        text = re.sub(r"\s+", " ", message.strip().casefold())
        if not text:
            return None
        state = self.snapshot(core)

        identity_question = bool(re.search(
            r"\b(?:who|what)\b[^?]{0,40}\b(?:made|created|developed|built|owns|"
            r"designed|trained|behind)\b[^?]{0,20}\b(?:you|u|nova|this)\b|"
            r"\b(?:who|what) (?:are|r) (?:you|u)\b|"
            r"\b(?:your|ur) (?:creator|developer|maker|company|owner|parent|"
            r"name|version)\b|"
            r"\bare you (?:made|created|developed|built|from|by)\b|"
            r"\b(?:are|r) (?:you|u) (?:anthropic|openai|google|meta|claude|gpt|gemini|llama)\b|"
            r"\b(?:who is|what is) (?:taji|nova)\b|"
            r"\bwhat version (?:are you|is nova|is this)\b|"
            r"\b(?:what|which) version\b[^?]{0,20}\b(?:you|nova|this)\b|"
            r"\btell me about (?:yourself|nova)\b|"
            r"\bintroduce yourself\b|"
            r"\bwhere (?:are you|is your) (?:source|code|repo|repository)\b|"
            r"\bare you open ?source\b|\b(?:github|repo|repository)\b[^?]{0,20}\bnova\b|"
            r"(?:تو رو کی ساخته|کی ساخته تورو|سازنده.?ت کیه|تو چی هستی|مال کدوم شرکتی|"
            r"خودت رو معرفی کن|نسخه.?ت چیه)",
            text,
        ))
        if identity_question:
            lines = [
                f"I'm {state['identity']} {state['version']}, developed by "
                f"{state['developer']}.",
                f"I'm open source: {state['repository']}.",
                "I can search the web, write and run code, and solve math "
                "questions when those tools are enabled.",
                capability_probe.describe_model(core),
                "I am not a product of Anthropic, OpenAI, Google, Meta, or any "
                "other AI vendor, and I should not claim to be one. The "
                "underlying model weights were trained elsewhere, but the agent "
                "you are talking to was built and configured by "
                f"{state['developer']}.",
            ]
            return " ".join(lines)

        parameter_question = bool(re.search(
            r"\bhow many parameters (?:do you have|does your model have|are in your model)\b|"
            r"\bparameter count\b|\bnumber of parameters\b|\bhow big are you\b|"
            r"(?:مدلت چند پارامتر داره|مدل تو چند پارامتر داره|چند پارامتر داری|تعداد پارامترهای مدل)",
            text,
        ))
        if parameter_question:
            details = capability_probe.probe_model_details(core)
            model_name = details.get("model", "the configured model")
            size = details.get("parameter_size")
            count = details.get("parameter_count")

            if details.get("backend_kind") == "remote":
                return (
                    f"I can't state a parameter count for {model_name}: it runs "
                    "on the provider's servers, and that metadata is not visible "
                    "to me. I won't guess it from the model name."
                )
            if size or count:
                parts = [f"The model serving this session, {model_name}, reports "
                         f"a size of {size or count}"]
                for label, key in (("architecture", "architecture"),
                                   ("quantization", "quantization")):
                    if details.get(key):
                        parts.append(f"{label} {details[key]}")
                return (
                    ", ".join(parts) + ". This is model metadata reported by the "
                    "local runtime, not a count of parameters in Nova's Python "
                    "agent code. Metadata availability does not prove generation "
                    "is working."
                )
            return (
                f"I cannot verify a parameter count for {model_name}: the local "
                "runtime returned no size metadata. I will not guess it from the "
                "model tag."
            )

        # Match the many ways a user asks this. The previous pattern required
        # "what model" to be adjacent, so "what is the exact name of your model"
        # fell through to the model, which then invented an answer from context.
        model_question = bool(re.search(
            r"\b(?:what|which) model\b|"
            r"\bmodel (?:name|id)\b|"
            r"\bname (?:of )?(?:your|the) model\b|"
            r"\b(?:your|the) model(?:'s)? name\b|"
            r"\bwhat (?:is your|model) model\b|\bwhich llm\b|\bwhat llm\b|"
            r"\bwhat ai (?:are you|model)\b|"
            r"\bwhat(?:'s| is) the exact name\b[^?]{0,40}\bmodel\b|"
            r"\bexact(?:ly)? (?:model|name)\b[^?]{0,30}\bmodel\b|"
            r"\bwhat(?:'s| is) the exact\b[^?]{0,30}\bmodel\b|"
            r"\bexact model\b|"
            r"\bwhat model (?:are you using|do you use|is this|are you|"
            r"do you run|is it)\b|"
            r"(?:از چه مدلی استفاده می.?کنی|مدلت چیه|چه مدلی هستی|"
            r"چه مدلی استفاده می.?کنی|اسم مدلت چیه)",
            text,
        ))
        if model_question:
            return (
                f"I'm Nova {state['version']}. My reasoning runs on the model "
                f"'{state['configured_model']}' via "
                f"{state.get('backend_description', state['model_provider'])}. "
                "This is the configured model; I have not verified from this "
                "answer alone that it is currently loaded and responding."
            )

        tools_question = bool(re.search(
            r"\b(?:what tools do you have|list your tools|what tools are available|"
            r"what are your capabilities|what can you do|what can i ask you to do|"
            r"what can you help me with|tell me about your capabilities)\b|"
            r"(?:چه ابزارهایی داری|چه کارهایی می.?تونی انجام بدی|قابلیت.?هات چیه)",
            text,
        ))
        if tools_question:
            return self._capability_report(core, state)

        location_question = bool(re.search(
            r"\bare you (?:local|remote|online|offline)\b|"
            r"\blocal or remote\b|\bremote or local\b|"
            r"\bdo you run (?:locally|on my (?:computer|machine|pc))\b|"
            r"\bwhere do you run\b|\bwhere are you running\b|"
            r"\bis my data (?:sent|leaving|leaving my (?:computer|machine))\b|"
            r"\bdoes anything leave (?:my|this) (?:computer|machine|pc)\b|"
            r"(?:لوکال هستی یا ریموت|کجا اجرا می.?شی|رو سیستم من اجرا می.?شی)",
            text,
        ))
        if location_question:
            details = capability_probe.probe_model_details(core)
            if details.get("backend_kind") == "remote":
                return (
                    f"I'm Nova, and my reasoning currently runs on the remote "
                    f"model '{details['model']}' {details['location']}. "
                    "That means your messages, the file contents you ask me to "
                    "read, and tool results are sent to that provider. My tools "
                    "still execute locally on this computer. Switch to a local "
                    "Ollama model in API settings if you want nothing to leave "
                    "this machine."
                )
            return (
                f"I'm Nova, running fully on this computer. My reasoning runs on "
                f"the local model '{details['model']}' through Ollama, and my "
                "tools execute here too. Nothing is sent to a remote provider."
            )

        web_question = bool(re.search(
            r"\b(?:can|do|could)\s+(?:you|u|nova)\b[^?]{0,40}\b(?:browse|search|"
            r"google|look\s+up|access)\b|"
            r"\b(?:do you have|is there|is)\b[^?]{0,30}\b(?:internet|web|online)\s*"
            r"(?:access|connection|connectivity)?\b|"
            r"\bare you able to\b[^?]{0,40}\b(?:search|browse|look\s+up)\b|"
            r"\bcan (?:you|u) (?:use|reach) the (?:web|internet)\b|"
            r"(?:به اینترنت دسترسی داری|می.?تونی وب رو جستجو کنی|می.?تونی سرچ کنی)",
            text,
        ))
        if web_question:
            return self._web_answer(core, state)

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
