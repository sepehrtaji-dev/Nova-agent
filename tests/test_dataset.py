import torch

from model.tokenizer import ByteBPETokenizer
from training.dataset import FineWebTokenDataset


TOKENIZER_PATH = "data/tokenizer/nova_tokenizer.json"


def main():
    print("=" * 60)
    print("NOVA DATASET TEST")
    print("=" * 60)

    tokenizer = ByteBPETokenizer.load(TOKENIZER_PATH)

    print(f"Vocabulary size: {tokenizer.vocab_size:,}")

    dataset = FineWebTokenDataset(
        tokenizer=tokenizer,
        sequence_length=128,
        max_documents=100,
        max_tokens=2_000,
    )

    print()
    print("Reading FineWeb-Edu...")

    sample = next(iter(dataset))

    input_ids = sample["input_ids"]
    target_ids = sample["target_ids"]

    print("Input shape :", tuple(input_ids.shape))
    print("Target shape:", tuple(target_ids.shape))

    print()
    print("Input IDs:")
    print(input_ids[:20].tolist())

    print()
    print("Target IDs:")
    print(target_ids[:20].tolist())

    print()
    print("Decoded input:")
    print(repr(tokenizer.decode(input_ids.tolist())))

    print()
    print("Decoded target:")
    print(repr(tokenizer.decode(target_ids.tolist())))

    assert input_ids.shape == (128,)
    assert target_ids.shape == (128,)

    assert input_ids.dtype == torch.long
    assert target_ids.dtype == torch.long

    assert torch.equal(
        input_ids[1:],
        target_ids[:-1],
    )

    print()
    print("=" * 60)
    print("DATASET TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()