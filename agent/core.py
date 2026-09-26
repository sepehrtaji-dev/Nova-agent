from model.ollama import OllamaBrain

from memory.manager import MemoryManager
from memory.extractor import MemoryExtractor
from memory.short_term import ShortTermMemory

from agent.router import ToolRouter

from tools import load_tools



class NovaCore:


    def __init__(self):

        self.brain = OllamaBrain()


        self.long_memory = MemoryManager()


        self.short_memory = ShortTermMemory()



        self.extractor = MemoryExtractor(
            self.brain
        )



        self.tools = load_tools()



        self.router = ToolRouter(
            self.brain,
            self.tools
        )




    def needs_tool(self, message):


        keywords = [

            "run",
            "execute",
            "terminal",
            "command",
            "python version",
            "check python",
            "show python",
            "whoami",
            "username",
            "list files",
            "show files",
            "list folder",
            "read file",
            "open file",
            "show file"

        ]


        text = message.lower()


        return any(
            key in text
            for key in keywords
        )





    def ask(self, message):


        print(
            "CORE RECEIVED:",
            message
        )



        self.short_memory.add(
            "user",
            message
        )



        # Memory extraction

        extracted = self.extractor.extract(
            message
        )


        for item in extracted.get(
            "memories",
            []
        ):


            self.long_memory.remember(
                item["category"],
                item["key"],
                item["value"]
            )



        tool_result = None



        # Only call router if needed

        if self.needs_tool(message):


            print(
                "BEFORE ROUTER"
            )


            decision = self.router.decide(
                message
            )


            print(
                "AFTER ROUTER:",
                decision
            )



            if (
                isinstance(decision, dict)
                and decision.get("use_tool") is True
            ):


                tool_result = self.tools.execute(
                    decision["tool"],
                    decision["input"]
                )


                print(
                    "TOOL RESULT:",
                    tool_result
                )



        else:


            decision = {
                "use_tool": False
            }




        # Build final prompt


        if tool_result:


            prompt = f"""

You are Nova, a local AI agent.


A real computer tool was executed.

The output below is real system information.


IMPORTANT RULES:

- Trust the tool output.
- Never deny access.
- Never invent another value.
- Never use old memory instead.


User request:

{message}


REAL TOOL OUTPUT:

{tool_result}


Answer clearly.


"""


        else:


            prompt = f"""

You are Nova.

You are a local AI agent powered by Llama 3.2:3B.


Conversation:

{self.short_memory.get()}


Memory:

{self.long_memory.get_memory()}


User:

{message}


Answer naturally.

"""



        response = self.brain.generate(
            prompt
        )



        self.short_memory.add(
            "assistant",
            response
        )


        return response