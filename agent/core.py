from model.ollama import OllamaBrain

from memory.manager import MemoryManager
from memory.extractor import MemoryExtractor



class NovaCore:


    def __init__(self):

        self.brain = OllamaBrain()

        self.memory = MemoryManager()

        self.extractor = MemoryExtractor()



    def ask(self,message):


        memories = self.extractor.extract(
            message
        )


        for memory in memories:

            self.memory.remember(
                *memory
            )


        context = self.memory.get_memory()


        prompt = f"""

You are Nova, a local AI agent.

User memory:
{context}


User:
{message}

Answer naturally.
"""


        return self.brain.generate(prompt)