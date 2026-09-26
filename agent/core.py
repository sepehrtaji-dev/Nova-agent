from model.ollama import OllamaBrain
from memory.memory import LongTermMemory
from memory.extractor import MemoryExtractor


class NovaCore:


    def __init__(self):

        self.brain = OllamaBrain()

        self.memory = LongTermMemory()

        self.extractor = MemoryExtractor()



    def ask(self, message):


        memories = self.extractor.extract(
            message
        )


        for item in memories:

            category, key, value = item

            self.memory.add_fact(
                category,
                key,
                value
            )


        context = self.memory.get_context()


        prompt = f"""
You are Nova, a local AI agent.

User memory:
{context}

User message:
{message}
"""


        return self.brain.generate(
            prompt
        )