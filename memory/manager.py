from memory.storage import MemoryStorage


class MemoryManager:


    def __init__(self):

        self.storage = MemoryStorage()

        self.data = self.storage.load()



    def remember(
        self,
        category,
        key,
        value
    ):

        if category not in self.data:

            self.data[category] = {}


        if isinstance(
            self.data[category],
            dict
        ):

            self.data[category][key] = value


        else:

            self.data[category].append(
                {
                    key:value
                }
            )


        self.storage.save(
            self.data
        )



    def get_memory(self):

        return self.data