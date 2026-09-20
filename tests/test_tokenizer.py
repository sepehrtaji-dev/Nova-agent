from pathlib import Path

from model.tokenizer import ByteBPETokenizer


TOKENIZER_PATH = Path("data/tokenizer/nova_tokenizer.json")


def main():
    print("=" * 60)
    print("NOVA TOKENIZER TEST")
    print("=" * 60)

    print("\nLoading tokenizer...")
    tokenizer = ByteBPETokenizer.load(TOKENIZER_PATH)

    print(f"Vocabulary size: {tokenizer.vocab_size:,}")
    print(f"Number of merges: {len(tokenizer.merges):,}")

    tests = [
        "Hello, how are you?",
        "Nova is a language model built from scratch.",
        "Artificial intelligence is fascinating.",
        "The quick brown fox jumps over the lazy dog.",
        "Python PyTorch Transformer Neural Network",
        "1234567890 !@#$%^&*()",
        "Hello 世界 🌍",
    ]

    print("\n" + "-" * 60)
    print("ENCODE / DECODE TESTS")
    print("-" * 60)

    for text in tests:
        token_ids = tokenizer.encode(text)
        decoded = tokenizer.decode(token_ids)

        print(f"\nOriginal : {text}")
        print(f"Tokens   : {len(token_ids)}")
        print(f"IDs      : {token_ids[:20]}")
        print(f"Decoded  : {decoded}")

        if decoded != text:
            print("WARNING: Round-trip mismatch!")
        else:
            print("PASS")

    print("\n" + "=" * 60)
    print("SPECIAL TOKEN TEST")
    print("=" * 60)

    token_ids = tokenizer.encode(
        "Hello Nova",
        add_bos=True,
        add_eos=True,
    )

    print(f"Token IDs: {token_ids}")
    print(f"First token: {token_ids[0]}")
    print(f"Last token : {token_ids[-1]}")

    assert token_ids[0] == tokenizer.SPECIAL_TOKENS["<bos>"]
    assert token_ids[-1] == tokenizer.SPECIAL_TOKENS["<eos>"]

    print("Special tokens: PASS")

    print("\n" + "=" * 60)
    print("ALL TOKENIZER TESTS FINISHED")
    print("=" * 60)


if __name__ == "__main__":
    main()