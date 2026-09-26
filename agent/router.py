import json
import re


class ToolRouter:

    def __init__(self, brain, tools):
        self.brain = brain
        self.tools = tools

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
            data = json.loads(response)

            if isinstance(data, dict):
                return data

        except json.JSONDecodeError:
            pass

        start = response.find("{")
        end = response.rfind("}")

        if start == -1 or end == -1 or end <= start:
            return None

        try:
            data = json.loads(
                response[start:end + 1]
            )

            if isinstance(data, dict):
                return data

        except json.JSONDecodeError:
            return None

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
            "DIRECTORY_CREATED"
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

            if not isinstance(
                path,
                str
            ):
                return False

            return bool(
                path.strip()
            )

        if tool_name == "list_files":

            path = tool_input.get(
                "path",
                "."
            )

            return isinstance(
                path,
                str
            )

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

            if not isinstance(
                command,
                str
            ):
                return False

            return bool(
                command.strip()
            )

        if tool_name == "web_search":

            return True

        return False

    def classify_task(
        self,
        message,
        conversation=""
    ):
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
or OPERATE on something, use:

computer

USER REQUEST:

{message}

PREVIOUS CONVERSATION:

{conversation}

Return ONLY JSON.

{{"task_type":"conversation"}}

or

{{"task_type":"computer"}}
"""

        raw = self.brain.generate(
            prompt
        )

        data = self._extract_json(
            raw
        )

        if isinstance(
            data,
            dict
        ):

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
test, debug, inspect, or operate something.

USER REQUEST:

{message}
"""

        raw = self.brain.generate(
            repair_prompt
        )

        data = self._extract_json(
            raw
        )

        if isinstance(
            data,
            dict
        ):

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
        tool_history
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

Your ONLY job is to choose the NEXT REAL
ACTION.

You are NOT the final answer generator.

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
  "location": "desktop"
}}

Do NOT put "content" in this decision.

COMPLETION:

Return "respond" ONLY if the user's requested
operation is already completely finished and
verified.

If more work is required, return "tool".

USER REQUEST:

{message}

CONVERSATION:

{conversation}

KNOWLEDGE:

{knowledge}

Return ONLY JSON.

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

        action = (
            self._normalize_action(
                data.get("action")
            )
        )

        if action != "tool":
            return None

        tool = data.get(
            "tool"
        )

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
                return None

            if not isinstance(
                tool_input_object,
                dict
            ):
                return None

        else:
            return None

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

        action = (
            self._normalize_action(
                data.get("action")
            )
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
            data.get(
                "goal_complete"
            ) is True
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
        tool_history
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

If the computer task is incomplete,
choose the next real tool.

Available tools:

{self.tools.get_descriptions()}

IMPORTANT:

For write_file, ONLY return:

{{
  "path": "filename",
  "location": "desktop"
}}

Do NOT generate file content in the
decision JSON.

File content is generated separately.

For read_file:

{{
  "path": "filename",
  "location": "desktop"
}}

For list_files:

{{
  "path": ".",
  "location": "desktop"
}}

For create_directory:

{{
  "path": "directory_name",
  "location": "desktop"
}}

For terminal:

{{
  "command": "command",
  "location": "desktop"
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

Generate the COMPLETE ACTUAL CONTENT of
ONE FILE.

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

        raw = self.brain.generate(
            prompt
        )

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

            if lines and lines[-1].strip() == "```":
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

    def decide(
        self,
        message,
        task_type,
        conversation="",
        knowledge="",
        tool_history=""
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
            tool_history=tool_history
        )

        raw = self.brain.generate(
            prompt
        )

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

            if tool_decision:

                if (
                    tool_decision["tool"]
                    == "write_file"
                ):

                    tool_input = json.loads(
                        tool_decision["input"]
                    )

                    path = tool_input.get(
                        "path"
                    )

                    location = tool_input.get(
                        "location",
                        "projects"
                    )

                    self._last_file_generation = {
                        "path": path,
                        "location": location
                    }

                return tool_decision

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
            tool_history=tool_history
        )

        raw = self.brain.generate(
            repair_prompt
        )

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

                if (
                    tool_decision["tool"]
                    == "write_file"
                ):

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

                return tool_decision

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