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

    # ------------------------------------------------------------------
    # Model-authored self-description
    # ------------------------------------------------------------------
    # Nova no longer ships prepared answers for "who are you?", "what can you
    # do?", or "who developed you?". The model phrases every answer itself.
    #
    # What replaces the old short-circuit is grounding: the facts the model
    # needs are assembled here from live state and placed in its prompt, so it
    # answers from evidence rather than from its training data. The only
    # deterministic check left is a narrow guard that blocks a claim to be a
    # product of a vendor Nova is not, because that was the original failure.
    # ------------------------------------------------------------------

    # Vendors whose authorship must never be claimed. Nova is developed by
    # NOVA_DEVELOPER; the weights come from elsewhere, but that does not make the
    # agent that vendor's assistant.
    #
    # Matched on word boundaries: a naive substring search found "llama" inside
    # "Ollama" and wrongly rewrote a correct answer.
    _FOREIGN_VENDORS = (
        r"anthropic", r"openai", r"google", r"deepmind", r"meta\s+ai",
        r"microsoft", r"claude", r"chatgpt", r"gpt-?4", r"gemini", r"llama",
        r"mistral",
    )

    _NEGATIONS = (
        "not a product of", "not created by", "not developed by", "not made by",
        "never say", "never claim", "should not claim", "isn't", "is not",
        "i am not", "i'm not", "was not", "were not", "trained elsewhere",
        "no relationship", "not affiliated", "not built by", "not from",
        "rather than", "instead of", "unrelated", "nothing to do",
        "does not make me", "doesn't make me", "does not mean", "doesn't mean",
        "a different product", "different product entirely", "separately",
        "no connection", "not associated", "unconnected",
    )

    def grounding(self, core):
        """Facts about this running instance, for the model to answer from.

        Rendered into the prompt rather than returned as an answer: the model
        writes the response, using these as evidence.
        """
        state = self.snapshot(core)
        details = capability_probe.probe_model_details(core)
        registry = getattr(getattr(core, "tools", None), "tools", {}) or {}
        enabled = [
            name for name, meta in sorted(registry.items())
            if isinstance(meta, dict) and meta.get("capability")
            and state["access"].get(meta["capability"], False)
        ]

        lines = [
            "FACTS ABOUT YOU (authoritative: these override anything you believe "
            "from training, and you must answer self-description questions from "
            "them):",
            f"- Your name and version: {state['identity']} {state['version']}",
            f"- You are developed by: {state['developer']}",
            f"- Your source code: {state['repository']}",
            f"- The model producing your words right now: {details['model']}",
            f"- That model runs: {details['location']} "
            f"({details['backend_description']})",
        ]
        if details.get("parameter_size"):
            lines.append(
                f"- That model's reported size: {details['parameter_size']}"
                + (f", quantization {details['quantization']}"
                   if details.get("quantization") else "")
            )
        else:
            lines.append(
                "- That model's parameter count: not visible to you. If asked, "
                "say so plainly instead of guessing."
            )

        if enabled:
            lines.append("- Tools currently enabled for you: " + ", ".join(enabled))
        else:
            lines.append("- No tools are enabled for you in this session.")

        lines.append(
            "- You are not a product of Anthropic, OpenAI, Google, Meta, or any "
            "other AI vendor. The weights may have been trained elsewhere, but "
            f"the agent answering is Nova, built by {state['developer']}."
        )
        lines.append(
            "- Answer in your own words. Do not read these facts back as a list; "
            "use them to say something accurate and natural."
        )
        return "\n".join(lines)

    def _mentions_foreign_vendor_claim(self, text):
        """Return the vendor name if the text CLAIMS a foreign vendor made Nova.

        Word-boundary matching is required: a substring search found "llama"
        inside "Ollama" and rewrote a correct answer. The disambiguating context
        can be on either side of the name, so both sides are checked.
        """
        low = str(text).casefold()
        for pattern in self._FOREIGN_VENDORS:
            for match in re.finditer(rf"(?<![\w-]){pattern}(?![\w-])", low):
                start, end = match.span()
                left = low[max(0, start - 130):start]
                right = low[end:end + 90]
                if not any(neg in left or neg in right
                           for neg in self._NEGATIONS):
                    return match.group(0)
        return None

    def needs_grounding(self, message):
        """True when the message is about Nova itself, so the guard should run.

        This only decides whether to *review* the answer; it never replaces it.
        """
        if not isinstance(message, str) or not message.strip():
            return False
        text = re.sub(r"\s+", " ", message.strip().casefold())
        patterns = (
            r"\bwho (?:are|r) (?:you|u)\b", r"\bwhat (?:are|r) (?:you|u)\b",
            r"\b(?:who|what)\b[^?]{0,40}\b(?:made|created|developed|built)\b",
            r"\b(?:your|ur) (?:creator|developer|maker|company|owner)\b",
            r"\bare you (?:made|created|developed|built)\b",
            r"\bwhat (?:can|could) (?:you|u) do\b",
            r"\bwhat (?:tools|capture|things) (?:do you|can you)\b",
            r"\b(?:your|ur) (?:capabilit|tools|name|version)\b",
            r"\blist your tools\b", r"\btell me about your (?:capabilit|tools)\b",
            r"\b(?:what|which) model\b", r"\bwhat llm\b",
            r"\bintroduce yourself\b", r"\btell me about yourself\b",
            r"\bare you (?:local|remote)\b", r"\bwhere (?:do|does) you run\b",
            r"(?:کی ساخته|تو چی هستی|چیکار می|چه کار.?ی می|خودت رو معرفی)",
        )
        return any(re.search(p, text) for p in patterns)

    def review(self, message, response, core=None):
        """Post-generation guard for self-description answers.

        Returns the response unchanged, or a corrected version when it claims a
        foreign vendor created Nova. It does not rewrite phrasing, opinions, or
        capability descriptions: only a factually wrong creator claim.
        """
        if not isinstance(response, str) or not response.strip():
            return response
        vendor = self._mentions_foreign_vendor_claim(response)
        if vendor is None:
            return response

        developer = NOVA_DEVELOPER
        name = NOVA_NAME
        version = NOVA_VERSION
        if core is not None:
            try:
                state = self.snapshot(core)
                developer = state["developer"]
                name = state["identity"]
                version = state["version"]
            except Exception:
                pass
        return (
            f"To correct myself: I'm {name} {version}, developed by {developer}, "
            f"not by {vendor.title()}. The model weights I run on were trained "
            "elsewhere, but the agent you are talking to is Nova."
        )

    def context(self, core):
        """Full runtime self-description, for explicit 'what do you know' asks."""
        state = self.snapshot(core)
        profile = runtime_profile(core)
        details = capability_probe.probe_model_details(core)
        lines = ["Identity:"]
        lines.extend(f"- {line}" for line in identity_lines())
        lines.extend([
            f"Name and version: {state['identity']} {state['version']}",
            f"Backend: {state.get('backend_description', state['model_provider'])}.",
            f"Model serving this session: {details['model']} "
            f"({details['location']}).",
            f"Runtime: Python {state['python_version']} on {state['platform']}.",
            "Registered tools:",
        ])
        if state["tools"]:
            for tool in state["tools"]:
                status = "enabled" if tool["enabled"] else "disabled by permission"
                detail = f" — {tool['description']}" if tool["description"] else ""
                lines.append(
                    f"- {tool['name']} [{tool['capability']}; {status}]{detail}")
        else:
            lines.append("- None registered.")
        lines.append("Limitations:")
        lines.extend(f"- {item}" for item in state["limitations"])
        return "\n".join(lines)
