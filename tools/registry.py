import inspect


class ToolRegistry:

    def __init__(self):
        self.tools = {}

    def register(
        self,
        name,
        description,
        function,
        capability="pc"
    ):

        self.tools[name] = {
            "description": description,
            "function": function,
            "capability": capability,
        }

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