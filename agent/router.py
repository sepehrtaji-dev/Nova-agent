import json



class ToolRouter:


    def __init__(
        self,
        brain,
        tools
    ):

        self.brain = brain
        self.tools = tools



    def decide(
        self,
        message
    ):


        text = message.lower()



        # Direct rules for common commands

        if (
            "python version" in text
            or "show python" in text
            or "check python" in text
        ):

            return {
                "use_tool": True,
                "tool": "terminal",
                "input": "python --version"
            }



        if (
            "current username" in text
            or "who am i" in text
            or "username" in text
        ):

            return {
                "use_tool": True,
                "tool": "terminal",
                "input": "whoami"
            }



        if (
            "list files" in text
            or "show files" in text
            or "list folder" in text
            or "directory" in text
        ):

            return {
                "use_tool": True,
                "tool": "terminal",
                "input": "dir"
            }




        prompt = f"""
You are Nova Tool Router.

Your job is ONLY choosing tools.

Available tools:

{self.tools.get_descriptions()}


User message:

{message}


Return ONLY valid JSON.

No markdown.
No explanation.


Tool example:

{{
 "use_tool": true,
 "tool": "terminal",
 "input": "whoami"
}}


No tool example:

{{
 "use_tool": false
}}

Decision:
"""



        response = self.brain.generate(
            prompt
        )



        print(
            "ROUTER RAW:",
            response
        )



        # Clean markdown

        response = response.replace(
            "```json",
            ""
        )


        response = response.replace(
            "```",
            ""
        )


        response = response.strip()



        try:

            data = json.loads(
                response
            )


        except Exception:


            return {
                "use_tool": False
            }



        # Normalize bad Llama outputs


        if (
            data.get("use_tool") is True
        ):


            if "input" not in data:


                if "subcommands" in data:

                    commands = data["subcommands"]


                    if len(commands) > 0:

                        data["input"] = commands[0].get(
                            "name",
                            ""
                        )


                else:

                    data["use_tool"] = False



        return data