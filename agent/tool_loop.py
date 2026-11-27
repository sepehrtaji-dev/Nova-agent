"""Model-driven tool execution loop.

The model chooses tools from the live registry, Nova executes validated calls,
and results are returned as tool messages. The model chooses the next step.
"""
from __future__ import annotations

import json

from agent.activity import THINKING_ACTIVITY, format_activity
from agent.cancellation import raise_if_cancelled
from tools.task_plan import normalize_plan, open_steps
from agent.context_budget import compact_definitions, estimate_tokens, fit_messages
from agent.goals import describe_unmet, goal_tools, infer_goals, record_goal_result, unmet_goals


# Failures that retrying cannot fix (the session simply does not allow the tool).
_PERMANENT_FAILURES = (
    "is disabled by session permissions",
    "is not enabled in this session",
    "is not registered",
)


def _is_permanent_failure(result):
    error = str(result.get("error") or "") if isinstance(result, dict) else ""
    return any(marker in error for marker in _PERMANENT_FAILURES)


class ToolLoopError(RuntimeError):
    """Raised when a model tool-call turn cannot be processed safely."""


def _value(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_tool_call(raw, round_index, call_index):
    function = _value(raw, "function", {})
    name = _value(function, "name")
    arguments = _value(function, "arguments", {})
    call_id = _value(raw, "id") or f"nova_call_{round_index}_{call_index}"
    parse_error = None
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            parse_error = f"Arguments for tool '{name}' are not valid JSON: {exc.msg}."
            arguments = {}
    if not isinstance(name, str) or not name.strip():
        raise ToolLoopError("Model returned a tool call without a valid name.")
    if not isinstance(arguments, dict):
        parse_error = f"Arguments for tool '{name}' must be a JSON object."
        arguments = {}
    return {
        "id": str(call_id),
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }, name, arguments, parse_error


class ToolCallingLoop:
    """Provider-neutral agentic loop over an OpenAI/Ollama-style tool interface."""

    MAX_RESULT_CHARS = 40000
    MAX_CALLS_PER_TURN = 6
    # How many times a premature final answer may be sent back for more work
    # (a failed tool call, or checklist items still open) before it is accepted.
    MAX_CONTINUATIONS = 4
    # A model that keeps repeating the same call is stuck, not working. The same
    # call is run at most this many times per turn, and a call that already
    # failed this many times is not retried unchanged.
    MAX_IDENTICAL_CALLS = 3
    MAX_IDENTICAL_FAILURES = 2
    # Rounds in a row where every call was a blocked repeat before the loop
    # stops asking for tools and makes the model summarize.
    MAX_BLOCKED_ROUNDS = 2
    # Prompt budget used when the backend does not report its context window
    # (hosted models have very large windows).
    DEFAULT_CONTEXT_TOKENS = 60000
    # Above this share of the window, tool descriptions are shortened.
    COMPACT_DEFINITIONS_SHARE = 0.35
    LEDGER_CHARS = 12000

    def __init__(
        self,
        brain,
        tools,
        verifier,
        allowed_tools,
        *,
        status=None,
        validate_input=None,
        prepare_context=None,
        on_result=None,
        on_answer_delta=None,
        on_thought_delta=None,
        max_rounds=12,
        cancel_event=None,
        max_continuations=None,
        context_window_tokens=None,
    ):
        self.brain = brain
        self.tools = tools
        self.verifier = verifier
        self.allowed_tools = set(allowed_tools or [])
        self.status = status
        self.validate_input = validate_input
        self.prepare_context = prepare_context
        self.on_result = on_result
        self.on_answer_delta = on_answer_delta
        self.on_thought_delta = on_thought_delta
        self.max_rounds = max(1, int(max_rounds or 12))
        self.cancel_event = cancel_event
        self.max_continuations = (
            self.MAX_CONTINUATIONS if max_continuations is None else max(0, int(max_continuations))
        )
        self._plan_steps = []
        self._thought_seen = False
        self._goals = []
        self.context_window_tokens = context_window_tokens

    def _check_cancelled(self):
        raise_if_cancelled(self.cancel_event)

    def _status(self, message):
        if callable(self.status):
            try:
                self.status(str(message))
            except Exception:
                pass

    def _round_thought_callback(self):
        """Wrap on_thought_delta so each round's thinking starts on a new paragraph.

        Without a separator, the thinking from consecutive rounds runs together
        in the panel ("...search the web.I'll search the web...").
        """
        callback = self.on_thought_delta
        if not callable(callback):
            return callback
        state = {"first": True}

        def emit(piece):
            if state["first"]:
                state["first"] = False
                if self._thought_seen:
                    piece = "\n\n" + str(piece)
                self._thought_seen = True
            callback(piece)

        return emit

    def _generate_turn(self, messages, definitions, system_prompt):
        stream_method = getattr(self.brain, "generate_tool_turn_stream", None)
        if callable(stream_method):
            stream_kwargs = {
                "messages": messages,
                "tools": definitions,
                "system_prompt": system_prompt,
                "on_token": self.on_answer_delta,
                "on_thought_delta": self._round_thought_callback(),
            }
            if getattr(self.brain, "supports_cancel_event", False):
                stream_kwargs["cancel_event"] = self.cancel_event
            return stream_method(**stream_kwargs)
        return self.brain.generate_tool_turn(
            messages=messages,
            tools=definitions,
            system_prompt=system_prompt,
        )

    def _definitions(self):
        definitions = []
        registry = getattr(self.tools, "tools", {})
        for name in sorted(self.allowed_tools):
            metadata = registry.get(name, {}) if isinstance(registry, dict) else {}
            if not isinstance(metadata, dict):
                continue
            schema = metadata.get("input_schema")
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            definitions.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(metadata.get("description", "")).strip(),
                    "parameters": schema,
                },
            })
        return definitions

    def _prepare(self, name, arguments, context):
        metadata = getattr(self.tools, "tools", {}).get(name, {})
        preparer = metadata.get("prepare_input") if isinstance(metadata, dict) else None
        if not callable(preparer):
            return arguments
        prepared = preparer(arguments, context)
        if not isinstance(prepared, dict):
            raise ToolLoopError(f"Input preparation for '{name}' did not return an object.")
        return prepared

    def _validate(self, name, arguments):
        if name not in self.allowed_tools:
            return False, f"Tool '{name}' is not enabled in this session."
        if not self.tools.exists(name):
            return False, f"Tool '{name}' is not registered."
        if callable(self.validate_input):
            return self.validate_input(name, arguments)
        validator = getattr(self.tools, "validate_input", None)
        if callable(validator):
            return validator(name, arguments)
        return True, None

    def _execute_call(self, name, arguments, context):
        if name not in self.allowed_tools:
            return {"ok": False, "error": f"Tool '{name}' is disabled by session permissions."}
        try:
            prepared = self._prepare(name, arguments, context)
        except Exception as exc:
            return {"ok": False, "error": f"Input preparation failed: {type(exc).__name__}: {exc}"}

        valid, reason = self._validate(name, prepared)
        if not valid:
            return {"ok": False, "error": f"Input validation failed: {reason or 'invalid input'}"}

        encoded = json.dumps(prepared, ensure_ascii=False)
        # A single human-readable activity event drives the live status chip
        # ("Searching the web…", "Reading the file…") instead of raw tool
        # names flickering past.
        self._check_cancelled()
        self._status(format_activity(name))
        try:
            result = self.tools.execute(name, encoded)
        except Exception as exc:
            result = f"TOOL_EXECUTION_EXCEPTION: {type(exc).__name__}: {exc}"
        self._check_cancelled()
        if not isinstance(result, str):
            result = str(result)

        verification = None
        try:
            verification = self.verifier.verify(name, encoded, result)
        except Exception:
            verification = None

        confirmed = bool(
            verification
            and callable(getattr(verification, "confirmed", None))
            and verification.confirmed()
        )
        status = getattr(verification, "status", "unverifiable") if verification else "unverifiable"
        message = getattr(verification, "message", "") if verification else "No verifier result available."
        evidence = getattr(verification, "evidence", "") if verification else ""

        if callable(self.on_result):
            try:
                self.on_result(name, encoded, result, verification)
            except Exception:
                pass

        self._status(f"{'Confirmed' if confirmed else 'Executed; verification ' + str(status)}: {name}")
        output = result
        if len(output) > self.MAX_RESULT_CHARS:
            output = output[:self.MAX_RESULT_CHARS] + "\n[Tool output truncated by Nova to keep the model context bounded.]"
        return {
            "ok": True,
            "tool": name,
            "verified": confirmed,
            "verification": str(status),
            "verification_message": str(message),
            "verification_evidence": str(evidence)[:1000],
            "output": output,
        }

    def _budget_tokens(self):
        window = self.context_window_tokens
        if window is None:
            window = getattr(self.brain, "context_window_tokens", None)
        if isinstance(window, int) and not isinstance(window, bool) and window >= 1024:
            return window
        return self.DEFAULT_CONTEXT_TOKENS

    def _tool_ledger(self, messages):
        """Compact, readable record of what the tools returned this turn.

        write_file builds a document from this, so it must hold the research
        itself, not the JSON-escaped session context the model was shown.
        """
        calls = {}
        entries = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") == "assistant":
                for call in message.get("tool_calls") or []:
                    function = call.get("function", {}) if isinstance(call, dict) else {}
                    calls[call.get("id")] = (function.get("name", ""), function.get("arguments", {}))
            elif message.get("role") == "tool":
                try:
                    data = json.loads(message.get("content") or "")
                except (TypeError, ValueError):
                    data = {}
                name, arguments = calls.get(message.get("tool_call_id"), (message.get("name", "tool"), {}))
                if name == "update_plan" or not isinstance(data, dict) or not data.get("ok"):
                    continue
                shown = {k: v for k, v in (arguments or {}).items() if k != "content"} if isinstance(arguments, dict) else {}
                entries.append(
                    f"[{name}] {json.dumps(shown, ensure_ascii=False)[:300]}\n"
                    f"{str(data.get('output', ''))[:6000]}"
                )
        kept, used = [], 0
        for entry in reversed(entries):  # newest results matter most
            if used + len(entry) > self.LEDGER_CHARS and kept:
                break
            kept.append(entry)
            used += len(entry)
        return "\n\n".join(reversed(kept))

    def _reminder(self, user_message):
        missing = unmet_goals(self._goals)
        remaining = open_steps(self._plan_steps)
        if not missing and not remaining:
            return ""
        todo = []
        if missing:
            todo.append(describe_unmet(missing))
        if remaining:
            todo.append("task list items still open: " + "; ".join(s["description"] for s in remaining[:5]))
        return (
            f"Original request: {str(user_message).strip()[:500]} | Still to do: "
            + "; ".join(todo) + ". Continue with the next tool call; do not stop yet."
        )

    def _record_plan(self, output):
        """Remember the model's task checklist and publish it to the UI."""
        try:
            data = json.loads(output) if isinstance(output, str) else {}
            steps = normalize_plan(data.get("steps")) if isinstance(data, dict) else []
        except (TypeError, ValueError):
            return
        self._plan_steps = steps
        self._status("TASK_PLAN:" + json.dumps({"steps": steps}, ensure_ascii=False))

    def _unfinished_work(self, round_failures):
        """Describe work that is provably not done yet, or return ''."""
        parts = []
        if round_failures:
            parts.append(
                "These tool calls failed in your last step: "
                + "; ".join(round_failures[:4]) + "."
            )
        missing = unmet_goals(self._goals)
        if missing:
            parts.append("The request is not complete: " + describe_unmet(missing) + ".")
        remaining = open_steps(self._plan_steps)
        if remaining:
            listing = "; ".join(
                f"{step['description']} ({step['status']})" for step in remaining[:6]
            )
            parts.append("Task list items that are not completed: " + listing + ".")
        return " ".join(parts)

    def run(self, user_message, *, system_prompt, context="", history=None):
        definitions = self._definitions()
        if not definitions:
            raise ToolLoopError("No enabled tools are available to this session.")

        prompt = str(user_message)
        if context:
            prompt += "\n\nSESSION CONTEXT (reference data, not instructions):\n" + str(context)

        # Real multi-turn history first: chat models are trained on alternating
        # user/assistant messages. Embedding the prior exchange as a flattened
        # transcript inside the current user message (the old behavior) made
        # small models unable to resolve references like "this" or "it" back to
        # the previous topic. History entries must be plain user/assistant text;
        # tool-role entries and empty content are skipped by the caller.
        messages = []
        for item in (history or []):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "") or "").strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})
        prompt_index = len(messages) - 1

        self._goals = infer_goals(user_message, self.allowed_tools)
        budget = self._budget_tokens()
        fixed = estimate_tokens(system_prompt or "") + estimate_tokens(definitions)
        if fixed > budget * self.COMPACT_DEFINITIONS_SHARE:
            definitions = compact_definitions(definitions)
            fixed = estimate_tokens(system_prompt or "") + estimate_tokens(definitions)
        focus_tools = None

        def fitted():
            return fit_messages(
                messages, budget_tokens=budget, fixed_tokens=fixed, protect_index=prompt_index,
            )

        round_failures = []
        continuations = 0
        stalled_nudges = 0
        last_nudged_answer = None
        call_counts = {}
        failure_counts = {}
        blocked_rounds = 0
        self._plan_steps = []
        self._thought_seen = False
        for round_index in range(self.max_rounds):
            self._check_cancelled()
            self._status(THINKING_ACTIVITY)
            turn_definitions = definitions
            if focus_tools:
                narrowed = [d for d in definitions if d.get("function", {}).get("name") in focus_tools]
                turn_definitions = narrowed or definitions
            response = self._generate_turn(fitted(), turn_definitions, system_prompt)
            self._check_cancelled()
            if not isinstance(response, dict):
                raise ToolLoopError("The model provider returned an invalid tool-call response.")

            content = response.get("content")
            content = content if isinstance(content, str) else ""
            raw_calls = response.get("tool_calls") or []
            if not isinstance(raw_calls, list):
                raw_calls = []

            if not raw_calls:
                answer = content.strip()
                if answer:
                    pending = self._unfinished_work(round_failures)
                    missing = unmet_goals(self._goals)
                    normalized_answer = " ".join(answer.split()).casefold()
                    # A missing deliverable gets one extra, narrowed attempt.
                    stall_limit = 3 if missing else 2
                    if (
                        pending
                        and continuations < self.max_continuations
                        and stalled_nudges < stall_limit
                        and (bool(missing) or normalized_answer != last_nudged_answer)
                        and round_index + 1 < self.max_rounds
                    ):
                        # Not a perfect result yet: do not accept this answer.
                        # Discard what was streamed and send the model back to
                        # work until the task is finished and verified.
                        continuations += 1
                        stalled_nudges += 1
                        last_nudged_answer = normalized_answer
                        round_failures = []
                        if missing and stalled_nudges >= 2:
                            # The model keeps talking instead of acting: offer
                            # only the tools that finish the missing deliverable.
                            focus_tools = goal_tools(missing)
                        hints = " ".join(goal.hint for goal in missing)
                        self._status("MODEL_ANSWER_RESET")
                        messages.append({"role": "assistant", "content": answer})
                        messages.append({"role": "user", "content": (
                            "Your task is not finished yet. " + pending + " " + hints + " "
                            "Keep working with your tools until every item is completed "
                            "and verified. If an item truly cannot be done, mark it "
                            "'failed' with update_plan and say why in your final answer. "
                            "Do not only describe what you would do; do it."
                        ).replace("  ", " ")})
                        continue
                    if missing:
                        # Never let the user believe unfinished work is done.
                        answer += (
                            "\n\nNote: this is not complete. " + describe_unmet(missing).capitalize() + "."
                        )
                    return answer
                raise ToolLoopError("The model returned neither a final answer nor a tool call.")

            if content:
                self._status("MODEL_ANSWER_RESET")
            normalized_calls = []
            parsed_calls = []
            for call_index, raw in enumerate(raw_calls[:self.MAX_CALLS_PER_TURN]):
                normalized, name, arguments, parse_error = _as_tool_call(raw, round_index, call_index)
                normalized_calls.append(normalized)
                parsed_calls.append((normalized, name, arguments, parse_error))

            assistant_message = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": normalized_calls,
            }
            # Preserve Ollama's native thinking channel in replayed history.
            # The model can then continue its reasoning after each tool result
            # instead of reconstructing the previous turn from scratch.
            thinking = response.get("thinking")
            if isinstance(thinking, str) and thinking:
                assistant_message["thinking"] = thinking
            provider_content = response.get("provider_content")
            if isinstance(provider_content, list) and provider_content:
                assistant_message["provider_content"] = provider_content
            messages.append(assistant_message)

            round_failures = []
            stalled_nudges = 0  # the model is acting again, not just answering
            focus_tools = None
            blocked_this_round = 0
            dropped = len(raw_calls) - len(parsed_calls)
            for call_number, (normalized, name, arguments, parse_error) in enumerate(parsed_calls):
                call_key = None
                repeat_block = None
                if not parse_error:
                    try:
                        call_key = (name, json.dumps(arguments, sort_keys=True, default=str))
                    except (TypeError, ValueError):
                        call_key = None
                    if call_key is not None:
                        if call_counts.get(call_key, 0) >= self.MAX_IDENTICAL_CALLS:
                            repeat_block = (
                                f"You already made this exact '{name}' call "
                                f"{call_counts[call_key]} times this turn. Do not repeat it."
                            )
                        elif failure_counts.get(call_key, 0) >= self.MAX_IDENTICAL_FAILURES:
                            repeat_block = (
                                f"This exact '{name}' call already failed "
                                f"{failure_counts[call_key]} times this turn. Retrying it unchanged "
                                "will not help."
                            )
                if repeat_block:
                    blocked_this_round += 1
                    result = {
                        "ok": False,
                        "error": repeat_block + " Use the results you already have, change the "
                                 "arguments, try a different tool, or answer with what you have "
                                 "and say what is missing.",
                    }
                elif parse_error:
                    result = {"ok": False, "error": parse_error}
                else:
                    if call_key is not None:
                        call_counts[call_key] = call_counts.get(call_key, 0) + 1
                    result = self._execute_call(
                        name,
                        arguments,
                        {
                            "message": user_message,
                            **(self.prepare_context if isinstance(self.prepare_context, dict) else {}),
                            "tool_history": self._tool_ledger(messages),
                            "status": self._status,
                        },
                    )

                if name == "update_plan" and result.get("ok"):
                    self._record_plan(result.get("output"))
                failed_call = not result.get("ok") or result.get("verification") == "failed"
                if failed_call and call_key is not None and not repeat_block:
                    failure_counts[call_key] = failure_counts.get(call_key, 0) + 1
                if (
                    failed_call
                    and not repeat_block
                    and not _is_permanent_failure(result)
                ):
                    detail = result.get("error") or result.get("verification_message") or "failed"
                    round_failures.append(f"{name}: {str(detail)[:160]}")
                if not failed_call and not repeat_block:
                    record_goal_result(self._goals, name)
                if call_number == len(parsed_calls) - 1:
                    reminder = self._reminder(user_message)
                    if reminder:
                        result["reminder"] = reminder
                if dropped > 0 and call_number == len(parsed_calls) - 1:
                    result["notice"] = (
                        f"{dropped} additional tool call(s) in this step were not run "
                        f"(limit {self.MAX_CALLS_PER_TURN} per step). Request them again "
                        "if they are still needed."
                    )
                messages.append({
                    "role": "tool",
                    "tool_call_id": normalized["id"],
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
                self._status(THINKING_ACTIVITY)

            if blocked_this_round and blocked_this_round == len(parsed_calls):
                blocked_rounds += 1
                if blocked_rounds >= self.MAX_BLOCKED_ROUNDS:
                    break
            else:
                blocked_rounds = 0

        self._status("Tool-call limit reached; asking the model for a concise status.")
        messages.append({
            "role": "user",
            "content": (
                "The tool-call budget for this turn has been reached. "
                "Do not call more tools. Summarize what was actually completed, "
                "what remains, and any verification uncertainty. Do not claim "
                "unverified work succeeded."
            ),
        })
        final = self._generate_turn(fitted(), definitions, system_prompt)
        if isinstance(final, dict) and not final.get("tool_calls"):
            text = final.get("content")
            if isinstance(text, str) and text.strip():
                return text.strip()
        return "I reached the tool-call limit before completing the request. Some actions may have completed; please review the verified results before continuing."
