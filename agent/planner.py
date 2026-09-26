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
            r"^\s*```json\s*",
            "",
            response,
            flags=re.IGNORECASE
        )

        response = re.sub(
            r"^\s*```\s*",
            "",
            response
        )

        response = re.sub(
            r"\s*```\s*$",
            "",
            response
        ).strip()

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
                data, _ = decoder.raw_decode(
                    response[index:]
                )

                if isinstance(data, dict):
                    return data

            except json.JSONDecodeError:
                continue

        return None

    def _normalize_steps(self, steps):
        if not isinstance(steps, list):
            return []

        normalized = []

        for index, step in enumerate(
            steps,
            start=1
        ):
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

    def create_plan(self, goal, context=""):
        if not isinstance(goal, str):
            return {
                "goal": "",
                "steps": []
            }

        goal = goal.strip()

        if not goal:
            return {
                "goal": "",
                "steps": []
            }

        prompt = f"""
You are Nova's task planner.

Create an actionable plan for the user's goal.

USER GOAL:
{goal}

CONTEXT:
{context}

Rules:
- Break complex work into meaningful ordered steps.
- Keep simple requests simple.
- Do not execute tools.
- Do not claim anything is completed.
- Do not invent results.
- Each step must describe one meaningful action.
- The plan will be executed by another component.
- Return JSON only.

Schema:
{{
  "goal": "short overall goal",
  "steps": [
    {{
      "description": "action to perform"
    }}
  ]
}}
"""

        try:
            print("\n[PLANNER] Creating plan...")

            raw = self.brain.generate(
                prompt,
                json_mode=True
            )

            print("[PLANNER] Plan received.")

        except Exception as e:
            print(
                f"[PLANNER] Create plan error: "
                f"{type(e).__name__}: {e}"
            )

            return {
                "goal": goal,
                "steps": []
            }

        data = self._extract_json(raw)

        if not isinstance(data, dict):
            print(
                "[PLANNER] Invalid JSON plan."
            )

            return {
                "goal": goal,
                "steps": []
            }

        steps = self._normalize_steps(
            data.get("steps")
        )

        return {
            "goal": str(
                data.get("goal") or goal
            ).strip(),
            "steps": steps
        }

    def replan(
        self,
        plan,
        goal,
        tool_name,
        tool_input,
        result,
        success
    ):
        if not isinstance(plan, dict):
            return plan

        steps = plan.get("steps", [])

        if not isinstance(steps, list):
            return plan

        if not steps:
            return plan

        previous_plan = json.loads(
            json.dumps(
                plan,
                ensure_ascii=False
            )
        )

        old_completed = [
            step
            for step in steps
            if (
                isinstance(step, dict)
                and step.get("status") == "completed"
            )
        ]

        old_completed_count = len(
            old_completed
        )

        current_step = None

        for step in steps:
            if not isinstance(step, dict):
                continue

            if step.get("status") != "completed":
                current_step = step
                break

        current_step_id = (
            current_step.get("id")
            if current_step
            else None
        )

        current_step_description = ""

        if current_step:
            current_step_description = str(
                current_step.get("description", "")
            ).strip()

        prompt = f"""
You are Nova's task planner.

Update the existing plan using the REAL tool result.

USER GOAL:
{goal}

CURRENT PLAN:
{json.dumps(
    plan,
    ensure_ascii=False,
    indent=2
)}

LATEST TOOL:
{tool_name}

TOOL INPUT:
{tool_input}

REAL TOOL RESULT:
{result}

TOOL SUCCESS:
{success}

CURRENT STEP ID:
{current_step_id}

CURRENT STEP:
{current_step_description}

Rules:

- Never invent a tool result.
- Never invent a successful operation.
- Preserve every completed step.
- A completed step MUST remain completed.
- NEVER reopen a completed step.
- NEVER remove a completed step.
- If the latest tool successfully performed the current step,
  mark that step completed.
- If the latest tool failed,
  keep the relevant step pending.
- Add a new step only if the REAL result proves that it is necessary.
- Do not execute tools.
- Do not claim the overall goal is complete unless all required
  steps are actually complete.
- Return JSON only.

Schema:
{{
  "goal": "overall goal",
  "steps": [
    {{
      "description": "action",
      "status": "pending"
    }}
  ]
}}
"""

        try:
            print("\n[PLANNER] Replanning...")
            print(
                f"[PLANNER] Tool: {tool_name}"
            )
            print(
                f"[PLANNER] Success: {success}"
            )
            print(
                "[PLANNER] Sending result to Qwen..."
            )

            raw = self.brain.generate(
                prompt,
                json_mode=True
            )

            print(
                "[PLANNER] Qwen response received."
            )

        except Exception as e:
            print(
                f"[PLANNER] Replan error: "
                f"{type(e).__name__}: {e}"
            )

            return previous_plan

        data = self._extract_json(raw)

        if not isinstance(data, dict):
            print(
                "[PLANNER] Replan returned invalid JSON."
            )

            return previous_plan

        new_steps = self._normalize_replanned_steps(
            data.get("steps"),
            previous_plan
        )

        if not new_steps:
            print(
                "[PLANNER] Replan returned no steps."
            )

            return previous_plan

        old_completed_descriptions = {
            str(
                step.get("description", "")
            ).strip().lower()
            for step in old_completed
        }

        for step in new_steps:
            description = str(
                step.get("description", "")
            ).strip().lower()

            if (
                description
                in old_completed_descriptions
            ):
                step["status"] = "completed"

                matching_old = next(
                    (
                        old
                        for old in old_completed
                        if str(
                            old.get(
                                "description",
                                ""
                            )
                        ).strip().lower()
                        == description
                    ),
                    None
                )

                if matching_old:
                    step["result"] = (
                        matching_old.get("result")
                    )

        if success and current_step:
            matched = False

            for step in new_steps:
                new_description = str(
                    step.get("description", "")
                ).strip().lower()

                if (
                    new_description
                    == current_step_description.lower()
                ):
                    step["status"] = "completed"
                    step["result"] = result
                    matched = True
                    break

            if not matched:
                print(
                    "[PLANNER] Current step description "
                    "changed during replanning."
                )

        new_completed_count = sum(
            1
            for step in new_steps
            if (
                isinstance(step, dict)
                and step.get("status") == "completed"
            )
        )

        if new_completed_count < old_completed_count:
            print(
                "[PLANNER] Replan attempted to "
                "remove completed progress."
            )

            print(
                "[PLANNER] Keeping previous plan."
            )

            return previous_plan

        result_plan = {
            "goal": str(
                data.get("goal")
                or plan.get("goal")
                or goal
            ).strip(),
            "steps": new_steps
        }

        print(
            "[PLANNER] Replan completed."
        )

        return result_plan

    def _normalize_replanned_steps(
        self,
        steps,
        old_plan
    ):
        if not isinstance(steps, list):
            return []

        old_by_description = {}

        for step in old_plan.get(
            "steps",
            []
        ):
            if not isinstance(step, dict):
                continue

            description = step.get(
                "description"
            )

            if isinstance(
                description,
                str
            ):
                old_by_description[
                    description.strip().lower()
                ] = step

        normalized = []

        for index, step in enumerate(
            steps,
            start=1
        ):
            if not isinstance(step, dict):
                continue

            description = step.get(
                "description"
            )

            if not isinstance(
                description,
                str
            ):
                continue

            description = description.strip()

            if not description:
                continue

            old = old_by_description.get(
                description.lower()
            )

            status = step.get(
                "status"
            )

            if status not in {
                "pending",
                "completed"
            }:
                if (
                    old
                    and old.get(
                        "status"
                    ) == "completed"
                ):
                    status = "completed"
                else:
                    status = "pending"

            result = None

            if (
                old
                and old.get(
                    "status"
                ) == "completed"
            ):
                result = old.get(
                    "result"
                )

            normalized.append({
                "id": index,
                "description": description,
                "status": status,
                "result": result
            })

        return normalized

    def update_step(
        self,
        plan,
        step_id,
        result,
        status="completed"
    ):
        if not isinstance(plan, dict):
            return plan

        steps = plan.get("steps", [])

        if not isinstance(
            steps,
            list
        ):
            return plan

        for step in steps:
            if not isinstance(
                step,
                dict
            ):
                continue

            if step.get("id") == step_id:
                step["status"] = status
                step["result"] = result
                break

        return plan

    def get_next_step(self, plan):
        if not isinstance(plan, dict):
            return None

        steps = plan.get(
            "steps",
            []
        )

        if not isinstance(
            steps,
            list
        ):
            return None

        for step in steps:
            if not isinstance(
                step,
                dict
            ):
                continue

            if step.get(
                "status"
            ) != "completed":
                return step

        return None

    def is_complete(self, plan):
        if not isinstance(plan, dict):
            return False

        steps = plan.get(
            "steps",
            []
        )

        if not steps:
            return False

        return all(
            isinstance(
                step,
                dict
            )
            and step.get(
                "status"
            ) == "completed"
            for step in steps
        )

    def get_plan_summary(self, plan):
        if not isinstance(
            plan,
            dict
        ):
            return "No plan."

        goal = plan.get(
            "goal",
            "Unknown goal"
        )

        steps = plan.get(
            "steps",
            []
        )

        lines = [
            f"Goal: {goal}",
            ""
        ]

        for step in steps:
            if not isinstance(
                step,
                dict
            ):
                continue

            step_id = step.get(
                "id",
                "?"
            )

            description = step.get(
                "description",
                "Unknown step"
            )

            status = step.get(
                "status",
                "pending"
            )

            lines.append(
                f"{step_id}. "
                f"[{status}] "
                f"{description}"
            )

        return "\n".join(lines)