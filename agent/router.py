
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

        markers = [
            "STATUS: SUCCESS",
            "FILE_CREATED",
            "DIRECTORY_CREATED",
            "Tool: web_search"
        ]

        return any(
            marker in tool_history
            for marker in markers
        )

    def _get_tool_names(self):

        if not self.tools.tools:
            return []

        return list(
            self.tools.tools.keys()
        )

    def _contains_placeholder(self, value):

        if not isinstance(value, str):
            return False

        text = value.strip().lower()

        placeholders = [
            "...",
            "…",
            "<code>",
            "</code>",
            "<code here>",
            "code here",
            "insert code here",
            "your code here",
            "actual code",
            "actual python code",
            "actual python calculator code",
            "write code here",
            "put code here",
            "todo",
            "tbd"
        ]

        return any(
            marker in text
            for marker in placeholders
        )

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

        return False

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

    def classify_task(
        self,
        message,
        conversation=""
    ):

        if self._has_search_intent(
            message
        ):
            return "computer"

        prompt = f"""
You are Nova's task classifier.

Classify ONLY the user's CURRENT request.

There are exactly two possible task types:

conversation

computer

A computer task means Nova must actually
perform one or more operations using real tools.

A conversation task means Nova only needs to
answer the user and does not need to operate
the computer.

Use "computer" when the user asks Nova to:

- create a file
- save a file
- write a file
- modify a file
- edit a project
- create a directory
- read a file
- inspect files
- list files
- run a program
- execute a command
- compile code
- test code
- debug code
- inspect terminal output
- work on a project
- operate on the desktop
- search the public web

Use "conversation" when the user only wants:

- explanation
- information
- brainstorming
- advice
- normal conversation
- code shown in chat
- examples
- tutorials
- conceptual help

If the user asks to CREATE, SAVE, MODIFY,
READ, RUN, TEST, COMPILE, DEBUG, INSPECT,
OPERATE, or SEARCH something, use:

computer

USER REQUEST:

{message}

PREVIOUS CONVERSATION:

{conversation}

Return ONLY valid JSON.

{{"task_type":"conversation"}}

or

{{"task_type":"computer"}}
"""

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

        if isinstance(data, dict):

            task_type = (
                self._normalize_task_type(
                    data.get("task_type")
                )
            )

            if task_type:
                return task_type

        repair_prompt = f"""
Return ONLY valid JSON.

Classify the request as:

{{"task_type":"conversation"}}

or

{{"task_type":"computer"}}

Use computer when Nova must actually
create, save, modify, read, run, compile,
test, debug, inspect, search the web,
or operate something.

USER REQUEST:

{message}
"""

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

        if isinstance(data, dict):

            task_type = (
                self._normalize_task_type(
                    data.get("task_type")
                )
            )

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
        plan="No plan."
    ):

        has_tool_result = bool(
            tool_history.strip()
        )

        has_successful_tool = (
            self._has_successful_tool(
                tool_history
            )
        )

        tools_description = (
            self.tools.get_descriptions()
        )

        tool_names = ", ".join(
            self._get_tool_names()
        )

        return f"""
You are Nova's autonomous action planner.

Your ONLY job is to choose the NEXT REAL ACTION.

You are NOT the final answer generator.

TERMINAL INTERACTIVE PROGRAM RULE

If a terminal command launches an interactive program
that expects input, do not leave it waiting for a human.

Prefer providing test input in the terminal input field,
for example:
{{"command":"python calc.py","input":"2+3\n"}}

Or use a non-interactive command that tests the program.
Never assume a command succeeded merely because it started.

AVAILABLE TOOLS:

{tools_description}

TOOL NAMES:

{tool_names}

TASK TYPE:

{task_type}

The task classifier already determined
the task type.

Do not change it.

REALITY RULE:

Only actual tool results prove that an
operation happened.

Never invent:

- files
- paths
- commands
- terminal output
- execution results
- compilation results
- file contents
- successful operations
- web search results

CURRENT PLAN:

{plan}

The plan describes the goal and ordered work.
Use it to choose the next real tool action.
Do not assume a plan step is complete unless
the tool history contains real evidence.

CURRENT STATE:

Has a tool been used?

{has_tool_result}

Has a successful tool result been observed?

{has_successful_tool}

TOOL HISTORY:

{tool_history}

COMPUTER TASK:

If task_type is computer and the user's
request is incomplete, choose a real tool.

Do NOT answer with instructions instead
of performing the requested operation.

Do NOT return source code as the final answer
when the user requested an actual file.

TOOL SELECTION:

Creating or saving a file:
write_file

Reading a file:
read_file

Listing files:
list_files

Creating a directory:
create_directory

Running, compiling, testing, or executing:
terminal

Searching the public web:
web_search

IMPORTANT:

If the user explicitly asks to search the web,
you MUST select:

web_search

Do not answer from memory.

Do not say you cannot access the web.

Do not generate a fake search result.

WEB SEARCH INPUT:

{{
  "query": "search query"
}}

IMPORTANT WRITE_FILE RULE:

When selecting write_file, DO NOT generate
the file content yet.

Only decide:

- which file
- which location

The actual file content will be generated
in a separate generation step.

Therefore write_file input MUST contain:

{{
  "path": "filename",
  "location": "projects"
}}

Do NOT put "content" in this decision.

COMPLETION:

Return "respond" ONLY if the user's requested
operation is already completely finished and
verified by a real tool result.

If more work is required, return "tool".

USER REQUEST:

{message}

CONVERSATION:

{conversation}

KNOWLEDGE:

{knowledge}

Return ONLY valid JSON.

For an unfinished computer task:

{{
  "action": "tool",
  "task_type": "computer",
  "tool": "TOOL_NAME",
  "input": {{
    "key": "value"
  }}
}}

For a completed computer task:

{{
  "action": "respond",
  "task_type": "computer",
  "goal_complete": true
}}

For conversation:

{{
  "action": "respond",
  "task_type": "conversation"
}}
"""

    def _validate_tool_decision(
        self,
        data,
        task_type
    ):

        if not isinstance(
            data,
            dict
        ):
            return None

        action = self._normalize_action(
            data.get("action")
        )

        if action != "tool":
            return None

        tool = data.get("tool")

        if not isinstance(
            tool,
            str
        ):
            return None

        tool = tool.strip()

        if not tool:
            return None

        if not self.tools.exists(
            tool
        ):
            return None

        raw_input = data.get(
            "input"
        )

        if isinstance(
            raw_input,
            dict
        ):

            tool_input_object = raw_input

        elif isinstance(
            raw_input,
            str
        ):

            try:

                tool_input_object = json.loads(
                    raw_input
                )

            except json.JSONDecodeError:

                if tool == "web_search":

                    tool_input_object = {
                        "query": raw_input
                    }

                else:

                    return None

            if not isinstance(
                tool_input_object,
                dict
            ):
                return None

        else:

            return None

        if tool == "web_search":

            normalized_web_input = (
                self._normalize_web_search_input(
                    tool_input_object
                )
            )

            if normalized_web_input is None:
                return None

            tool_input_object = json.loads(
                normalized_web_input
            )

        if not self._validate_basic_tool_input(
            tool,
            tool_input_object
        ):
            return None

        normalized_input = (
            self._normalize_tool_input(
                tool_input_object
            )
        )

        if normalized_input is None:
            return None

        return {
            "action": "tool",
            "task_type": task_type,
            "tool": tool,
            "input": normalized_input
        }

    def _validate_response_decision(
        self,
        data,
        task_type,
        has_successful_tool
    ):

        if not isinstance(
            data,
            dict
        ):
            return None

        action = self._normalize_action(
            data.get("action")
        )

        if action != "respond":
            return None

        returned_task_type = (
            self._normalize_task_type(
                data.get("task_type")
            )
        )

        if returned_task_type != task_type:
            return None

        if task_type == "conversation":

            return {
                "action": "respond",
                "task_type": "conversation"
            }

        goal_complete = (
            data.get("goal_complete") is True
        )

        if not goal_complete:
            return None

        if not has_successful_tool:
            return None

        return {
            "action": "respond",
            "task_type": "computer",
            "goal_complete": True
        }

    def _build_repair_prompt(
        self,
        message,
        task_type,
        tool_history,
        plan="No plan."
    ):

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

