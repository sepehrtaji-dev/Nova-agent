import json
import os
import tempfile
import unittest

from model.tokenizer import ByteBPETokenizer, TokenizerConfig


class TokenizerRoundTripTests(unittest.TestCase):
    def test_training_and_reload_preserve_round_trip(self):
        tokenizer = ByteBPETokenizer(
            TokenizerConfig(vocab_size=512, min_frequency=1)
        )
        corpus = [
            "Hello world",
            "Hello Python",
            "Nova local agent",
            "Unicode: 世界 🌍",
            "12345 punctuation !?",
        ]
        tokenizer.train(corpus)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tokenizer.json")
            tokenizer.save(path)
            loaded = ByteBPETokenizer.load(path)

            for text in corpus:
                ids = loaded.encode(text)
                self.assertEqual(loaded.decode(ids), text)

            self.assertEqual(
                loaded.SPECIAL_TOKENS,
                tokenizer.SPECIAL_TOKENS,
            )
            self.assertEqual(
                list(loaded.merges.items()),
                list(tokenizer.merges.items()),
            )

    def test_saved_json_has_integer_vocab_ids(self):
        tokenizer = ByteBPETokenizer()
        tokenizer.train(["abc abc"])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tokenizer.json")
            tokenizer.save(path)
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)

            self.assertTrue(data["token_to_id"])
            self.assertTrue(
                all(isinstance(value, int) for value in data["token_to_id"].values())
            )


if __name__ == "__main__":
    unittest.main()
