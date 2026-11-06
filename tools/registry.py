import inspect


class ToolRegistry:

    def __init__(self):
        self.tools = {}
        self.default_access = {}

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

    def validate_input(self, name, input_data, allow_generated_missing=False):
        """Validate tool arguments against the supported JSON Schema subset."""
        if not self.exists(name):
            return False, f"Unknown tool: {name}"
        if not isinstance(input_data, dict):
            return False, "Tool input must be a JSON object."

        schema = self.tools[name].get("input_schema")
        if not isinstance(schema, dict):
            return True, None

        def validate(value, definition, field):
            if not isinstance(definition, dict):
                return False, f"Schema for '{field}' is invalid."

            expected = definition.get("type")
            checks = {
                "string": lambda item: isinstance(item, str),
                "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
                "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
                "boolean": lambda item: isinstance(item, bool),
                "object": lambda item: isinstance(item, dict),
                "array": lambda item: isinstance(item, list),
                "null": lambda item: item is None,
            }
            if expected in checks and not checks[expected](value):
                return False, f"Input field '{field}' must be {expected}."

            if "enum" in definition and value not in definition["enum"]:
                return False, f"Input field '{field}' is not an allowed value."

            if isinstance(value, str):
                if len(value) < int(definition.get("minLength", 0)):
                    return False, f"Input field '{field}' is too short."
                maximum = definition.get("maxLength")
                if maximum is not None and len(value) > int(maximum):
                    return False, f"Input field '{field}' is too long."

            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if "minimum" in definition and value < definition["minimum"]:
                    return False, f"Input field '{field}' is below its minimum."
                if "maximum" in definition and value > definition["maximum"]:
                    return False, f"Input field '{field}' exceeds its maximum."

            if isinstance(value, dict):
                properties = definition.get("properties", {})
                required = definition.get("required", [])
                if not isinstance(properties, dict) or not isinstance(required, list):
                    return False, f"Object schema for '{field}' is invalid."
                missing = [
                    key for key in required
                    if isinstance(key, str)
                    and (key not in value or value[key] is None)
                    and not (
                        allow_generated_missing
                        and isinstance(properties.get(key), dict)
                        and properties[key].get("x-generated") is True
                    )
                ]
                if missing:
                    return False, f"Missing required input field(s) in '{field}': " + ", ".join(missing)
                if definition.get("additionalProperties") is False:
                    unknown = sorted(set(value) - set(properties))
                    if unknown:
                        return False, f"Unexpected input field(s) in '{field}': " + ", ".join(unknown)
                for key, item in value.items():
                    if key in properties:
                        valid, reason = validate(item, properties[key], f"{field}.{key}")
                        if not valid:
                            return valid, reason

            if isinstance(value, list):
                minimum = definition.get("minItems")
                maximum = definition.get("maxItems")
                if minimum is not None and len(value) < int(minimum):
                    return False, f"Input field '{field}' has too few items."
                if maximum is not None and len(value) > int(maximum):
                    return False, f"Input field '{field}' has too many items."
                item_schema = definition.get("items")
                if isinstance(item_schema, dict):
                    for index, item in enumerate(value):
                        valid, reason = validate(item, item_schema, f"{field}[{index}]")
                        if not valid:
                            return valid, reason

            return True, None

        if schema.get("type", "object") != "object":
            return False, "Tool input schema must describe an object."
        return validate(input_data, schema, "input")

    def validate_planner_input(self, name, input_data):
        """Validate model-supplied fields before generated fields are prepared."""
        return self.validate_input(name, input_data, allow_generated_missing=True)

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