import json
import os
import numpy as np

from memory.embeddings import EmbeddingModel



class VectorMemory:


    def __init__(self):

        self.path = (
            "memory/database/memories.json"
        )

        os.makedirs(
            "memory/database",
            exist_ok=True
        )


        if not os.path.exists(self.path):

            with open(
                self.path,
                "w"
            ) as f:

                json.dump([],f)


        self.embedder = EmbeddingModel()

        self.memories = self.load()



    def load(self):

        with open(
            self.path,
            "r"
        ) as f:

            return json.load(f)



    def save(self):

        with open(
            self.path,
            "w"
        ) as f:

            json.dump(
                self.memories,
                f,
                indent=4
            )



    def add(self,text):

        vector = self.embedder.encode(
            text
        )


        self.memories.append(
            {
                "text":text,
                "vector":vector
            }
        )


        self.save()



    def search(
        self,
        query,
        limit=3
    ):

        q = np.array(
            self.embedder.encode(query)
        )


        results=[]


        for item in self.memories:

            v=np.array(
                item["vector"]
            )


            score = np.dot(q,v) / (
                np.linalg.norm(q)
                *
                np.linalg.norm(v)
            )


            results.append(
                (
                    score,
                    item["text"]
                )
            )


        results.sort(
            reverse=True
        )


        return [
            x[1]
            for x in results[:limit]
        ]