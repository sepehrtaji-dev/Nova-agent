"""Evidence-based self-reflection for Nova task runs.

This module audits observable plan state and verifier records. It deliberately
does not ask the model to invent a success assessment from its own narrative.
"""

import re


_STATUS_PATTERN = re.compile(
    r"^VERIFIER_STATUS:\s*(CONFIRMED|FAILED|UNVERIFIABLE)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


class SelfReflection:
    """Compare a task plan's state with the current run's verifier evidence."""

    def evaluate(self, goal, plan, tool_history, reported_complete=False):
        steps = plan.get("steps", []) if isinstance(plan, dict) else []
        if not isinstance(steps, list):
            steps = []
        valid_steps = [step for step in steps if isinstance(step, dict)]

        completed_steps = [
            str(step.get("description", "")).strip() or "(unnamed step)"
            for step in valid_steps
            if step.get("status") == "completed"
        ]
        pending_steps = [
            str(step.get("description", "")).strip() or "(unnamed step)"
            for step in valid_steps
            if step.get("status") != "completed"
        ]

        if isinstance(tool_history, list):
            history_text = "\n".join(str(item) for item in tool_history)
        elif isinstance(tool_history, str):
            history_text = tool_history
        else:
            history_text = ""

        # Raw tool output is untrusted and may contain text that imitates a
        # verifier marker. Count only markers emitted after the raw-result block.
        trusted_history = re.sub(
            r"BEGIN_RAW_TOOL_RESULT\s*.*?END_RAW_TOOL_RESULT",
            "",
            history_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        statuses = [
            value.lower()
            for value in _STATUS_PATTERN.findall(trusted_history)
        ]
        confirmed = statuses.count("confirmed")
        failed = statuses.count("failed")
        unverifiable = statuses.count("unverifiable")

        plan_complete = bool(valid_steps) and not pending_steps
        evidence_covers_plan = (
            plan_complete and confirmed >= len(completed_steps)
        )
        complete = bool(
            reported_complete and plan_complete and evidence_covers_plan
        )

        if complete:
            reason = "All planned steps are marked complete and have sufficient confirmed verifier evidence."
        elif pending_steps:
            reason = "The plan still contains pending or incomplete steps."
        elif not valid_steps:
            reason = "No valid plan steps are available to verify goal coverage."
        elif confirmed < len(completed_steps):
            reason = "Confirmed verifier evidence does not cover every completed plan step."
        elif not reported_complete:
            reason = "The runtime did not independently mark the task complete."
        else:
            reason = "The available evidence is insufficient to confirm full completion."

        retry_candidates = []
        if failed or unverifiable:
            retry_candidates.append(
                "Review failed or unverifiable tool outcomes; do not blindly replay side-effecting actions."
            )
        retry_candidates.extend(pending_steps)

        return {
            "goal": str(goal or ""),
            "reported_complete": bool(reported_complete),
            "complete": complete,
            "plan_step_count": len(valid_steps),
            "completed_steps": completed_steps,
            "pending_steps": pending_steps,
            "confirmed_tool_calls": confirmed,
            "failed_tool_calls": failed,
            "unverifiable_tool_calls": unverifiable,
            "reason": reason,
            "follow_up": retry_candidates[:8],
        }
