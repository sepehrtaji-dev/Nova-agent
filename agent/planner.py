import json
import re


class Planner:
    def __init__(self, brain):
        self.brain = brain

    def _extract_json(self, response):
        if not response:
            return None

        response = str(response).strip()

        response = re.sub(
            r"^```json\s*",
            "",
            response,
            flags=re.IGNORECASE
        )
        response = re.sub(r"^```\s*", "", response)
        response = re.sub(r"\s*```$", "", response)

        try:
            data = json.loads(response)

            if isinstance(data, dict):
                return data

        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()

        for index, char in enumerate(response):
            if char != "{":
                continue

            try:
                data, _ = decoder.raw_decode(response[index:])

                if isinstance(data, dict):
                    return data

            except json.JSONDecodeError:
                continue

        return None

    def _normalize_steps(self, data):
        if not isinstance(data, dict):
            return []

        steps = data.get("steps", [])

        if not isinstance(steps, list):
            return []

        normalized = []

        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue

            description = step.get("description")

            if not isinstance(description, str):
                continue

            description = description.strip()

            if not description:
                continue

            normalized.append({
                "id": index,
                "description": description,
                "status": "pending",
                "result": None
            })

        return normalized

    def create_plan(self, goal, context=None):
        if not isinstance(goal, str) or not goal.strip():
            return {
                "goal": "",
                "steps": []
            }

        context = context or ""

        prompt = f"""
You are Nova's task planner.

Your job is to break the user's goal into clear,
ordered, actionable steps.

User goal:
{goal}

Additional context:
{context}

Rules:

- Do not execute tools.
- Do not write code.
- Do not pretend that an action was completed.
- Do not invent results.
- Break complex tasks into logical steps.
- Keep simple tasks simple.
- Steps must be ordered.
- Each step should describe one meaningful action.
- Do not include unnecessary conversational steps.
- The plan should be useful for another component
  that will execute the steps later.

Return JSON only.

Schema:
{{
  "goal": "short description of the overall goal",
  "steps": [
    {{
      "description": "first action"
    }},
    {{
      "description": "second action"
    }}
  ]
}}
"""

        raw = self.brain.generate(prompt, json_mode=True)

        data = self._extract_json(raw)

        if not isinstance(data, dict):
            return {
                "goal": goal.strip(),
                "steps": []
            }

        steps = self._normalize_steps(data)

        return {
            "goal": str(
                data.get("goal") or goal
            ).strip(),
            "steps": steps
        }

    def update_step(self, plan, step_id, result, status="completed"):
        if not isinstance(plan, dict):
            return plan

        steps = plan.get("steps", [])

        if not isinstance(steps, list):
            return plan

        for step in steps:
            if not isinstance(step, dict):
                continue

            if step.get("id") == step_id:
                step["status"] = status
                step["result"] = result
                break

        return plan

    def get_next_step(self, plan):
        if not isinstance(plan, dict):
            return None

        steps = plan.get("steps", [])

        if not isinstance(steps, list):
            return None

        for step in steps:
            if not isinstance(step, dict):
                continue

            if step.get("status") == "pending":
                return step

        return None

    def is_complete(self, plan):
        if not isinstance(plan, dict):
            return False

        steps = plan.get("steps", [])

        if not steps:
            return False

        return all(
            isinstance(step, dict)
            and step.get("status") == "completed"
            for step in steps
        )

    def get_plan_summary(self, plan):
        if not isinstance(plan, dict):
            return "No plan."

        goal = plan.get("goal", "Unknown goal")
        steps = plan.get("steps", [])

        lines = [
            f"Goal: {goal}",
            ""
        ]

        for step in steps:
            if not isinstance(step, dict):
                continue

            step_id = step.get("id", "?")
            description = step.get(
                "description",
                "Unknown step"
            )
            status = step.get("status", "pending")

            lines.append(
                f"{step_id}. [{status}] {description}"
            )

        return "\n".join(lines)