
import json
import logging
import re


class ToolRouter:

    def __init__(self, brain, tools):
        self.brain = brain
        self.tools = tools
        self._last_file_generation = None

    def _extract_json(self, response):

        if not response:
            return None

        response = str(response).strip()

        # BUG 33: Handle code fences with optional info string (```json, ``` JSON, etc.)
        response = re.sub(
            r"^\s*```[\s]*[a-zA-Z]*[\s]*",
            "",
            response,
            flags=re.IGNORECASE
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

            # BUG 2: Wrap valid JSON arrays
            if isinstance(data, list):
                return {"items": data}

        except json.JSONDecodeError:
            pass

        # BUG 44+45: Try fallback parsing for trailing commas and single quotes
        try:
            cleaned = re.sub(r",\s*}", "}", response)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            cleaned = re.sub(r"'([^']*)'", r'"\1"', cleaned)
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {"items": data}
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        candidates = []

        for index, char in enumerate(response):

            if char != "{":
                continue

            try:
                data, _ = decoder.raw_decode(
                    response[index:]
                )

                if isinstance(data, dict):
                    candidates.append(data)

            except json.JSONDecodeError:
                continue

        # BUG 3: Prefer the LAST valid JSON object (most likely the actual decision)
        if candidates:
            # Prefer the last object containing expected keys
            expected_keys = {"action", "task_type", "tool"}
            for candidate in reversed(candidates):
                if expected_keys & set(candidate.keys()):
                    return candidate
            # Otherwise return the last one
            return candidates[-1]

        return None

    def _extract_function_call(self, response):

        if not response:
            return None

        text = str(response).strip()

        # BUG 4: Handle nested parentheses by finding the outer bracket
        # and using balanced parenthesis matching
        match = re.search(r"\[\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", text)
        if not match:
            return None

        tool_name = match.group(1).strip()
        # Find the matching closing parenthesis
        start = match.end() - 1  # position of '('
        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == '(':
                depth += 1
            elif text[i] == ')':
                depth -= 1
                if depth == 0:
                    end = i
                    break

        if end == -1:
            return None

        # Find the closing bracket after the parenthesis
        bracket_end = text.find(']', end)
        if bracket_end == -1:
            return None

        # The balanced-parenthesis scan above already extracted the call.
        # Do not run a second regex against an undefined pattern variable.
        arguments = text[start + 1:end].strip()

        if not self.tools.exists(tool_name):
            return None

        if tool_name == "web_search":

            query_match = re.search(
                r"""
                (?:query|search|q|text)
                \s*=\s*
                (?:
                    "([^"]*)"
                    |
                    '([^']*)'
                )
                """,
                arguments,
                flags=re.IGNORECASE | re.VERBOSE
            )

            if query_match:

                query = (
                    query_match.group(1)
                    if query_match.group(1) is not None
                    else query_match.group(2)
                )

                query = query.strip()

                if query:

                    return {
                        "action": "tool",
                        "task_type": "computer",
                        "tool": "web_search",
                        "input": json.dumps(
                            {
                                "query": query
                            },
                            ensure_ascii=False
                        )
                    }

            if arguments:

                cleaned = arguments.strip()

                if (
                    cleaned.startswith('"')
                    and cleaned.endswith('"')
                ):
                    cleaned = cleaned[1:-1]

                elif (
                    cleaned.startswith("'")
                    and cleaned.endswith("'")
                ):
                    cleaned = cleaned[1:-1]

                cleaned = cleaned.strip()

                if cleaned:

                    return {
                        "action": "tool",
                        "task_type": "computer",
                        "tool": "web_search",
                        "input": json.dumps(
                            {
                                "query": cleaned
                            },
                            ensure_ascii=False
                        )
                    }

        if tool_name == "terminal":

            command_match = re.search(
                r"""
                (?:command|cmd)
                \s*=\s*
                (?:
                    "([^"]*)"
                    |
                    '([^']*)'
                )
                """,
                arguments,
                flags=re.IGNORECASE | re.VERBOSE
            )

            if command_match:

                command = (
                    command_match.group(1)
                    if command_match.group(1) is not None
                    else command_match.group(2)
                )

                command = command.strip()

                if command:

                    stdin_match = re.search(
                        r"""
                        (?:input|stdin)
                        \s*=\s*
                        (?:
                            "([^"]*)"
                            |
                            '([^']*)'
                        )
                        """,
                        arguments,
                        flags=re.IGNORECASE | re.VERBOSE
                    )

                    payload = {
                        "command": command,
                        "location": "projects"
                    }

                    if stdin_match:
                        payload["input"] = (
                            stdin_match.group(1)
                            if stdin_match.group(1) is not None
                            else stdin_match.group(2)
                        )

                    return {
                        "action": "tool",
                        "task_type": "computer",
                        "tool": "terminal",
                        "input": json.dumps(
                            payload,
                            ensure_ascii=False
                        )
                    }

        # Generic handler for all other tools (git, write_file, read_file,
        # list_files, create_directory, etc.): parse key="value" arguments.
        parsed = self._parse_key_value_arguments(arguments)
        if parsed:
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": tool_name,
                "input": json.dumps(
                    parsed,
                    ensure_ascii=False
                )
            }

        return None

    def _parse_key_value_arguments(self, arguments):
        """Parse arguments in format: key="value", key='value', or key=value"""
        if not arguments or not arguments.strip():
            return None

        result = {}
        # BUG 7: Handle input={...} style JSON object values first
        json_obj_pattern = re.compile(
            r"""
            (\w+)               # key
            \s*=\s*             # =
            (\{.*\})            # JSON object value
            """,
            re.VERBOSE | re.DOTALL
        )
        json_matches = json_obj_pattern.findall(arguments)
        if json_matches:
            for key, value_str in json_matches:
                try:
                    value = json.loads(value_str)
                    result[key] = value
                except json.JSONDecodeError:
                    continue
            if result:
                return result

        # Pattern to match key="value", key='value', or key=value (no spaces around =)
        # Handles quoted values with escaped quotes
        # BUG 6: Allow commas in unquoted values
        pattern = re.compile(
            r"""
            (\w+)               # key
            \s*=\s*             # =
            (?:                 # value
                "((?:[^"\\]|\\.)*)"   # double-quoted
                |
                '((?:[^'\\]|\\.)*)'   # single-quoted
                |
                ([^,\s]+(?:,\s*[^=\s,]+)*)  # unquoted (commas allowed within value)
            )
            """,
            re.VERBOSE
        )

        matches = pattern.findall(arguments)
        if matches:
            for match in matches:
                key = match[0]
                # One of the three value groups will be non-empty
                value = match[1] or match[2] or match[3]
                if value:
                    # Unescape quotes
                    value = value.replace('\\"', '"').replace("\\'", "'")
                    result[key] = value
            return result if result else None

        return None

    def _normalize_task_type(self, value):

        if not isinstance(value, str):
            return None

        value = value.strip().lower()

        if value in {
            "conversation",
            "chat",
            "talk"
        }:
            return "conversation"

        if value in {
            "computer",
            "action",
            "execution",
            "computer_task"
        }:
            return "computer"

        return None

    def _normalize_action(self, value):

        if not isinstance(value, str):
            return None

        value = value.strip().lower()

        if value in {
            "tool",
            "use_tool",
            "execute"
        }:
            return "tool"

        if value in {
            "respond",
            "response",
            "answer"
        }:
            return "respond"

        if value in {
            "retry",
            "again"
        }:
            return "retry"

        return None

    def _trusted_verifier_status(self, value):
        if not isinstance(value, str):
            return None

        normalized = value.replace("\\n", "\n")
        marker = re.search(
            r"END_RAW_TOOL_RESULT\s*\n",
            normalized,
            flags=re.IGNORECASE,
        )
        trusted = normalized[marker.end():] if marker else normalized

        # BUG 8: Allow trailing content after the status
        match = re.search(
            r"VERIFIER_STATUS:\s*(CONFIRMED|FAILED|UNVERIFIABLE)\s*\S*",
            trusted,
            flags=re.IGNORECASE,
        )
        return match.group(1).lower() if match else None

    def _has_successful_tool(self, tool_history):
        if not isinstance(tool_history, str) or not tool_history.strip():
            return False
        return self._trusted_verifier_status(tool_history) == "confirmed"

    def _get_tool_names(self, allowed_tools=None):

        if not self.tools.tools:
            return []

        names = list(self.tools.tools.keys())

        if allowed_tools is not None:
            allowed = set(allowed_tools)
            names = [name for name in names if name in allowed]

        return names

    def _contains_placeholder(self, value):
        """Return True only for obvious incomplete-code placeholders."""
        if not isinstance(value, str):
            return False

        text = value.strip().lower()
        if not text:
            return False

        strong_phrases = (
            "<code>",
            "</code>",
            "<code here>",
            "code here",
            "insert code here",
            "your code here",
            "write code here",
            "put code here",
            "the rest of the code",
            "rest of the code",
        )

        if any(phrase in text for phrase in strong_phrases):
            return True

        # A bare ellipsis / unicode ellipsis on its own line is a placeholder;
        # normal occurrences inside real Python expressions or prose are fine.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped in {"...", "…"}:
                return True

            # Common unfinished implementation comments.
            if re.match(r"^#\s*(?:todo|tbd)\b", stripped):
                return True

            if re.match(r"^(?:todo|tbd)\s*:\s*(?:implement|finish|complete|add)", stripped):
                return True

        return False

    def _normalize_web_search_input(self, tool_input):

        if isinstance(tool_input, str):

            stripped = tool_input.strip()

            if not stripped:
                return None

            try:

                parsed = json.loads(
                    stripped
                )

                if isinstance(parsed, dict):
                    tool_input = parsed

                else:

                    return json.dumps(
                        {
                            "query": stripped
                        },
                        ensure_ascii=False
                    )

            except json.JSONDecodeError:

                return json.dumps(
                    {
                        "query": stripped
                    },
                    ensure_ascii=False
                )

        if not isinstance(tool_input, dict):
            return None

        query = (
            tool_input.get("query")
            or tool_input.get("search")
            or tool_input.get("q")
            or tool_input.get("text")
        )

        if not isinstance(query, str):
            return None

        query = query.strip()

        if not query:
            return None

        return json.dumps(
            {
                "query": query
            },
            ensure_ascii=False
        )

    def _validate_basic_tool_input(
        self,
        tool_name,
        tool_input
    ):

        if not isinstance(
            tool_input,
            dict
        ):
            return False

        if tool_name == "write_file":

            path = tool_input.get(
                "path"
            )

            location = tool_input.get(
                "location",
                "projects"
            )

            if not isinstance(
                path,
                str
            ):
                return False

            if not path.strip():
                return False

            if location not in {
                "projects",
                "desktop",
                "system"
            }:
                return False

            return True

        if tool_name == "find_files":
            path = tool_input.get("path", ".")
            location = tool_input.get("location", "projects")
            if not isinstance(path, str):
                return False
            if location not in {"projects", "desktop", "system"}:
                return False
            for key in ("created_within_hours", "modified_within_hours"):
                if key in tool_input and tool_input.get(key) is not None:
                    try:
                        if float(tool_input.get(key)) < 0:
                            return False
                    except (TypeError, ValueError):
                        return False
            return True

        if tool_name == "read_file":

            path = tool_input.get(
                "path"
            )

            location = tool_input.get(
                "location",
                "projects"
            )

            if not isinstance(
                path,
                str
            ):
                return False

            if not path.strip():
                return False

            if location not in {
                "projects",
                "desktop",
                "system"
            }:
                return False

            return True

        if tool_name == "list_files":

            path = tool_input.get(
                "path",
                "."
            )

            location = tool_input.get(
                "location",
                "projects"
            )

            if not isinstance(
                path,
                str
            ):
                return False

            if location not in {
                "projects",
                "desktop",
                "system"
            }:
                return False

            return True

        if tool_name == "create_directory":

            path = tool_input.get(
                "path"
            )

            location = tool_input.get(
                "location",
                "projects"
            )

            if not isinstance(
                path,
                str
            ):
                return False

            path = path.strip()

            if not path:
                return False

            if path in {
                "~",
                "/",
                "\\",
                ".",
                ".."
            }:
                return False

            if location not in {
                "projects",
                "desktop",
                "system"
            }:
                return False

            return True

        if tool_name == "terminal":

            command = tool_input.get(
                "command"
            )

            location = tool_input.get(
                "location",
                "projects"
            )

            if not isinstance(
                command,
                str
            ):
                return False

            if not command.strip():
                return False

            if location not in {
                "projects",
                "desktop"
            }:
                return False

            return True

        if tool_name == "web_search":

            query = (
                tool_input.get("query")
                or tool_input.get("search")
                or tool_input.get("q")
                or tool_input.get("text")
            )

            return (
                isinstance(query, str)
                and bool(query.strip())
            )

        if tool_name == "git":
            action = tool_input.get("action")
            if not isinstance(action, str) or not action.strip():
                return False
            valid_actions = {
                "init", "clone", "status", "add",
                "commit", "push", "pull", "log",
                "diff", "branch", "checkout",
                "create_branch", "stash", "create_repo"
            }
            if action.strip().lower() not in valid_actions:
                return False
            return True

        if tool_name == "generate_image":
            prompt = tool_input.get("prompt")
            return isinstance(prompt, str) and bool(prompt.strip())

        if tool_name == "desktop":
            action = tool_input.get("action")
            return isinstance(action, str) and bool(action.strip())

        if tool_name in {"edit_file", "delete_file"}:
            path = tool_input.get("path")
            location = tool_input.get("location", "projects")
            return (
                isinstance(path, str)
                and bool(path.strip())
                and location in {"projects", "desktop", "system"}
            )

        # BUG 20: Unknown tools should return False
        logging.warning("Unknown tool encountered in validation: %s", tool_name)
        return False

    def _force_desktop_decision(self, message):
        """Build a deterministic desktop tool decision directly from user text."""
        import re as _re

        msg = re.sub(r"\s+", " ", str(message or "").strip().lower())

        def _coords():
            match = _re.search(
                r"\b(?:at|to|on)\s*\(?\s*(-?\d+)\s*[,x]\s*(-?\d+)\s*\)?",
                msg,
                flags=_re.IGNORECASE,
            )
            if not match:
                match = _re.search(
                    r"\b(-?\d+)\s*[,x]\s*(-?\d+)\b",
                    msg,
                    flags=_re.IGNORECASE,
                )
            if not match:
                return None
            # BUG 15: Clamp coordinates to reasonable screen bounds
            x = max(0, min(7680, int(match.group(1))))
            y = max(0, min(4320, int(match.group(2))))
            return x, y

        # Screenshot
        if _re.search(r"\b(?:screenshot|take\s+a\s+screenshot|capture\s+(?:the\s+)?screen)\b", msg):
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "desktop",
                "input": json.dumps({"action": "screenshot"}),
            }

        # Mouse click
        if _re.search(r"\b(?:click|double[- ]click|right[- ]click|middle[- ]click)\b", msg):
            coords = _coords()
            if coords is None:
                return None
            x, y = coords
            if "right" in msg:
                button = "right"
            elif "middle" in msg:
                button = "middle"
            else:
                button = "left"
            clicks = 2 if "double" in msg else 1
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "desktop",
                "input": json.dumps({
                    "action": "click",
                    "x": x,
                    "y": y,
                    "button": button,
                    "clicks": clicks,
                }),
            }

        # Mouse move
        if _re.search(r"\b(?:move|move\s+the)\b.*\bmouse\b|\bmouse\b.*\bmove\b", msg):
            coords = _coords()
            if coords is None:
                return None
            x, y = coords
            duration_match = _re.search(r"\b(?:in|over|for)\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)\b", msg)
            duration = float(duration_match.group(1)) if duration_match else 0.3
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "desktop",
                "input": json.dumps({
                    "action": "move",
                    "x": x,
                    "y": y,
                    "duration": duration,
                }),
            }

        # Keyboard text input
        if _re.search(r"\b(?:type|write)\b", msg):
            raw_message = str(message or "").strip()
            text_match = _re.search(
                r"""\b(?:type|write)\s+(?:this\s+)?(?:text\s+)?["'](.+?)["'](?:\s+(?:here|there|in\s+it|into\s+.+|in\s+.+|on\s+.+))?\s*$""",
                raw_message,
                flags=_re.IGNORECASE,
            )
            if text_match:
                typed_text = text_match.group(1)
            else:
                plain_match = _re.search(
                    r"\b(?:type|write)\s+(.+?)\s*$",
                    raw_message,
                    flags=_re.IGNORECASE,
                )
                if not plain_match:
                    return None
                typed_text = plain_match.group(1).strip()
                typed_text = _re.sub(r"\s+(?:here|there)$", "", typed_text, flags=_re.IGNORECASE).strip()

            if typed_text:
                return {
                    "action": "tool",
                    "task_type": "computer",
                    "tool": "desktop",
                    "input": json.dumps({
                        "action": "type",
                        "text": typed_text,
                    }, ensure_ascii=False),
                }

        # Keyboard key / shortcut
        if _re.search(r"\b(?:press|hit)\b", msg):
            key_match = _re.search(
                r"\b(?:press|hit)\s+(?:the\s+)?(?:key\s+)?([a-z0-9]+(?:\+[a-z0-9]+)*)\s*$",
                str(message or "").strip(),
                flags=_re.IGNORECASE,
            )
            if key_match:
                return {
                    "action": "tool",
                    "task_type": "computer",
                    "tool": "desktop",
                    "input": json.dumps({
                        "action": "key",
                        "key": key_match.group(1),
                    }),
                }

        # Scroll
        if _re.search(r"\bscroll\b", msg):
            amount = 3
            amount_match = _re.search(r"\b(?:by|with)\s+(\d+)\b", msg)
            if amount_match:
                amount = int(amount_match.group(1))
            # BUG 16: Clamp scroll amount to reasonable range (1-100)
            amount = max(1, min(100, amount))
            if _re.search(r"\b(?:down|lower)\b", msg):
                amount = -amount
            else:
                amount = abs(amount)
            coords = _coords()
            payload = {
                "action": "scroll",
                "amount": amount,
            }
            if coords is not None:
                payload["x"], payload["y"] = coords
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "desktop",
                "input": json.dumps(payload),
            }

        # List windows
        if "list" in msg and "window" in msg:
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "desktop",
                "input": json.dumps({"action": "get_windows"}),
            }

        # Close app/window
        close_match = _re.search(
            r"\bclose\s+(?:the\s+)?(?:app\s+)?(.+?)(?:\s+app)?$",
            msg,
            flags=_re.IGNORECASE,
        )
        if close_match:
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "desktop",
                "input": json.dumps({
                    "action": "close_app",
                    "title": close_match.group(1).strip(),
                }),
            }

        # Open app
        open_match = _re.search(
            r"\b(?:open|launch|run|start|execute)\s+(?:my\s+|the\s+)?(?:app\s+)?(.+?)(?:\s+app)?$",
            msg,
            flags=_re.IGNORECASE,
        )
        if open_match:
            app = open_match.group(1).strip()
            if app not in {"file", "folder", "directory"}:
                return {
                    "action": "tool",
                    "task_type": "computer",
                    "tool": "desktop",
                    "input": json.dumps({
                        "action": "open_app",
                        "app": app,
                    }),
                }

        return None


    def classify_task(self, message, conversation=""):
        """Classify intent with the language model, not keyword/regex shortcuts.

        Deterministic checks remain appropriate for validation and authorization,
        but user intent should be interpreted from the full request and context.
        If the model cannot provide a valid classification, fail closed to
        conversation rather than accidentally initiating a computer action.
        """
        if not isinstance(message, str) or not message.strip():
            return "conversation"

        prompt = f"""You are Nova's intent classifier.
Determine whether the user's current message requires Nova to perform a real
action using an enabled tool, or whether it is a conversational/informational
request that can be answered without a tool.

Interpret the full meaning, including negation, hypotheticals, quotations,
questions about how something works, and prior conversation. Mentioning a tool,
app, file, terminal, web search, or computer action is NOT by itself a request
to execute it. If the user asks how to do something, explain it unless they
clearly ask Nova to do it. If intent is genuinely ambiguous, choose conversation.

Return only JSON with exactly one field:
{{"task_type":"computer"}}
or
{{"task_type":"conversation"}}

PREVIOUS CONVERSATION:
{conversation[-6000:] if isinstance(conversation, str) else ""}

CURRENT USER MESSAGE:
{message}
"""
        for attempt in range(2):
            try:
                raw = self.brain.generate(
                    prompt if attempt == 0 else (
                        "Classify the intent of this request. Return only JSON: "
                        '{"task_type":"computer"} or '
                        '{"task_type":"conversation"}. Do not infer execution '
                        "intent from mere mentions, hypotheticals, or questions.\n"
                        f"Conversation: {conversation[-3000:] if isinstance(conversation, str) else ''}\n"
                        f"Request: {message}"
                    ),
                    json_mode=True,
                )
            except Exception as exc:
                logging.warning("Intent classification attempt %s failed: %s", attempt + 1, exc)
                continue

            data = self._extract_json(raw)
            if isinstance(data, dict):
                task_type = self._normalize_task_type(data.get("task_type"))
                if task_type in {"computer", "conversation"}:
                    return task_type

        return "conversation"

    def _build_decision_prompt(
        self,
        message,
        task_type,
        conversation,
        knowledge,
        tool_history,
        plan="No plan.",
        allowed_tools=None
    ):
        allowed = set(allowed_tools) if allowed_tools is not None else None
        descriptions = []

        for name, data in self.tools.tools.items():
            if allowed is not None and name not in allowed:
                continue
            descriptions.append(f"- {name}: {data['description']}")

        tools_description = "\n".join(descriptions) or "No tools are currently enabled."

        # Core supplies a bounded, step-aware history. Do not blindly keep
        # only the tail because earlier completed steps are authoritative.
        if not tool_history:
            tool_history = "None"

        if not plan:
            plan = "No plan."

        # BUG 12: Include knowledge in decision prompt
        knowledge_section = f"\nKNOWLEDGE:\n{knowledge}\n" if knowledge else ""

        return f"""You are Nova. Choose the next tool to run.

Think step by step before answering:
1. What is the user's goal?
2. What has been done so far (check TOOL HISTORY)?
3. What remains to be done?
4. Which single tool should run next?

AVAILABLE TOOLS:
{tools_description}

PLAN:
{plan}

TOOL HISTORY:
{tool_history if tool_history else "None"}

USER REQUEST: {message}
{knowledge_section}
RULES:
- Look at the plan. Find the first pending step. Run that tool.
- Use the tool descriptions above to choose valid inputs; do not invent unsupported capabilities.
- If the user is only asking to recall/report information already present in verified tool evidence or recent conversation, do not execute a new computer action.
- For write_file: ONLY return path and location. Never include content or code.
- For terminal: return the command to run.
- For git: return action and required fields.
- If a tool already succeeded (VERIFIER_STATUS: CONFIRMED), do NOT run it again.
- Choose exactly ONE action. Be specific and precise.

Return ONE JSON only:
{{"action":"tool","task_type":"computer","tool":"TOOL_NAME","input":{{"key":"value"}}}}

Or if task is fully done:
{{"action":"respond","task_type":"computer","goal_complete":true}}

Examples:
write_file: {{"action":"tool","task_type":"computer","tool":"write_file","input":{{"path":"nn.py","location":"projects"}}}}
terminal:   {{"action":"tool","task_type":"computer","tool":"terminal","input":{{"command":"python nn.py","location":"projects"}}}}
web_search: {{"action":"tool","task_type":"computer","tool":"web_search","input":{{"query":"pytorch tutorial"}}}}
git:        {{"action":"tool","task_type":"computer","tool":"git","input":{{"action":"init","path":"myproject"}}}}
screenshot: {{"action":"tool","task_type":"computer","tool":"desktop","input":{{"action":"screenshot"}}}}"""


    def _build_repair_prompt(
        self,
        message,
        task_type,
        conversation="",
        tool_history="",
        plan="No plan.",
        allowed_tools=None,
        knowledge=""
    ):

        if allowed_tools is None:
            tools_description = self.tools.get_descriptions()
        else:
            allowed = set(allowed_tools)
            lines = []
            for name, data in self.tools.tools.items():
                if name in allowed:
                    lines.append(f"- {name}: {data['description']}")
            tools_description = "\n".join(lines) or "No tools are currently enabled."

        # BUG 13: Include knowledge in repair prompt
        knowledge_section = f"\nKNOWLEDGE:\n{knowledge}\n" if knowledge else ""

        return f"""
You are Nova's action validator.

Think step by step:
1. What is the user's goal?
2. What has been done (check TOOL HISTORY)?
3. What is the next logical action?
4. Which tool performs it?

Return ONLY valid JSON.

TASK TYPE: {task_type}

USER REQUEST: {message}

PREVIOUS CONVERSATION: {conversation}

REAL TOOL HISTORY: {tool_history}

CURRENT PLAN: {plan}
{knowledge_section}
If the computer task is incomplete, choose the next real tool.

Available tools:
{tools_description}

Only the tools listed above are enabled for this request.

IMPORTANT: If the user explicitly requested a web search and no successful web_search result exists, YOU MUST choose web_search.

For web_search:
{{"action":"tool","task_type":"computer","tool":"web_search","input":{{"query":"search query"}}}}

For write_file (ONLY path + location, NO content, NO code):
{{"action":"tool","task_type":"computer","tool":"write_file","input":{{"path":"filename.py","location":"projects"}}}}

For edit_file (modify existing file):
{{"action":"tool","task_type":"computer","tool":"edit_file","input":{{"path":"filename","location":"projects","old":"text to replace","new":"replacement text"}}}}

For delete_file:
{{"action":"tool","task_type":"computer","tool":"delete_file","input":{{"path":"filename","location":"projects"}}}}

For read_file:
{{"action":"tool","task_type":"computer","tool":"read_file","input":{{"path":"filename","location":"projects"}}}}

For list_files:
{{"action":"tool","task_type":"computer","tool":"list_files","input":{{"path":".","location":"projects"}}}}

For create_directory:
{{"action":"tool","task_type":"computer","tool":"create_directory","input":{{"path":"directory_name","location":"projects"}}}}

For terminal:
{{"action":"tool","task_type":"computer","tool":"terminal","input":{{"command":"command","location":"projects"}}}}

For git:
{{"action":"tool","task_type":"computer","tool":"git","input":{{"action":"clone","url":"https://github.com/..."}}}}

If the entire task is completed:
{{"action":"respond","task_type":"computer","goal_complete":true}}

Return JSON only.
"""

    def _verified_web_document(self, tool_history):
        if not isinstance(tool_history, str):
            return None

        blocks = re.findall(
            r"TOOL_NAME:\s*web_search\s*\n"
            r".*?BEGIN_RAW_TOOL_RESULT\n"
            r"(.*?)"
            r"\nEND_RAW_TOOL_RESULT\n"
            r"VERIFIER_STATUS:\s*CONFIRMED",
            tool_history,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not blocks:
            return None

        entries = []
        for raw in blocks:
            matches = re.findall(
                r"\[\d+\]\s*\n"
                r"Title:\s*(.*?)\n"
                r"URL:\s*(.*?)\n"
                r"Snippet:\s*(.*?)(?=\n\n\[\d+\]|\Z)",
                raw,
                flags=re.DOTALL,
            )
            for title, url, snippet in matches:
                title = re.sub(r"\s+", " ", title).strip()
                url = re.sub(r"\s+", " ", url).strip()
                snippet = re.sub(r"\s+", " ", snippet).strip()
                entries.append((title, url, snippet))

        if not entries:
            return None

        lines = ["Verified search evidence:"]
        for index, (title, url, snippet) in enumerate(entries[:6], start=1):
            lines.append(f"{index}. {title}")
            if snippet:
                lines.append(f"   {snippet}")
            if url:
                lines.append(f"   Source: {url}")
        return "\n".join(lines)

    def generate_file_content(
        self,
        user_request,
        path,
        location,
        conversation="",
        tool_history=""
    ):
        self._last_file_generation_error = None

        # BUG 17: Validate path is a string
        if not isinstance(path, str):
            self._last_file_generation_error = "Path must be a string."
            return None

        # BUG 18: Validate location parameter
        if location not in {"projects", "desktop", "system"}:
            self._last_file_generation_error = f"Invalid location: {location}"
            return None

        extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        code_languages = {
            "cpp": "C++",
            "c": "C",
            "py": "Python",
            "pyw": "Python",
            "js": "JavaScript",
            "ts": "TypeScript",
            "tsx": "TypeScript",
            "jsx": "JavaScript",
            "java": "Java",
            "rs": "Rust",
            "go": "Go",
            # BUG 29: Expanded extension whitelist
            "sh": "Bash",
            "ps1": "PowerShell",
            "csv": "CSV",
            "yaml": "YAML",
            "yml": "YAML",
        }
        is_text_document = extension in {"txt", "md", "markdown"}
        language = code_languages.get(extension, "source")

        if re.search(r":\s*$", str(user_request or "").strip()):
            self._last_file_generation_error = (
                "The file request ends with an empty 'containing:' clause; "
                "no content was supplied."
            )
            return None

        if is_text_document:
            verified_document = self._verified_web_document(tool_history)
            if verified_document is not None:
                return verified_document

        bounded_history = str(tool_history or "")
        if len(bounded_history) > 14000:
            # BUG 19: Keep both HEAD and TAIL when truncating
            head = bounded_history[:7000]
            tail = bounded_history[-7000:]
            bounded_history = head + "\n... [truncated] ...\n" + tail

        bounded_conversation = str(conversation or "")
        if len(bounded_conversation) > 8000:
            # BUG 19: Keep both HEAD and TAIL when truncating
            head = bounded_conversation[:4000]
            tail = bounded_conversation[-4000:]
            bounded_conversation = head + "\n... [truncated] ...\n" + tail

        if is_text_document:
            prompt = (
                "Generate the complete text content for the requested document.\n\n"
                f"User request: {user_request}\n\n"
                f"Recent conversation:\n{bounded_conversation}\n\n"
                "Tool ledger:\n"
                f"{bounded_history}\n\n"
                "Rules:\n"
                "- Use only facts explicitly supported by verified evidence in the ledger.\n"
                "- Never invent a fact, version, date, source, URL, or result.\n"
                "- Preserve uncertainty when evidence is incomplete.\n"
                "- Return document content only."
            )
        else:
            prompt = (
                f"Generate complete raw {language} source code for \"{path}\".\n\n"
                f"User request: {user_request}\n\n"
                f"Recent conversation:\n{bounded_conversation}\n\n"
                f"Relevant tool history:\n{bounded_history}\n\n"
                "Output source code only. No Markdown fences, explanation, placeholders, TODOs, or ellipsis."
            )

        try:
            raw = self.brain.generate(
                prompt,
                system_prompt=(
                    f"You are an expert {language} code generator. "
                    "Think step by step about the implementation, then return only valid raw "
                    f"{language} source code. No placeholders, no TODOs, no ellipsis."
                ),
                json_mode=False,
                options={
                    "temperature": 0.0,
                    "num_predict": 2048,
                },
            )
        except Exception as exc:
            self._last_file_generation_error = f"{type(exc).__name__}: {exc}"
            return None

        if not isinstance(raw, str):
            raw = str(raw)

        generated = raw.strip()

        if generated.startswith("```"):
            lines = generated.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            generated = "\n".join(lines).strip()

        if self._contains_placeholder(generated):
            self._last_file_generation_error = "Generated code contained a placeholder."
            return None

        if not generated:
            self._last_file_generation_error = "Code generation returned empty content."
            return None

        return generated
    def _remember_file_generation(
        self,
        tool_decision
    ):

        if (
            not tool_decision
            or tool_decision.get("tool")
            != "write_file"
        ):
            return

        try:

            tool_input = json.loads(
                tool_decision["input"]
            )

            self._last_file_generation = {
                "path": tool_input.get(
                    "path"
                ),
                "location": tool_input.get(
                    "location",
                    "projects"
                )
            }

        except Exception:

            self._last_file_generation = None

    def _validate_tool_decision(self, data, task_type):
        if not isinstance(data, dict):
            return None

        action = str(data.get("action", "")).strip().lower()
        if action not in {"tool", "use_tool", "execute"}:
            return None

        tool = data.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            return None

        tool = tool.strip()

        if not self.tools.exists(tool):
            return None

        raw_input = data.get("input")

        if isinstance(raw_input, dict):
            tool_input_object = raw_input
        elif isinstance(raw_input, str):
            try:
                tool_input_object = json.loads(raw_input)
            except json.JSONDecodeError:
                return None
            if not isinstance(tool_input_object, dict):
                return None
        else:
            return None

        if not self._validate_basic_tool_input(tool, tool_input_object):
            return None

        normalized_input = self._normalize_tool_input(tool_input_object)
        if normalized_input is None:
            return None

        return {
            "action": "tool",
            "task_type": task_type,
            "tool": tool,
            "input": normalized_input
        }

    def _validate_response_decision(self, data, task_type, has_successful_tool):
        if not isinstance(data, dict):
            return None

        action = str(data.get("action", "")).strip().lower()
        if action not in {"respond", "response", "answer"}:
            return None

        if task_type == "conversation":
            return {"action": "respond", "task_type": "conversation"}

        goal_complete = data.get("goal_complete") is True
        if not goal_complete:
            return None

        if not has_successful_tool:
            return None

        return {
            "action": "respond",
            "task_type": "computer",
            "goal_complete": True
        }

    def _normalize_tool_input(self, tool_input):
        if isinstance(tool_input, dict):
            return json.dumps(tool_input, ensure_ascii=False)
        if isinstance(tool_input, str):
            stripped = tool_input.strip()
            if not stripped:
                return None
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    return json.dumps(parsed, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
            return stripped
        return None

    def _extract_filename(self, text):
        """Extract a filename while preserving its original casing."""
        if not isinstance(text, str):
            return None
        match = re.search(
            r"(?<![\w.-])([A-Za-z0-9_-]+\.(?:py|pyw|js|ts|tsx|jsx|cpp|c|h|java|rs|go|md|txt|json))(?![\w.-])",
            text,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    def _pending_planned_tool(self, plan_line):
        if not isinstance(plan_line, str):
            return None

        text = plan_line.strip()
        tools = getattr(self.tools, "tools", {})
        if not isinstance(tools, dict):
            return None

        structured = re.search(
            r"\|\s*TOOL=([A-Za-z_][A-Za-z0-9_]*)\b",
            text,
            flags=re.IGNORECASE,
        )
        if structured:
            candidate = structured.group(1).strip()
            return candidate if candidate in tools else None

        for name in tools:
            pattern = rf"\[pending\]\s*{re.escape(str(name))}\s*:"
            if re.search(pattern, text, re.IGNORECASE):
                return str(name)

        return None

    def _pending_plan_input(self, plan_line):
        if not isinstance(plan_line, str):
            return None

        match = re.search(
            r"\|\s*INPUT=(\{.*\})\s*$",
            plan_line.strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            return None

        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

        return value if isinstance(value, dict) else None

    def _deterministic_plan_decision(self, message, task_type, plan, tool_history, allowed_tools=None):
        """Return a tool decision for an unambiguous pending plan step.

        Tool selection for concrete computer actions must not depend entirely on
        a second LLM decision. The planner already produced the next action;
        use it deterministically and let the LLM generate only the file content.
        """
        if task_type != "computer" or not isinstance(plan, str):
            return None

        # BUG 27: Empty allowed_tools list should mean no tools allowed
        if allowed_tools is None:
            allowed = set(self.tools.tools.keys())
        else:
            allowed = set(allowed_tools)
        if not allowed:
            return None

        history = str(tool_history or "")
        pending = ""
        for line in plan.splitlines():
            if "[pending]" in line.lower():
                pending = line.strip()
                break

        if not pending:
            return None

        pending_lower = pending.lower()

        pending_action = re.search(
            r":\s*(.+)$",
            pending,
            flags=re.IGNORECASE,
        )
        action_text = (
            pending_action.group(1).strip()
            if pending_action
            else pending
        )
        action_lower = action_text.lower()
        combined = f"{pending} {message or ''}".strip()

        planned_tool = self._pending_planned_tool(pending)
        if planned_tool is not None and planned_tool not in allowed:
            return None

        planned_input = self._pending_plan_input(pending)
        if planned_tool is not None and isinstance(planned_input, dict):
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": planned_tool,
                "input": json.dumps(
                    planned_input,
                    ensure_ascii=False,
                ),
            }

        planned_tool = self._pending_planned_tool(pending)
        if planned_tool in allowed:
            tool_meta = getattr(self.tools, "tools", {}).get(planned_tool, {})
            tool_description = (
                str(tool_meta.get("description", "")).lower()
                if isinstance(tool_meta, dict)
                else ""
            )

        # A text-only legacy plan still needs an execution adapter. This does
        # not infer intent from the user's message: it translates only the
        # already-selected pending desktop step and remains subject to the
        # allowed-tools check above.
        if planned_tool == "desktop" and "desktop" in allowed:
            desktop_decision = self._force_desktop_decision(action_text)
            if desktop_decision and desktop_decision.get("tool") == "desktop":
                return desktop_decision
        write_words = ("file", "script", "program", "source", "code")
        write_intent = (
            "write_file" in pending_lower
            or ("write" in pending_lower and any(word in pending_lower for word in write_words))
            or ("create" in pending_lower and any(word in pending_lower for word in write_words))
            or ("save" in pending_lower and any(word in pending_lower for word in write_words))
            or ("generate" in pending_lower and any(word in pending_lower for word in write_words))
            or ("make" in pending_lower and any(word in pending_lower for word in write_words))
        )
        if write_intent and "write_file" in allowed:
            path = None
            # Prefer an explicit filename from the planner, preserving case.
            path = self._extract_filename(pending) or self._extract_filename(str(message or ""))


            # Otherwise derive a stable filename from the user's request.
            if not path:
                text = str(message or "").lower()
                if "c++" in text or "c plus plus" in text or "cpp" in text:
                    path = "hello.cpp"
                elif "python" in text:
                    path = "script.py"
                elif "javascript" in text:
                    path = "script.js"
                elif "typescript" in text:
                    path = "script.ts"
                elif "rust" in text:
                    path = "script.rs"
                elif "java" in text:
                    path = "Main.java"
                elif "golang" in text or re.search(r"\bgo\b", text):
                    path = "script.go"
                elif any(x in text for x in ("deep learning", "deeplearning", "neural network", "pytorch", "tensorflow")):
                    path = "deep_learning_model.py"
                elif "model" in text:
                    path = "model.py"
                else:
                    path = "generated_code.txt"

            # BUG 28: Sanitize write_file path to prevent directory traversal
            if path:
                # Normalize path separators and remove any parent directory references
                path = path.replace("\\", "/")
                # Split into parts and remove ".." and "." segments
                parts = [p for p in path.split("/") if p not in ("..", ".", "")]
                path = "/".join(parts)
                # Ensure no leading slash (prevent absolute paths)
                path = path.lstrip("/")

            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "write_file",
                "input": json.dumps({
                    "path": path,
                    "location": "projects"
                }, ensure_ascii=False)
            }

        filename = self._extract_filename(
            f"{pending} {message or ''}"
        )

        if planned_tool == "find_files" and "file" in tool_description:
            combined = f"{pending} {message or ''}"

            age_match = re.search(
                r"\b(?:last|past)\s+(\d+)\s*(?:hours?|hrs?)\b",
                combined,
                flags=re.IGNORECASE,
            )
            created_match = re.search(
                r"\b(?:created|made|created\s+for\s+me)\b",
                combined,
                flags=re.IGNORECASE,
            )
            modified_match = re.search(
                r"\b(?:modified|changed|updated)\b",
                combined,
                flags=re.IGNORECASE,
            )

            payload = {
                "path": ".",
                "location": (
                    "desktop"
                    if re.search(r"\bdesktop\b", combined, re.IGNORECASE)
                    else "projects"
                ),
                "recursive": True,
            }

            filename = self._extract_filename(combined)
            if filename:
                payload["pattern"] = filename
            if age_match:
                hours = int(age_match.group(1))
                if created_match:
                    payload["created_within_hours"] = hours
                elif modified_match:
                    payload["modified_within_hours"] = hours

            return {
                "action": "tool",
                "task_type": "computer",
                "tool": planned_tool,
                "input": json.dumps(payload, ensure_ascii=False),
            }

        if planned_tool is not None:
            combined = f"{pending} {message or ''}"

            if (
                "file" in tool_description
                and re.search(r"\bread\b", action_lower)
                and filename
            ):
                location = (
                    "desktop"
                    if re.search(r"\bdesktop\b", combined, re.IGNORECASE)
                    else "projects"
                )
                return {
                    "action": "tool",
                    "task_type": "computer",
                    "tool": planned_tool,
                    "input": json.dumps(
                        {"path": filename, "location": location},
                        ensure_ascii=False,
                    ),
                }

            if (
                "file" in tool_description
                and re.search(r"\blist\b", action_lower)
            ):
                location = (
                    "desktop"
                    if re.search(r"\bdesktop\b", combined, re.IGNORECASE)
                    else "projects"
                )
                return {
                    "action": "tool",
                    "task_type": "computer",
                    "tool": planned_tool,
                    "input": json.dumps(
                        {"path": ".", "location": location},
                        ensure_ascii=False,
                    ),
                }

            if (
                "directory" in tool_description
                and re.search(r"\b(?:create|make)\b", action_lower)
            ):
                folder_match = re.search(
                    r"(?:directory|folder)\s+(?:called|named)?\s*([A-Za-z0-9_.-]+)",
                    combined,
                    re.IGNORECASE,
                )
                if folder_match:
                    location = (
                        "desktop"
                        if re.search(r"\bdesktop\b", combined, re.IGNORECASE)
                        else "projects"
                    )
                    return {
                        "action": "tool",
                        "task_type": "computer",
                        "tool": planned_tool,
                        "input": json.dumps(
                            {"path": folder_match.group(1), "location": location},
                            ensure_ascii=False,
                        ),
                    }

        if planned_tool is not None and "web" in tool_description and "search" in tool_description:
            query = re.sub(
                r'^\s*(?:go\s+and\s+)?(?:search|look\s+up)(?:\s+(?:the\s+web|the\s+internet|online))?\s*(?:for|about)?\s*',
                '',
                str(message or '').strip(),
                flags=re.IGNORECASE,
            ).strip()
            if query:
                return {
                    "action": "tool",
                    "task_type": "computer",
                    "tool": planned_tool,
                    "input": json.dumps({"query": query}, ensure_ascii=False),
                }

        if planned_tool is not None and "terminal" in tool_description and re.search(
            r'\b(?:run|execute)\b',
            action_lower,
        ):
            match = re.search(
                r'(?:run|execute)\s+(?:the\s+)?(?:command|script)?\s*["\'](.+?)["\']',
                str(message or '').strip(),
                flags=re.IGNORECASE,
            )
            if match:
                return {
                    "action": "tool",
                    "task_type": "computer",
                    "tool": planned_tool,
                    "input": json.dumps(
                        {"command": match.group(1).strip(), "location": "projects"},
                        ensure_ascii=False,
                    ),
                }

        return None
    _MAX_RETRIES = 3

    def decide(
        self,
        message,
        task_type,
        conversation="",
        knowledge="",
        tool_history="",
        plan="No plan.",
        allowed_tools=None
    ):
        # BUG 22: Handle invalid task_type gracefully
        if task_type not in {"computer", "conversation"}:
            logging.warning("Invalid task_type: %s, defaulting to conversation", task_type)
            task_type = "conversation"

        # BUG 34: Max retry counter
        retry_count = 0

        has_successful_tool = (
            self._has_successful_tool(
                tool_history
            )
        )

        # The plan is authoritative. Resolve its pending step before looking
        # at the whole user message so compound tasks keep their order.
        deterministic = self._deterministic_plan_decision(
            message=message,
            task_type=task_type,
            plan=plan,
            tool_history=tool_history,
            allowed_tools=allowed_tools
        )
        if deterministic:
            self._remember_file_generation(deterministic)
            return deterministic

        prompt = self._build_decision_prompt(
            message=message,
            task_type=task_type,
            conversation=conversation,
            knowledge=knowledge,
            tool_history=tool_history,
            plan=plan,
            allowed_tools=allowed_tools
        )

        # BUG 30: System prompt should not say "think step by step" when output should be code only
        try:
            raw = self.brain.generate(
                prompt,
                system_prompt="You are Nova, a precise AI agent. Return ONLY valid JSON. No explanation. No extra text."
            )
        except Exception as exc:
            # BUG 42+43: Log before swallowing
            logging.warning("Primary brain.generate failed: %s", exc)
            raw = ""

        data = self._extract_json(
            raw
        )

        if task_type == "conversation":

            response_decision = (
                self._validate_response_decision(
                    data,
                    "conversation",
                    has_successful_tool
                )
            )

            if response_decision:
                return response_decision

        if task_type == "computer":

            tool_decision = (
                self._validate_tool_decision(
                    data,
                    "computer"
                )
            )

            pending_tool = None
            if isinstance(plan, str):
                for plan_line in plan.splitlines():
                    if "[pending]" in plan_line.lower():
                        pending_tool = self._pending_planned_tool(plan_line)
                        break

            if (
                tool_decision
                and pending_tool is not None
                and tool_decision.get("tool") != pending_tool
            ):
                tool_decision = None

            if tool_decision:

                if allowed_tools is not None and tool_decision.get("tool") not in set(allowed_tools):
                    tool_decision = None
                else:
                    self._remember_file_generation(
                        tool_decision
                    )

                return tool_decision

            function_call = (
                self._extract_function_call(
                    raw
                )
            )

            if function_call:

                validated_function_call = (
                    self._validate_tool_decision(
                        function_call,
                        "computer"
                    )
                )

                if validated_function_call:

                    if pending_tool is not None and validated_function_call.get("tool") != pending_tool:
                        validated_function_call = None
                    elif search_requested and validated_function_call.get("tool") != "web_search":
                        validated_function_call = None
                    elif allowed_tools is not None and validated_function_call.get("tool") not in set(allowed_tools):
                        validated_function_call = None
                    else:
                        self._remember_file_generation(
                            validated_function_call
                        )
                        return validated_function_call

            response_decision = (
                self._validate_response_decision(
                    data,
                    "computer",
                    has_successful_tool
                )
            )

            if response_decision:
                return response_decision

        repair_prompt = self._build_repair_prompt(
            message=message,
            task_type=task_type,
            conversation=conversation,
            tool_history=tool_history,
            plan=plan,
            allowed_tools=allowed_tools,
            knowledge=knowledge
        )

        try:

            raw = self.brain.generate(
                repair_prompt,
                json_mode=True
            )

        except Exception:

            raw = ""

        data = self._extract_json(
            raw
        )

        # BUG 21: Recompute pending_tool in repair pass (may have changed)
        if isinstance(plan, str):
            pending_tool = None
            for plan_line in plan.splitlines():
                if "[pending]" in plan_line.lower():
                    pending_tool = self._pending_planned_tool(plan_line)
                    break

        if task_type == "computer":

            tool_decision = (
                self._validate_tool_decision(
                    data,
                    "computer"
                )
            )

            if tool_decision and pending_tool is not None and tool_decision.get("tool") != pending_tool:
                tool_decision = None

            if tool_decision and search_requested and tool_decision.get("tool") != "web_search":
                tool_decision = None

            if tool_decision:

                # BUG 27: Empty allowed_tools list means no tools allowed
                if allowed_tools is not None:
                    if len(allowed_tools) == 0 or tool_decision.get("tool") not in set(allowed_tools):
                        tool_decision = None
                    else:
                        self._remember_file_generation(
                            tool_decision
                        )
                        return tool_decision
                else:
                    self._remember_file_generation(
                        tool_decision
                    )
                    return tool_decision

            function_call = (
                self._extract_function_call(
                    raw
                )
            )

            if function_call:

                validated_function_call = (
                    self._validate_tool_decision(
                        function_call,
                        "computer"
                    )
                )

                if validated_function_call:
                    if pending_tool is not None and validated_function_call.get("tool") != pending_tool:
                        validated_function_call = None
                    elif search_requested and validated_function_call.get("tool") != "web_search":
                        validated_function_call = None
                    elif allowed_tools is not None:
                        # BUG 27: Empty allowed_tools list means no tools allowed
                        if len(allowed_tools) == 0 or validated_function_call.get("tool") not in set(allowed_tools):
                            validated_function_call = None
                        else:
                            self._remember_file_generation(
                                validated_function_call
                            )
                            return validated_function_call
                    else:
                        self._remember_file_generation(
                            validated_function_call
                        )
                        return validated_function_call

            response_decision = (
                self._validate_response_decision(
                    data,
                    "computer",
                    has_successful_tool
                )
            )

            if response_decision:
                return response_decision

            # BUG 34: Return retry with limit indication
            retry_count += 1
            return {
                "action": "retry",
                "task_type": "computer",
                "retry_count": retry_count,
                "max_retries": self._MAX_RETRIES
            }

        response_decision = (
            self._validate_response_decision(
                data,
                "conversation",
                has_successful_tool
            )
        )

        if response_decision:
            return response_decision

        return {
            "action": "retry",
            "task_type": "conversation"
        }
