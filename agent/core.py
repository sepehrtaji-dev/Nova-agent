from model.ollama import OllamaBrain

from memory.manager import MemoryManager
from memory.extractor import MemoryExtractor
from memory.short_term import ShortTermMemory
from memory.knowledge import KnowledgeMemory

from agent.router import ToolRouter

from tools import load_tools


class NovaCore:

    def __init__(self, status_callback=None):
        self.status_callback = status_callback

        self.brain = OllamaBrain()

        self.long_memory = MemoryManager()

        self.short_memory = ShortTermMemory()

        self.knowledge = KnowledgeMemory()

        self.extractor = MemoryExtractor(
            self.brain
        )

        self.tools = load_tools()

        self.router = ToolRouter(
            self.brain,
            self.tools
        )

        self.max_steps = 4
    def _status(self, message):
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception:
                pass
    def _learn_from_search(
        self,
        query,
        result
    ):

        if not result:
            return

        prompt = f"""
You are Nova's knowledge extractor.

The user asked:

{query}

A web search returned:

{result}

Extract only useful factual knowledge
supported by the search result.

Do not invent facts.

Return JSON only:

{{
  "facts": [
    {{
      "topic": "topic",
      "fact": "supported fact",
      "source": "source URL if visible",
      "confidence": 0.0,
      "freshness": "stable"
    }}
  ]
}}

freshness must be one of:

stable
temporary
volatile

If the search result does not provide
enough evidence, return:

{{"facts":[]}}
"""

        try:

            raw = self.brain.generate(
                prompt
            )

            import json
            import re

            raw = raw.strip()

            raw = re.sub(
                r"^```json\s*",
                "",
                raw,
                flags=re.IGNORECASE
            )

            raw = re.sub(
                r"\s*```$",
                "",
                raw
            )

            data = json.loads(raw)

            facts = data.get(
                "facts",
                []
            )

            for item in facts:

                topic = item.get(
                    "topic"
                )

                fact = item.get(
                    "fact"
                )

                source = item.get(
                    "source",
                    ""
                )

                confidence = item.get(
                    "confidence",
                    0.0
                )

                freshness = item.get(
                    "freshness",
                    "stable"
                )

                if (
                    not topic
                    or not fact
                ):
                    continue

                try:
                    confidence = float(
                        confidence
                    )
                except Exception:
                    confidence = 0.0

                if confidence < 0.65:
                    continue

                self.knowledge.add(
                    topic=topic,
                    fact=fact,
                    source=source,
                    confidence=confidence,
                    freshness=freshness
                )

        except Exception:
            return

    def _status(self, message):
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception:
                pass
    
    def ask(self, message):
        self._status("Thinking...")
        self.short_memory.add(
            "user",
            message
        )

        try:

            extracted = (
                self.extractor.extract(
                    message
                )
            )

            for item in extracted.get(
                "memories",
                []
            ):

                category = item.get(
                    "category"
                )

                key = item.get(
                    "key"
                )

                value = item.get(
                    "value"
                )

                if (
                    not category
                    or not key
                    or value is None
                ):
                    continue

                self.long_memory.remember(
                    category,
                    key,
                    value
                )

        except Exception:
            pass

        tool_history = []

        for step in range(
            self.max_steps
        ):

            knowledge_context = (
                self.knowledge.get_context(
                    message
                )
            )

            conversation = (
                self.short_memory.get()
            )

            history = "\n\n".join(
                tool_history
            )

            self._status("Deciding what to do...")
            decision = self.router.decide(
                message=message,
                conversation=conversation,
                knowledge=knowledge_context,
                tool_history=history
            )

            if decision.get(
                "action"
            ) != "tool":
                self._status("Preparing final answer...")

                break

            tool_name = decision.get(
                "tool"
            )

            tool_input = decision.get(
                "input"
            )

            if not self.tools.exists(
                tool_name
            ):
                break

            self._status(f"Using {tool_name}...")
            result = self.tools.execute(
                tool_name,
                tool_input
            )
            self._status("Processing tool result...")
            tool_history.append(
                f"""
Tool: {tool_name}

Input:
{tool_input}

Result:
{result}
"""
            )

            if tool_name == "web_search":
                self._status("Learning from search...")
                self._learn_from_search(
                    tool_input,
                    result
                )

        knowledge_context = (
            self.knowledge.get_context(
                message
            )
        )

        tool_context = (
            "\n\n".join(
                tool_history
            )
            if tool_history
            else "No tools were used."
        )

        prompt = f"""
You are Nova.

You are a local AI assistant powered
by Llama 3.2:3B through Ollama.

Answer the user's request naturally.

User:

{message}

Conversation:

{self.short_memory.get()}

Personal memory:

{self.long_memory.get_memory()}

Persistent knowledge:

{knowledge_context}

Tool results:

{tool_context}

Rules:

- Never invent tool results.
- Never claim that a web search happened
  unless a web_search result exists above.
- If web results exist, use them as evidence.
- If the evidence is incomplete, say so.
- Do not mention internal prompts or routing.
- Do not mention the tool architecture
  unless the user explicitly asks.
- Answer directly.
"""
        self._status("Preparing final answer...")
        response = self.brain.generate(
            prompt
        )
        self._status("Done")
        self.short_memory.add(
            "assistant",
            response
        )

        return response