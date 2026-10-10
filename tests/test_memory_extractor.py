import unittest

from memory.extractor import MemoryExtractor


class MemoryExtractorTests(unittest.TestCase):
    def setUp(self):
        self.extractor = MemoryExtractor(brain=None)

    def test_only_explicit_values_are_kept(self):
        data = {
            "memories": [
                {"category": "profile", "key": "gpu", "value": "RTX 3060"},
                {"category": "profile", "key": "job", "value": "astronaut"},
            ]
        }
        result = self.extractor._validate(
            data,
            source_text="I use an RTX 3060 for my AI projects.",
        )
        self.assertEqual(
            result["memories"],
            [{"category": "profile", "key": "gpu", "value": "RTX 3060"}],
        )

    def test_labeled_password_is_not_saved(self):
        result = self.extractor._validate(
            {
                "memories": [
                    {"category": "profile", "key": "password", "value": "hunter2"},
                    {"category": "profile", "key": "work", "value": "Nova"},
                ]
            },
            source_text="Remember my password is hunter2 and I work on Nova.",
        )
        self.assertEqual(
            result["memories"],
            [{"category": "profile", "key": "work", "value": "Nova"}],
        )

    def test_api_keys_and_bearer_tokens_are_not_saved(self):
        result = self.extractor._validate(
            {
                "memories": [
                    {"category": "profile", "key": "api_key", "value": "sk-test-123"},
                    {"category": "profile", "key": "token", "value": "abc.def.ghi"},
                ]
            },
            source_text=(
                "My API key is sk-test-123 and my request uses "
                "Bearer abc.def.ghi"
            ),
        )
        self.assertEqual(result["memories"], [])

    def test_private_key_block_is_not_saved(self):
        private_key = (
            "-----BEGIN PRIVATE KEY-----\n"
            "sample-private-material\n"
            "-----END PRIVATE KEY-----"
        )
        result = self.extractor._validate(
            {
                "memories": [
                    {
                        "category": "profile",
                        "key": "private_key",
                        "value": private_key,
                    }
                ]
            },
            source_text="Please remember this: " + private_key,
        )
        self.assertEqual(result["memories"], [])

    def test_secret_is_rejected_even_when_embedded_in_a_longer_phrase(self):
        secret_phrase = "My password is hunter2"
        result = self.extractor._validate(
            {
                "memories": [
                    {"category": "profile", "key": "credential", "value": secret_phrase},
                ]
            },
            source_text=secret_phrase,
        )
        self.assertEqual(result["memories"], [])

    def test_secret_filter_does_not_store_unmentioned_values(self):
        result = self.extractor._validate(
            {
                "memories": [
                    {"category": "profile", "key": "gpu", "value": "RTX 3060"},
                ]
            },
            source_text="I use a GPU.",
        )
        self.assertEqual(result["memories"], [])


if __name__ == "__main__":
    unittest.main()
