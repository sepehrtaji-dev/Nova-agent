from model.ollama import OllamaBrain
from tools import load_tools
from memory.manager import MemoryManager
from memory.extractor import MemoryExtractor
from memory.short_term import ShortTermMemory


class NovaCore:


    def __init__(self):

        self.brain = OllamaBrain()

        self.memory = MemoryManager()

        self.extractor = MemoryExtractor(
            self.brain
        )

        self.short_memory = ShortTermMemory()

        self.tools = load_tools()



    def ask(self, message):


        extracted = self.extractor.extract(
            message
        )


        for item in extracted.get(
            "memories",
            []
        ):

            self.memory.remember(
                item["category"],
                item["key"],
                item["value"]
            )


        memory_context = self.memory.get_memory()

        available_tools = self.tools.get_descriptions()

        self.short_memory.add("user",message)


        conversation = self.short_memory.get()
        prompt = f"""

You are Nova, a local AI agent.


Conversation history:

{conversation}


Long term memory:

{memory_context}


Current user message:

{message}


Answer naturally and remember the conversation.
"""


        response = self.brain.generate(prompt)


        self.short_memory.add(
            "assistant",
            response
        )


        return response