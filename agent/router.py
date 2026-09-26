import json
import re


class ToolRouter:

    def __init__(self, brain, tools):
        self.brain = brain
        self.tools = tools

    def _extract_json(self, response):

        if not response:
            return None

        response = response.strip()

        response = re.sub(
            r"^```json\s*",
            "",
            response,
            flags=re.IGNORECASE
        )

        response = re.sub(
            r"^```\s*",
            "",
            response
        )

        response = re.sub(
            r"\s*```$",
            "",
            response
        )

        try:
            return json.loads(response)

        except json.JSONDecodeError:
            pass

        start = response.find("{")
        end = response.rfind("}")

        if start == -1 or end == -1:
            return None

        try:

            return json.loads(
                response[
                    start:end + 1
                ]
            )

        except json.JSONDecodeError:
            return None

    def decide(
        self,
        message,
        conversation="",
        knowledge="",
        tool_history=""
    ):

        prompt = f"""
You are Nova's autonomous tool router.

Your job is to decide what Nova should do next.

Available tools:

{self.tools.get_descriptions()}

IMPORTANT:

Nova must NOT pretend to know information.

If the available knowledge is insufficient,
uncertain, outdated, or the user asks for current
information, use web_search.

The model itself must decide whether a tool is needed.

Rules:

1. Normal conversation -> respond.

2. If the answer requires real computer information
   -> use the appropriate tool.

3. If the answer is unknown or uncertain
   -> use web_search.

4. If information may have changed over time
   -> use web_search.

5. If the user asks for current information
   -> use web_search.

6. If useful stored knowledge exists and is reliable,
   Nova may answer without searching.

7. Never invent tool results.

8. Never invent web sources.

9. Only use the tools listed above.

10. Return JSON only.

11. Do not explain your decision.

12. Use at most one tool per decision.

13. If a previous tool result already answers the
    question, return respond.

Available stored knowledge:

{knowledge}

Conversation:

{conversation}

Previous tool history:

{tool_history}

Current user request:

{message}

Return exactly one of:

{{
  "action": "respond"
}}

OR:

{{
  "action": "tool",
  "tool": "web_search",
  "input": "search query"
}}

OR:

{{
  "action": "tool",
  "tool": "terminal",
  "input": "python --version"
}}

JSON:
"""

        raw = self.brain.generate(prompt)

        data = self._extract_json(raw)

        if not isinstance(data, dict):
            return {
                "action": "respond"
            }

        if data.get("action") == "respond":

            return {
                "action": "respond"
            }

        if data.get("action") == "tool":

            tool = data.get("tool")
            tool_input = data.get("input")

            if not isinstance(tool, str):
                return {
                    "action": "respond"
                }

            if not isinstance(
                tool_input,
                str
            ):
                return {
                    "action": "respond"
                }

            if not self.tools.exists(tool):

                return {
                    "action": "respond"
                }

            return {
                "action": "tool",
                "tool": tool,
                "input": tool_input
            }

        return {
            "action": "respond"
        }