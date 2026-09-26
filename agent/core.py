from model.ollama import OllamaBrain

from memory.manager import MemoryManager
from memory.extractor import MemoryExtractor



class NovaCore:


    def __init__(self):

        self.brain = OllamaBrain()

        self.memory = MemoryManager()

        self.extractor = MemoryExtractor(
            self.brain
        )



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



        prompt = f"""

You are Nova.

You are a local AI agent powered by Llama 3.2:3B.

Use this user memory when relevant:

{memory_context}


User message:

{message}

Answer naturally.
"""


        return self.brain.generate(
            prompt
        )