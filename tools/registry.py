class ToolRegistry:

    def __init__(self):
        self.tools = {}

    def register(
        self,
        name,
        description,
        function
    ):

        self.tools[name] = {
            "description": description,
            "function": function
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

            lines.append(
                f"- {name}: "
                f"{data['description']}"
            )

        return "\n".join(lines)