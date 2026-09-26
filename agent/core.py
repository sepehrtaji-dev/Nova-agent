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



    def ask(self, message):


        print("CORE RECEIVED:", message)


        self.short_memory.add(
            "user",
            message
        )


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



        print("BEFORE ROUTER")


        decision = self.router.decide(
            message
        )


        print("AFTER ROUTER:", decision)



        tool_result = None


        if decision.get(
            "use_tool",
            False
        ):

            tool_result = self.tools.execute(
                decision["tool"],
                decision["input"]
            )


            print("TOOL RESULT:", tool_result)



        if tool_result:

            final_message = f"""

User asked:

{message}


A tool was executed.

Tool result:

{tool_result}


IMPORTANT:

Use ONLY the tool result.

Do not use memory.

Do not guess.

Answer the user with the exact information from the tool.

"""

        else:

            final_message = f"""

You are Nova, a local AI agent.

The following information comes from a real computer tool.

You MUST trust this information.

Never say you don't have access.

Never deny the tool result.

Never replace it with your own knowledge.


User request:

{message}


REAL TOOL OUTPUT:

{tool_result}


Explain the result clearly.

"""



        response = self.brain.generate(
            final_message
        )


        self.short_memory.add(
            "assistant",
            response
        )


        return response