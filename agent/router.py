
import json
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

    def _extract_function_call(self, response):

        if not response:
            return None

        text = str(response).strip()

        pattern = re.compile(
            r"\[\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*"
            r"\(\s*(.*?)\s*\)\s*\]",
            re.DOTALL
        )

        match = pattern.search(text)

        if not match:
            return None

        tool_name = match.group(1).strip()
        arguments = match.group(2).strip()

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
        # Pattern to match key="value", key='value', or key=value (no spaces around =)
        # Handles quoted values with escaped quotes
        pattern = re.compile(
            r"""
            (\w+)               # key
            \s*=\s*             # =
            (?:                 # value
                "((?:[^"\\]|\\.)*)"   # double-quoted
                |
                '((?:[^'\\]|\\.)*)'   # single-quoted
                |
                ([^,\s]+)       # unquoted (no commas, no spaces)
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

    def _has_successful_tool(self, tool_history):

        if not tool_history:
            return False

        success_markers = [
            "STATUS: SUCCESS",
            "FILE_CREATED",
            "DIRECTORY_CREATED",
            "Verification: CONFIRMED",
            "Tool success: True",
        ]

        return any(
            marker.lower() in tool_history.lower()
            for marker in success_markers
        )

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

    def _normalize_tool_input(self, tool_input):

        if isinstance(tool_input, dict):

            return json.dumps(
                tool_input,
                ensure_ascii=False
            )

        if isinstance(tool_input, str):

            stripped = tool_input.strip()

            if not stripped:
                return None

            try:

                parsed = json.loads(
                    stripped
                )

                if isinstance(parsed, dict):

                    return json.dumps(
                        parsed,
                        ensure_ascii=False
                    )

            except json.JSONDecodeError:
                pass

            return stripped

        return None

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
                "desktop"
            }:
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
                "desktop"
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
                "desktop"
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
                "desktop"
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
                and location in {"projects", "desktop"}
            )

        # Unknown tool — allow through, let the tool handle validation
        return True

    # Desktop intent — force desktop tool before model decides
    _desktop_intent = re.compile(
        r"\b(?:"
        r"screenshot|take\s+a\s+screenshot|capture\s+screen"
        r"|open\s+(?:app|application)\b|launch\s+(?:app|application)\b"
        r"|close\s+(?:app|application)\b"
        r"|click\s+(?:on\s+)?(?:the\s+)?"
        r"|move\s+(?:the\s+)?mouse"
        r"|type\s+(?:into|in|on)"
        r"|press\s+(?:key|ctrl|alt|enter|escape)"
        r"|scroll\s+(?:up|down)"
        r"|list\s+(?:open\s+)?windows"
        r"|focus\s+window"
        r"|control\s+(?:the\s+)?(?:mouse|keyboard|screen)"
        r")\b",
        re.IGNORECASE
    )

    def _has_desktop_intent(self, message):
        return bool(self._desktop_intent.search(message))

    def _force_desktop_decision(self, message):
        """Build a desktop tool decision directly from message intent."""
        import re as _re
        msg = message.lower()

        # Screenshot
        if any(w in msg for w in ["screenshot", "capture screen", "take a screenshot"]):
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "desktop",
                "input": json.dumps({"action": "screenshot"})
            }

        # List windows
        if "list" in msg and "window" in msg:
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "desktop",
                "input": json.dumps({"action": "get_windows"})
            }

        # Close app
        close_pat = r'close' + r'\s+' + r'(?:the\s+)?' + r'(\w[\w\s]*?)' + r'(?:\s+app)?\s*$'
        close_match = _re.search(close_pat, msg)
        if close_match:
            title = close_match.group(1).strip()
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "desktop",
                "input": json.dumps({"action": "close_app", "title": title})
            }

        # Open app
        open_pat = r'open' + r'\s+' + r'(?:the\s+|app\s+)?' + r'(\w[\w\s]*?)' + r'(?:\s+app)?\s*$'
        open_match = _re.search(open_pat, msg)
        if open_match:
            app = open_match.group(1).strip()
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "desktop",
                "input": json.dumps({"action": "open_app", "app": app})
            }

        # Default: screenshot
        return {
            "action": "tool",
            "task_type": "computer",
            "tool": "desktop",
            "input": json.dumps({"action": "screenshot"})
        }


    _search_intent_pattern = re.compile(
        r"""
        \b
        (?:
            web\s*search
            | search\s+(?:the\s+)?(?:web|internet)
            | search\s+(?:about|for|up)
            | go\s+and\s+search
            | google\s+
            | look\s+up
            | find\s+(?:about|information\s+about)
        )
        \b
        """,
        re.IGNORECASE | re.VERBOSE
    )

    def _has_search_intent(self, message):
        if not isinstance(
            message,
            str
        ):
            return False

        return bool(
            self._search_intent_pattern.search(
                message
            )
        )

    def _is_obviously_conversational(self, message):
        """Fast-path greetings and casual chat so they never enter tool execution."""
        if not isinstance(message, str):
            return False

        text = re.sub(r"\\s+", " ", message.strip().lower())
        if not text:
            return False

        casual = {
            "hi", "hello", "hey", "hey nova", "hi nova", "hello nova",
            "yo", "sup", "what's up", "whats up", "how are you",
            "how are you?", "good morning", "good afternoon", "good evening",
            "good night", "thanks", "thank you", "thx", "bye", "goodbye"
        }

        return text in casual

    def _has_explicit_computer_intent(self, message):
        """Detect direct requests that require real computer/tool actions."""
        if not isinstance(message, str):
            return False

        text = re.sub(r"\s+", " ", message.strip().lower())
        if not text:
            return False

        # Questions that start with how/what/why are usually conversational.
        if re.match(r"^(?:how|what|why|can|could|would)\b", text):
            return bool(re.search(
                r"\b(?:for me|on my (?:pc|computer)|in (?:the )?(?:projects|desktop) folder|to (?:create|write|run|read|edit|delete|modify))\b",
                text,
            ))

        patterns = [
            r"\b(?:create|make|write|save|overwrite|generate|edit|modify|delete|remove|read|open)\b[^\n]{0,80}\.(?:py|pyw|js|ts|tsx|jsx|cpp|c|h|java|rs|go|md|txt|json)\b",
            r"\b(?:create|make|write|save|generate)\b[^\n]{0,100}\b(?:file|script|program|source|source code|code)\b",
            r"\b(?:write|create|make|generate)\b[^\n]{0,60}\b(?:python|c\+\+|cpp|javascript|typescript|rust|java|golang)\b",
            r"\b(?:run|execute)\b[^\n]{0,80}\b(?:command|script|program|python|powershell|shell)\b",
            r"\b(?:terminal|powershell|cmd|shell)\b",
            r"\b(?:git|github)\b[^\n]{0,100}\b(?:clone|commit|push|pull|checkout|branch|status|init|add|create repo|repository)\b",
            r"\b(?:search|look up|find|google)\b[^\n]{0,60}\b(?:web|internet|online)\b",
            r"\b(?:screenshot|capture (?:the )?screen|open app|launch app|click|move (?:the )?mouse|press (?:key|ctrl|alt|enter|escape)|scroll)\b",
            r"\b(?:in|inside) (?:the )?(?:projects|desktop) (?:folder|directory)\b",
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

    def classify_task(self, message, conversation=""):

        if self._is_obviously_conversational(message):
            return "conversation"

        if self._has_explicit_computer_intent(message):
            return "computer"

        prompt = f"""You are a task classifier for Nova, a local AI agent.

Decide if Nova needs to USE TOOLS to respond, or just TALK.

Answer "computer" if Nova must actually DO something:
- Access, read, write, create, delete, or modify files
- Run terminal commands or scripts
- Use git (clone, commit, push, pull, study a repo, etc.)
- Search the web
- Install packages
- Inspect, analyze, or study any file, folder, URL, or repository
- Anything that requires interacting with the computer or external systems

Answer "conversation" if Nova only needs to TALK:
- Explaining concepts
- Answering questions from memory
- Writing text that the user will copy manually
- General chat
- Asking the user for missing information (like a token or password)

KEY INSIGHT: If the user wants Nova to DO something (even passively like
"study this", "look at this", "analyze this", "check this"), that requires
tools → computer.
If the user just wants Nova to TELL them something → conversation.

SPECIAL CASE - GitHub repo creation:
If the user wants to create a GitHub repo but no GitHub token (ghp_...) 
appears in the conversation, Nova must ask for it first → conversation.
If a token IS present in the conversation → computer.

Examples:
- "study this repo https://github.com/..." → computer
- "create a github repo" (no token in conversation) → conversation
- "create a github repo" (token already given) → computer
- "what is a linked list?" → conversation
- "create a calculator.py file" → computer
- "how does git work?" → conversation
- "commit my changes" → computer

User message: {message}

Previous conversation: {conversation}

Return ONLY valid JSON. No explanation.
{{"task_type": "computer"}} or {{"task_type": "conversation"}}"""

        try:
            raw = self.brain.generate(prompt, json_mode=True)
        except Exception:
            raw = ""

        data = self._extract_json(raw)

        if isinstance(data, dict):
            task_type = self._normalize_task_type(data.get("task_type"))
            if task_type:
                return task_type

        # Repair pass with even simpler prompt
        repair_prompt = f"""Does this request require Nova to use tools (files, terminal, git, web)?

Request: {message}

Reply ONLY: {{"task_type":"computer"}} or {{"task_type":"conversation"}}"""

        try:
            raw = self.brain.generate(repair_prompt, json_mode=True)
        except Exception:
            raw = ""

        data = self._extract_json(raw)

        if isinstance(data, dict):
            task_type = self._normalize_task_type(data.get("task_type"))
            if task_type:
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
        if allowed_tools is None:
            tool_names = ", ".join(self._get_tool_names())
        else:
            tool_names = ", ".join(
                n for n in self._get_tool_names()
                if n in set(allowed_tools)
            )

        # Truncate tool_history to last 500 chars to keep prompt short
        if tool_history and len(tool_history) > 500:
            tool_history = "..." + tool_history[-500:]

        # Keep the beginning of the plan because it contains the first pending step.
        if plan and len(plan) > 1200:
            plan = plan[:1200]

        return f"""You are Nova. Choose the next tool to run.

TOOLS: {tool_names}

PLAN:
{plan}

TOOL HISTORY:
{tool_history if tool_history else "None"}

USER REQUEST: {message}

RULES:
- Look at the plan. Find the first pending step. Run that tool.
- For write_file: ONLY return path and location. Never include content or code.
- For terminal: return the command to run.
- For git: return action and required fields.
- Keep response under 80 tokens.

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
        tool_history,
        plan="No plan.",
        allowed_tools=None
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

        return f"""
You are Nova's action validator.

Return ONLY valid JSON.

TASK TYPE:

{task_type}

USER REQUEST:

{message}

REAL TOOL HISTORY:

{tool_history}

CURRENT PLAN:

{plan}

If the computer task is incomplete,
choose the next real tool.

Available tools:

{tools_description}

Only the tools listed above are enabled for this request.

IMPORTANT:

If the user explicitly requested a web search
and no successful web_search result exists,
YOU MUST choose web_search.

For web_search:

{{
  "action": "tool",
  "task_type": "computer",
  "tool": "web_search",
  "input": {{
    "query": "search query"
  }}
}}

For write_file (ONLY path + location, NO content, NO code):

{{
  "action": "tool",
  "task_type": "computer",
  "tool": "write_file",
  "input": {{
    "path": "filename.py",
    "location": "projects"
  }}
}}

For edit_file (modify existing file):

{{
  "action": "tool",
  "task_type": "computer",
  "tool": "edit_file",
  "input": {{
    "path": "filename",
    "location": "projects",
    "old": "text to replace",
    "new": "replacement text"
  }}
}}

For delete_file:

{{
  "action": "tool",
  "task_type": "computer",
  "tool": "delete_file",
  "input": {{
    "path": "filename",
    "location": "projects"
  }}
}}

Do NOT generate file content in the
decision JSON.

For read_file:

{{
  "action": "tool",
  "task_type": "computer",
  "tool": "read_file",
  "input": {{
    "path": "filename",
    "location": "projects"
  }}
}}

For list_files:

{{
  "action": "tool",
  "task_type": "computer",
  "tool": "list_files",
  "input": {{
    "path": ".",
    "location": "projects"
  }}
}}

For create_directory:

{{
  "action": "tool",
  "task_type": "computer",
  "tool": "create_directory",
  "input": {{
    "path": "directory_name",
    "location": "projects"
  }}
}}

For terminal:

{{
  "action": "tool",
  "task_type": "computer",
  "tool": "terminal",
  "input": {{
    "command": "command",
    "location": "projects"
  }}
}}

For git:

{{
  "action": "tool",
  "task_type": "computer",
  "tool": "git",
  "input": {{
    "action": "clone",
    "url": "https://github.com/..."
  }}
}}

If the entire task is completed:

{{
  "action": "respond",
  "task_type": "computer",
  "goal_complete": true
}}

Return JSON only.
"""

    def generate_file_content(
        self,
        user_request,
        path,
        location,
        conversation="",
        tool_history=""
    ):
        self._last_file_generation_error = None

        extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        language = {
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
        }.get(extension, "source")

        prompt = (
            f"Generate complete raw {language} source code for \"{path}\".\n\n"
            f"User request: {user_request}\n\n"
            "Output source code only. No Markdown fences, explanation, JSON, placeholders, TODOs, or ellipsis."
        )

        try:
            raw = self.brain.generate(
                prompt,
                system_prompt=(
                    f"You are a code generator. Return only valid raw {language} source code."
                ),
                json_mode=False,
                options={
                    "temperature": 0.0,
                    "num_predict": 256,
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

    def _deterministic_plan_decision(self, message, task_type, plan, tool_history, allowed_tools=None):
        """Return a tool decision for an unambiguous pending plan step.

        Tool selection for concrete computer actions must not depend entirely on
        a second LLM decision. The planner already produced the next action;
        use it deterministically and let the LLM generate only the file content.
        """
        if task_type != "computer" or not isinstance(plan, str):
            return None

        allowed = set(allowed_tools or self.tools.tools.keys())
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
            return {
                "action": "tool",
                "task_type": "computer",
                "tool": "write_file",
                "input": json.dumps({
                    "path": path,
                    "location": "projects"
                }, ensure_ascii=False)
            }

        filename = self._extract_filename(f"{pending} {message or ''}")

        simple_tools = (
            ("read_file", ("read file", "open file", "inspect file", "check file")),
            ("list_files", ("list files", "list directory", "list folder", "show files")),
            ("create_directory", ("create directory", "create folder", "make directory", "make folder")),
        )

        for tool_name, aliases in simple_tools:
            if tool_name not in allowed:
                continue
            if not any(alias in pending_lower for alias in aliases):
                continue

            if tool_name == "read_file":
                if not filename:
                    return None
                payload = {"path": filename, "location": "projects"}
            elif tool_name == "list_files":
                payload = {"path": ".", "location": "projects"}
            else:
                folder_match = re.search(
                    r"(?:directory|folder)\s+(?:called|named)?\s*([A-Za-z0-9_.-]+)",
                    f"{pending} {message or ''}",
                    re.IGNORECASE,
                )
                if not folder_match:
                    return None
                payload = {
                    "path": folder_match.group(1),
                    "location": "projects",
                }

            return {
                "action": "tool",
                "task_type": "computer",
                "tool": tool_name,
                "input": json.dumps(payload, ensure_ascii=False),
            }

        if "web_search" in allowed and any(
            alias in pending
            for alias in ("web search", "search the web", "search the internet", "look up")
        ):
            query = re.sub(
                r"^\s*(?:go and )?(?:search|look up)(?: the web| the internet| online)?\s*(?:for|about)?\s*",
                "",
                str(message or "").strip(),
                flags=re.IGNORECASE,
            ).strip()
            if query:
                return {
                    "action": "tool",
                    "task_type": "computer",
                    "tool": "web_search",
                    "input": json.dumps({"query": query}, ensure_ascii=False),
                }

        if "terminal" in allowed and any(
            alias in pending
            for alias in ("run command", "run terminal", "execute command", "run script", "execute script")
        ):
            match = re.search(
                r'(?:run|execute)\s+(?:the\s+)?(?:command|script)?\s*["\'](.+?)["\']',
                str(message or "").strip(),
                flags=re.IGNORECASE,
            )
            if match:
                return {
                    "action": "tool",
                    "task_type": "computer",
                    "tool": "terminal",
                    "input": json.dumps(
                        {"command": match.group(1).strip(), "location": "projects"},
                        ensure_ascii=False,
                    ),
                }

        return None

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

        has_successful_tool = (
            self._has_successful_tool(
                tool_history
            )
        )

        # Deterministic execution for an explicit pending plan step.
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

        try:

            raw = self.brain.generate(
                prompt,
                json_mode=True
            )

        except Exception:

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

            # Force desktop tool for OS control requests
            if self._has_desktop_intent(message) and not has_successful_tool:
                desktop_decision = self._force_desktop_decision(message)
                if desktop_decision:
                    return desktop_decision

            search_requested = (
                self._has_search_intent(
                    message
                )
                and not has_successful_tool
            )

            tool_decision = (
                self._validate_tool_decision(
                    data,
                    "computer"
                )
            )

            if (
                tool_decision
                and search_requested
                and tool_decision.get(
                    "tool"
                ) != "web_search"
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

                    if allowed_tools is not None and validated_function_call.get("tool") not in set(allowed_tools):
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
            tool_history=tool_history,
            plan=plan,
            allowed_tools=allowed_tools
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

        if task_type == "computer":

            tool_decision = (
                self._validate_tool_decision(
                    data,
                    "computer"
                )
            )

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
                    if (
                        allowed_tools is not None
                        and validated_function_call.get("tool") not in set(allowed_tools)
                    ):
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

            return {
                "action": "retry",
                "task_type": "computer"
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

