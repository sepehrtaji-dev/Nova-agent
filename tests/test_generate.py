import torch

from model.config import ModelConfig
from model.model import NovaLanguageModel
from model.generate import generate
from model.tokenizer import ByteBPETokenizer


def test_generate():
    tokenizer = ByteBPETokenizer()

    tokenizer.train(
        [
            "Hello world",
            "Hello Python",
            "Nova is an AI",
            "Python is powerful",
        ]
    )

    config = ModelConfig(
        vocab_size=tokenizer.vocab_size,
        max_sequence_length=64,
        embedding_dim=64,
        num_layers=2,
        num_heads=4,
        feed_forward_dim=256,
        dropout=0.0,
    )

    model = NovaLanguageModel(config)

    result = generate(
        model=model,
        tokenizer=tokenizer,
        prompt="Hello",
        max_new_tokens=10,
        temperature=1.0,
        top_k=10,
        device="cpu",
    )

    assert isinstance(result, str)
    assert len(result) > 0


if __name__ == "__main__":
    test_generate()

    print("Generation test passed.")