{self.tools.get_descriptions()}

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

For write_file:

{{
  "action": "tool",
  "task_type": "computer",
  "tool": "write_file",
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

        prompt = f"""
You are Nova's code generation engine.

Generate the COMPLETE ACTUAL CONTENT of ONE FILE.

The file will be written directly to disk.

USER REQUEST:

{user_request}

TARGET FILE:

{path}

LOCATION:

{location}

CONVERSATION:

{conversation}

PREVIOUS TOOL RESULTS:

{tool_history}

RULES:

1. Generate the complete file.

2. Do not explain the code.

3. Do not describe the code.

4. Do not use placeholders.

5. Do not use ellipsis.

6. Do not write "code here".

7. Do not write TODO instead of implementation.

8. Do not wrap the file in Markdown fences.

9. The output must be directly usable as
the contents of the target file.

10. Include imports, functions, classes,
main logic, and required supporting code
when they are necessary.

11. Do not omit sections for brevity.

12. Do not say "the rest of the code".

13. Do not return JSON.

14. Return ONLY the raw file content.

Generate the complete file now.
"""

        try:

            raw = self.brain.generate(
                prompt,
                json_mode=False
            )

        except Exception:

            return None

        if not isinstance(
            raw,
            str
        ):
            raw = str(raw)

        content = raw.strip()

        if content.startswith(
            "```"
        ):

            lines = content.splitlines()

            if lines:
                lines = lines[1:]

            if (
                lines
                and lines[-1].strip() == "```"
            ):
                lines = lines[:-1]

            content = "\n".join(
                lines
            ).strip()

        if self._contains_placeholder(
            content
        ):
            return None

        if not content:
            return None

        return content

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

    def decide(
        self,
        message,
        task_type,
        conversation="",
        knowledge="",
        tool_history="",
        plan="No plan."
    ):

        has_successful_tool = (
            self._has_successful_tool(
                tool_history
            )
        )

        prompt = self._build_decision_prompt(
            message=message,
            task_type=task_type,
            conversation=conversation,
            knowledge=knowledge,
            tool_history=tool_history,
            plan=plan
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
            plan=plan
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

