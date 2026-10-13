import inspect


class ToolRegistry:

    def __init__(self):
        self.tools = {}

    def register(
        self,
        name,
        description,
        function,
        capability="pc",
        input_schema=None,
        prepare_input=None,
        verifier_method=None,
    ):

        self.tools[name] = {
            "description": description,
            "function": function,
            "capability": capability,
            "input_schema": input_schema,
            "prepare_input": prepare_input,
            "verifier_method": verifier_method,
        }

    def validate_input(self, name, input_data):
        """Validate arguments against the selected tool's declared JSON schema."""
        if not self.exists(name):
            return False, f"Unknown tool: {name}"
        if not isinstance(input_data, dict):
            return False, "Tool input must be a JSON object."

        schema = self.tools[name].get("input_schema")
        if not isinstance(schema, dict):
            # The handler remains responsible for domain-specific validation
            # when no machine-readable contract is declared.
            return True, None
        if schema.get("type", "object") != "object":
            return False, "Tool input schema must describe an object."

        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            return False, "Tool input schema is invalid."

        missing = [
            key for key in required
            if isinstance(key, str)
            and (key not in input_data or input_data[key] is None)
        ]
        if missing:
            return False, "Missing required input field(s): " + ", ".join(missing)

        if schema.get("additionalProperties") is False:
            unknown = sorted(set(input_data) - set(properties))
            if unknown:
                return False, "Unexpected input field(s): " + ", ".join(unknown)

        type_checks = {
            "string": lambda value: isinstance(value, str),
            "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": lambda value: isinstance(value, bool),
            "object": lambda value: isinstance(value, dict),
            "array": lambda value: isinstance(value, list),
            "null": lambda value: value is None,
        }
        for key, value in input_data.items():
            definition = properties.get(key)
            if not isinstance(definition, dict):
                continue
            expected = definition.get("type")
            check = type_checks.get(expected)
            if check is not None and not check(value):
                return False, f"Input field '{key}' must be {expected}."
            if isinstance(value, str):
                if len(value) < int(definition.get("minLength", 0)):
                    return False, f"Input field '{key}' is too short."
                max_length = definition.get("maxLength")
                if max_length is not None and len(value) > int(max_length):
                    return False, f"Input field '{key}' is too long."
            if "enum" in definition and value not in definition["enum"]:
                return False, f"Input field '{key}' is not an allowed value."
        return True, None

    def exists(self, name):

        return name in self.tools

    def execute(
        self,
        name,
        input_data=None
    ):

        if not self.exists(name):
            return (
                f"Unknown tool: {name}"
            )

        function = self.tools[name][
            "function"
        ]

        try:

            if input_data is None:
                return function()

            return function(
                input_data
            )

        except Exception as e:

            return (
                f"Tool execution error: {e}"
            )

    def get_capability(self, name):
        data = self.tools.get(name)
        if not isinstance(data, dict):
            return None
        return data.get("capability")

    def get_descriptions(self):

        if not self.tools:
            return "No tools available."

        lines = []

        for name, data in self.tools.items():
            description = str(data.get("description", "")).strip()
            function = data.get("function")
            contract = inspect.getdoc(function) if callable(function) else None

            if contract:
                # Function documentation is the closest source of truth for the
                # accepted input contract. Keep prompts bounded for local models.
                contract = contract.strip()
                if len(contract) > 1600:
                    contract = contract[:1597].rstrip() + "..."
                lines.append(
                    f"- {name}: {description}\n"
                    f"  Input contract: {contract}"
                )
            else:
                lines.append(f"- {name}: {description}")

        return "\n".join(lines)