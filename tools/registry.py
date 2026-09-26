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



    def execute(
        self,
        name,
        input
    ):

        if name not in self.tools:

            return "Tool not found"


        return self.tools[name]["function"](
            input
        )



    def get_descriptions(self):

        result = []

        for name,tool in self.tools.items():

            result.append(
                f"{name}: {tool['description']}"
            )


        return "\n".join(result)